from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from endstone.plugin import Plugin

from ..application.editor import (
    EditorActorMismatchError,
    EditorProtocolError,
    EditorSessionBusyError,
    EditorSessionConsumedError,
    EditorSessionExpiredError,
    EditorSessionNotFoundError,
)
from .service import StonePermsService

TRANSPORT_PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 1_048_576


@dataclass(frozen=True, slots=True)
class WebConnectionStatus:
    enabled: bool
    configured: bool
    connected: bool
    ready: bool
    api_url: str
    server_id: str
    last_error: str


@dataclass(frozen=True, slots=True)
class WebLoginCode:
    code: str
    expires_at: int
    username: str | None
    dashboard_url: str
    claimed_server: bool


class StonePermsWebConnector:
    def __init__(
        self,
        plugin: Plugin,
        service: StonePermsService,
        *,
        enabled: bool = False,
        api_url: str = "",
        server_id: str = "",
        server_token: str = "",
        server_name: str = "Endstone server",
        connect_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._plugin = plugin
        self._service = service
        self._enabled = enabled
        self._api_url = api_url.rstrip("/")
        self._server_id = server_id
        self._server_token = server_token
        self._server_name = server_name
        self._connect_factory = connect_factory
        self._instance_id = self._load_instance_id()
        self._stop: threading.Event | None = None
        self._send_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._socket: Any | None = None
        self._connected = False
        self._ready = False
        self._last_error = ""
        self._shutting_down = False

    @property
    def status(self) -> WebConnectionStatus:
        with self._state_lock:
            return WebConnectionStatus(
                enabled=self._enabled,
                configured=bool(self._api_url and self._server_id and self._server_token),
                connected=self._connected,
                ready=self._ready,
                api_url=self._api_url,
                server_id=self._server_id,
                last_error=self._last_error,
            )

    def start(self) -> None:
        with self._state_lock:
            if (
                self._shutting_down
                or not self._enabled
                or not self._api_url
                or not self._server_id
                or not self._server_token
                or (self._thread is not None and self._thread.is_alive())
            ):
                return
            stop = threading.Event()
            self._stop = stop
            self._thread = threading.Thread(
                target=self._run,
                args=(stop,),
                name="StonePerms-Web",
                daemon=True,
            )
            self._thread.start()

    def close(self) -> None:
        with self._state_lock:
            stop = self._stop
            thread = self._thread
            connection = self._socket
            self._socket = None
            self._connected = False
            self._ready = False
            if stop is not None:
                stop.set()
        if connection is not None:
            self._close_connection(connection)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)
        with self._state_lock:
            if self._thread is thread:
                self._thread = None
                self._stop = None

    def shutdown(self) -> None:
        with self._state_lock:
            self._shutting_down = True
        self.close()

    def pair(self, api_url: str, code: str, server_name: str | None = None) -> str:
        normalized_url = _validate_api_url(api_url)
        name = str(server_name or self._server_name).strip()
        if not name or len(name) > 80:
            raise ValueError("Server name must contain 1-80 characters")
        payload = {
            "code": str(code).strip(),
            "instanceId": self._instance_id,
            "name": name,
            "pluginVersion": str(self._plugin.version),
            "protocolVersion": TRANSPORT_PROTOCOL_VERSION,
        }
        result = _json_request(f"{normalized_url}/v1/plugin/pair", "POST", payload)
        server_id = _required_text(result.get("serverId"), "serverId", 64)
        server_token = _required_text(result.get("serverToken"), "serverToken", 128)
        if not server_token.startswith("sp_srv_"):
            raise ValueError("API returned an invalid server credential")
        self._save_credential(normalized_url, server_id, server_token, name)
        return server_id

    def pair_async(
        self,
        api_url: str,
        code: str,
        server_name: str | None,
        callback: Callable[[str | None, Exception | None], None],
    ) -> None:
        def work() -> None:
            try:
                server_id, error = self.pair(api_url, code, server_name), None
            except Exception as exc:
                server_id, error = None, exc
            self._plugin.server.scheduler.run_task(self._plugin, lambda: callback(server_id, error))

        threading.Thread(target=work, name="StonePerms-Pair", daemon=True).start()

    def unpair(self) -> bool:
        status = self.status
        revoked = False
        if status.configured:
            try:
                _json_request(
                    f"{self._api_url}/v1/plugin/credential",
                    "DELETE",
                    None,
                    bearer=self._server_token,
                    expect_empty=True,
                )
                revoked = True
            except (OSError, ValueError):
                revoked = False
        self.close()
        web_config = self._plugin.config.setdefault("web", {})
        if not isinstance(web_config, MutableMapping):
            raise ValueError("The web configuration section must be a table")
        web_config.update(enabled=False, server_id="", server_token="")
        self._plugin.save_config()
        with self._state_lock:
            self._enabled = False
            self._server_id = ""
            self._server_token = ""
        return revoked

    def unpair_async(self, callback: Callable[[bool | None, Exception | None], None]) -> None:
        def work() -> None:
            try:
                revoked, error = self.unpair(), None
            except Exception as exc:
                revoked, error = None, exc
            self._plugin.server.scheduler.run_task(self._plugin, lambda: callback(revoked, error))

        threading.Thread(target=work, name="StonePerms-Unpair", daemon=True).start()

    def create_login_code(self) -> WebLoginCode:
        status = self.status
        claimed_server = not status.configured
        if claimed_server:
            api_url = _validate_api_url(status.api_url)
            result = _json_request(
                f"{api_url}/v1/plugin/bootstrap-login-codes",
                "POST",
                {
                    "instanceId": self._instance_id,
                    "name": self._server_name,
                    "pluginVersion": str(self._plugin.version),
                    "protocolVersion": TRANSPORT_PROTOCOL_VERSION,
                },
            )
            server_id = _required_text(result.get("serverId"), "serverId", 64)
            server_token = _required_text(result.get("serverToken"), "serverToken", 128)
            if not server_token.startswith("sp_srv_"):
                raise ValueError("API returned an invalid server credential")
            self._save_credential(api_url, server_id, server_token, self._server_name)
        else:
            result = _json_request(
                f"{status.api_url}/v1/plugin/login-codes",
                "POST",
                {},
                bearer=self._server_token,
            )
        code = _required_text(result.get("code"), "code", 16)
        username = _optional_text(result.get("username"), "username", 32)
        dashboard_url = _required_text(result.get("dashboardUrl"), "dashboardUrl", 512)
        expires_at = _integer(result.get("expiresAt"), "expiresAt", 1, 4_102_444_800)
        return WebLoginCode(
            code=code,
            expires_at=expires_at,
            username=username,
            dashboard_url=dashboard_url,
            claimed_server=claimed_server or username is None,
        )

    def create_login_code_async(
        self,
        callback: Callable[[WebLoginCode | None, Exception | None], None],
    ) -> None:
        def work() -> None:
            try:
                login_code, error = self.create_login_code(), None
            except Exception as exc:
                login_code, error = None, exc
            self._plugin.server.scheduler.run_task(self._plugin, lambda: callback(login_code, error))

        threading.Thread(target=work, name="StonePerms-Web-Login", daemon=True).start()

    def _save_credential(
        self,
        api_url: str,
        server_id: str,
        server_token: str,
        server_name: str,
    ) -> None:
        with self._state_lock:
            if self._shutting_down:
                raise RuntimeError("StonePerms is shutting down")
        self.close()
        web_config = self._plugin.config.setdefault("web", {})
        if not isinstance(web_config, MutableMapping):
            raise ValueError("The web configuration section must be a table")
        web_config.update(
            enabled=True,
            api_url=api_url,
            server_id=server_id,
            server_token=server_token,
            server_name=server_name,
        )
        self._plugin.save_config()
        with self._state_lock:
            self._enabled = True
            self._api_url = api_url
            self._server_id = server_id
            self._server_token = server_token
            self._server_name = server_name
            self._last_error = ""
        self.start()

    def _run(self, stop: threading.Event) -> None:
        backoff = 1.0
        http_transport = False
        while not stop.is_set():
            if http_transport:
                try:
                    self._poll_http(stop)
                    backoff = 1.0
                    continue
                except Exception as exc:
                    if not stop.is_set():
                        message = str(exc).strip() or exc.__class__.__name__
                        with self._state_lock:
                            self._connected = False
                            self._ready = False
                            self._last_error = message[:300]
                        self._plugin.logger.warning(f"StonePerms API connection failed: {message}")
                if not stop.wait(backoff):
                    backoff = min(30.0, backoff * 2)
                continue
            try:
                connection = None
                try:
                    connection = self._connect()
                except Exception as exc:
                    if _requires_http_transport(exc):
                        http_transport = True
                        with self._state_lock:
                            self._last_error = ""
                        self._plugin.logger.info(
                            "WebSocket upgrade unavailable; using the HTTPS plugin connection"
                        )
                        continue
                    raise
                if stop.is_set():
                    break
                with self._state_lock:
                    self._socket = connection
                    self._connected = True
                    self._ready = False
                    self._last_error = ""
                self._send(
                    {
                        "type": "hello",
                        "instanceId": self._instance_id,
                        "pluginVersion": str(self._plugin.version),
                        "protocolVersion": TRANSPORT_PROTOCOL_VERSION,
                    },
                    connection=connection,
                )
                backoff = 1.0
                self._receive_loop(connection, stop)
            except Exception as exc:
                if not stop.is_set():
                    message = str(exc).strip() or exc.__class__.__name__
                    with self._state_lock:
                        self._last_error = message[:300]
                    self._plugin.logger.warning(f"StonePerms API connection failed: {message}")
            finally:
                with self._state_lock:
                    if self._socket is connection:
                        self._socket = None
                        self._connected = False
                        self._ready = False
                if connection is not None:
                    self._close_connection(connection, report_failure=not stop.is_set())
            if not stop.wait(backoff):
                backoff = min(30.0, backoff * 2)

    def _poll_http(self, stop: threading.Event) -> None:
        result = _json_request(
            f"{self._api_url}/v1/plugin/poll",
            "POST",
            {},
            bearer=self._server_token,
        )
        if stop.is_set():
            return
        _exact_keys(result, {"request", "pollAfterMs"})
        delay_ms = _integer(result["pollAfterMs"], "pollAfterMs", 250, 5_000)
        with self._state_lock:
            self._connected = True
            self._ready = True
            self._last_error = ""
        message = result["request"]
        if message is not None:
            if not isinstance(message, Mapping):
                raise ValueError("API poll response contains an invalid request")
            self._schedule_request(message, stop=stop, http_response=True)
        stop.wait(delay_ms / 1_000)

    def _connect(self) -> Any:
        factory = self._connect_factory
        if factory is None:
            try:
                import websocket
            except ImportError as exc:
                raise RuntimeError(
                    "websocket-client is required when the StonePerms web bridge is enabled"
                ) from exc
            factory = websocket.create_connection
        return factory(
            _websocket_url(self._api_url),
            header=[f"Authorization: Bearer {self._server_token}"],
            timeout=10,
            enable_multithread=True,
        )

    def _receive_loop(self, connection: Any, stop: threading.Event) -> None:
        connection.settimeout(2)
        last_heartbeat = time.monotonic()
        while not stop.is_set():
            if time.monotonic() - last_heartbeat >= 20:
                self._send({"type": "heartbeat"}, connection=connection)
                last_heartbeat = time.monotonic()
            message = self._receive_message(connection)
            if message is not None:
                self._handle_message(message, stop, connection)

    @staticmethod
    def _receive_message(connection: Any) -> Mapping[str, object] | None:
        try:
            raw = connection.recv()
        except TimeoutError:
            return None
        except Exception as exc:
            if exc.__class__.__name__ == "WebSocketTimeoutException":
                return None
            raise

        if raw is None or raw == "":
            raise ConnectionError("API closed the WebSocket connection")
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_MESSAGE_BYTES:
            raise ValueError("API sent an unsupported or oversized message")
        return _decode_message(raw)

    def _handle_message(
        self,
        message: Mapping[str, object],
        stop: threading.Event,
        connection: Any,
    ) -> None:
        if stop.is_set():
            return
        message_type = message.get("type")
        if message_type == "helloAck":
            _exact_keys(message, {"type", "protocolVersion", "heartbeatSeconds"})
            if message["protocolVersion"] != TRANSPORT_PROTOCOL_VERSION:
                raise ValueError("API uses an unsupported transport protocol")
            with self._state_lock:
                self._ready = True
            return
        if message_type == "heartbeatAck":
            _exact_keys(message, {"type"})
            return
        if message_type == "request":
            self._schedule_request(message, stop=stop, connection=connection)
            return
        raise ValueError("API sent an unsupported message type")

    def _schedule_request(
        self,
        message: Mapping[str, object],
        *,
        stop: threading.Event,
        http_response: bool = False,
        connection: Any | None = None,
    ) -> None:
        _exact_keys(message, {"type", "requestId", "action", "actor", "payload"})
        request_id = _required_text(message["requestId"], "requestId", 128)
        actor = _required_text(message["actor"], "actor", 128)
        action = _required_text(message["action"], "action", 64)
        payload = message["payload"]
        if not isinstance(payload, Mapping):
            raise ValueError("Web request payload must be an object")

        def execute() -> None:
            if stop.is_set():
                return
            response = self._request_response(request_id, action, actor, payload)
            if stop.is_set():
                return
            if http_response:
                threading.Thread(
                    target=self._send_http_response,
                    args=(response, stop),
                    name="StonePerms-Web-Response",
                    daemon=True,
                ).start()
                return
            try:
                self._send(response, connection=connection)
            except (ConnectionError, OSError):
                return

        self._plugin.server.scheduler.run_task(self._plugin, execute)

    def _send_http_response(
        self,
        response: Mapping[str, object],
        stop: threading.Event,
    ) -> None:
        payload = {key: value for key, value in response.items() if key != "type"}
        error: Exception | None = None
        for attempt in range(3):
            if stop.is_set():
                return
            try:
                _json_request(
                    f"{self._api_url}/v1/plugin/responses",
                    "POST",
                    payload,
                    bearer=self._server_token,
                    expect_empty=True,
                )
                return
            except Exception as exc:
                error = exc
                if stop.wait(0.5 * (2**attempt)):
                    return
        if error is not None and not stop.is_set():
            self._plugin.logger.warning(f"StonePerms could not return a dashboard response: {error}")

    def _request_response(
        self,
        request_id: str,
        action: str,
        actor: str,
        payload: Mapping[str, object],
    ) -> Mapping[str, object]:
        try:
            result = self._dispatch_request(action, payload, actor)
            return {
                "type": "response",
                "requestId": request_id,
                "ok": True,
                "payload": result,
            }
        except Exception as exc:
            code, description = _public_error(exc)
            if code == "INTERNAL_ERROR":
                self._plugin.logger.error(f"StonePerms web request failed: {exc}")
            return {
                "type": "response",
                "requestId": request_id,
                "ok": False,
                "error": {"code": code, "message": description},
            }

    def _dispatch_request(
        self,
        action: str,
        payload: Mapping[str, object],
        actor: str,
    ) -> object:
        family = action.partition(".")[0]
        handler = {
            "editor": self._handle_editor_request,
            "directory": self._handle_directory_request,
            "display": self._handle_display_request,
            "settings": self._handle_settings_request,
            "player": self._handle_player_request,
            "group": self._handle_group_request,
            "track": self._handle_track_request,
            "audit": self._handle_audit_request,
        }.get(family)
        if handler is None:
            raise ValueError(f"Unsupported web action {action!r}")
        return handler(action, payload, actor)

    def _handle_editor_request(
        self,
        action: str,
        payload: Mapping[str, object],
        actor: str,
    ) -> object:
        if action == "editor.applyChanges":
            return self._service.apply_editor_changes(dict(payload), actor=actor)
        if action != "editor.createSession":
            raise ValueError(f"Unsupported web action {action!r}")

        _exact_keys(payload, {"users", "includeGroups", "includeTracks"})
        users = payload["users"]
        if not isinstance(users, list) or any(not isinstance(user, str) for user in users):
            raise ValueError("Editor users must be an array of strings")
        return self._service.create_editor_session(
            actor=actor,
            users=users,
            include_groups=_boolean(payload["includeGroups"], "includeGroups"),
            include_tracks=_boolean(payload["includeTracks"], "includeTracks"),
        )

    def _handle_directory_request(
        self,
        action: str,
        payload: Mapping[str, object],
        _actor: str,
    ) -> object:
        if action != "directory.snapshot":
            raise ValueError(f"Unsupported web action {action!r}")
        _exact_keys(payload, set())
        return self._service.get_web_directory()

    def _handle_display_request(
        self,
        action: str,
        payload: Mapping[str, object],
        _actor: str,
    ) -> object:
        if action == "display.getSettings":
            _exact_keys(payload, set())
            return self._service.get_web_display_settings()
        if action != "display.updateSettings":
            raise ValueError(f"Unsupported web action {action!r}")

        _exact_keys(payload, {"chatEnabled", "chatFormat", "nametagEnabled", "nametagFormat"})
        return self._service.update_web_display_settings(
            chat_enabled=_boolean(payload["chatEnabled"], "chatEnabled"),
            chat_format=_display_text(payload["chatFormat"], "chatFormat"),
            nametag_enabled=_boolean(payload["nametagEnabled"], "nametagEnabled"),
            nametag_format=_display_text(payload["nametagFormat"], "nametagFormat"),
        )

    def _handle_settings_request(
        self,
        action: str,
        payload: Mapping[str, object],
        actor: str,
    ) -> object:
        if action == "settings.get":
            _exact_keys(payload, set())
            return self._service.get_web_plugin_settings()
        if action != "settings.update":
            raise ValueError(f"Unsupported web action {action!r}")

        _exact_keys(
            payload,
            {
                "defaultGroup",
                "serverContext",
                "includeDeviceOsContext",
                "includeLocaleContext",
                "expiryCheckSeconds",
                "catalogRefreshSeconds",
                "debug",
            },
        )
        return self._service.update_web_plugin_settings(
            default_group=_required_text(payload["defaultGroup"], "defaultGroup", 64),
            server_context=_required_text(payload["serverContext"], "serverContext", 64),
            include_device_os_context=_boolean(payload["includeDeviceOsContext"], "includeDeviceOsContext"),
            include_locale_context=_boolean(payload["includeLocaleContext"], "includeLocaleContext"),
            expiry_check_seconds=_integer(payload["expiryCheckSeconds"], "expiryCheckSeconds", 1, 60),
            catalog_refresh_seconds=_integer(
                payload["catalogRefreshSeconds"], "catalogRefreshSeconds", 1, 300
            ),
            debug=_boolean(payload["debug"], "debug"),
            actor=actor,
        )

    def _handle_player_request(
        self,
        action: str,
        payload: Mapping[str, object],
        _actor: str,
    ) -> object:
        _exact_keys(payload, {"identifier"})
        identifier = _required_text(payload["identifier"], "identifier", 128)
        if action == "player.inspect":
            return self._service.get_web_player(identifier)
        if action == "player.avatar":
            return self._service.get_web_player_avatar(identifier)
        raise ValueError(f"Unsupported web action {action!r}")

    def _handle_group_request(
        self,
        action: str,
        payload: Mapping[str, object],
        actor: str,
    ) -> object:
        if action == "group.create":
            _exact_keys(payload, {"name", "displayName", "weight"})
            return self._service.create_web_group(
                _required_text(payload["name"], "name", 64),
                _optional_text(payload["displayName"], "displayName", 128),
                _integer(payload["weight"], "weight", -(2**31), 2**31 - 1),
                actor=actor,
            )
        if action == "group.setWeight":
            _exact_keys(payload, {"name", "weight"})
            return self._service.set_web_group_weight(
                _required_text(payload["name"], "name", 64),
                _integer(payload["weight"], "weight", -(2**31), 2**31 - 1),
                actor=actor,
            )
        if action == "group.delete":
            _exact_keys(payload, {"name"})
            return self._service.delete_web_group(
                _required_text(payload["name"], "name", 64),
                actor=actor,
            )
        raise ValueError(f"Unsupported web action {action!r}")

    def _handle_track_request(
        self,
        action: str,
        payload: Mapping[str, object],
        actor: str,
    ) -> object:
        if action == "track.create":
            _exact_keys(payload, {"name"})
            return self._service.create_web_track(
                _required_text(payload["name"], "name", 64),
                actor=actor,
            )
        if action == "track.rename":
            _exact_keys(payload, {"name", "newName"})
            return self._service.rename_web_track(
                _required_text(payload["name"], "name", 64),
                _required_text(payload["newName"], "newName", 64),
                actor=actor,
            )
        if action == "track.clone":
            _exact_keys(payload, {"name", "cloneName"})
            return self._service.clone_web_track(
                _required_text(payload["name"], "name", 64),
                _required_text(payload["cloneName"], "cloneName", 64),
                actor=actor,
            )
        if action == "track.delete":
            _exact_keys(payload, {"name"})
            return self._service.delete_web_track(
                _required_text(payload["name"], "name", 64),
                actor=actor,
            )
        if action == "track.moveUser":
            _exact_keys(payload, {"identifier", "track", "direction"})
            return self._service.move_web_player(
                _required_text(payload["identifier"], "identifier", 128),
                _required_text(payload["track"], "track", 64),
                _required_text(payload["direction"], "direction", 16),
                actor=actor,
            )
        raise ValueError(f"Unsupported web action {action!r}")

    def _handle_audit_request(
        self,
        action: str,
        payload: Mapping[str, object],
        _actor: str,
    ) -> object:
        if action != "audit.list":
            raise ValueError(f"Unsupported web action {action!r}")
        _exact_keys(payload, {"limit"})
        return self._service.get_web_audit(_integer(payload["limit"], "limit", 1, 200))

    def _send(self, message: Mapping[str, object], *, connection: Any | None = None) -> None:
        encoded = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > MAX_MESSAGE_BYTES:
            raise ValueError("StonePerms web response exceeds 1 MiB")
        with self._send_lock:
            with self._state_lock:
                active_connection = self._socket
            if active_connection is None or (
                connection is not None and active_connection is not connection
            ):
                raise ConnectionError("StonePerms API is not connected")
            active_connection.send(encoded)

    def _close_connection(self, connection: Any, *, report_failure: bool = True) -> None:
        try:
            connection.close()
        except Exception as exc:
            if report_failure:
                message = str(exc).strip() or exc.__class__.__name__
                self._plugin.logger.warning(
                    f"Could not close the StonePerms API connection: {message}"
                )

    def _load_instance_id(self) -> str:
        path = Path(self._plugin.data_folder) / "instance-id"
        try:
            value = path.read_text(encoding="ascii").strip()
            return str(uuid.UUID(value))
        except (FileNotFoundError, UnicodeError, ValueError):
            value = str(uuid.uuid4())
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value + "\n", encoding="ascii")
            return value


def _validate_api_url(value: str) -> str:
    raw = str(value).strip().rstrip("/")
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("API URL must be an absolute HTTP(S) URL without credentials")
    if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError("API URL must not contain a path, query, or fragment")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Remote StonePerms APIs require HTTPS")
    return urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))


def _websocket_url(api_url: str) -> str:
    parsed = urlparse(api_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunparse((scheme, parsed.netloc, "/v1/plugin/connect", "", "", ""))


def _requires_http_transport(error: Exception) -> bool:
    return error.__class__.__name__ == "WebSocketBadStatusException" or (
        "websocket" in str(error).lower() and "header" in str(error).lower()
    )


def _json_request(
    url: str,
    method: str,
    payload: Mapping[str, object] | None,
    *,
    bearer: str = "",
    expect_empty: bool = False,
) -> dict[str, object]:
    data = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = {"Accept": "application/json", "User-Agent": "StonePerms-Plugin/0.8"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read(MAX_MESSAGE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raw = exc.read(MAX_MESSAGE_BYTES + 1)
        try:
            error = json.loads(raw.decode("utf-8"))["error"]["message"]
        except (KeyError, TypeError, ValueError, UnicodeError):
            error = f"API returned HTTP {exc.code}"
        raise ValueError(str(error)[:500]) from exc
    except urllib.error.URLError as exc:
        raise OSError(f"Could not reach StonePerms API: {exc.reason}") from exc
    if len(raw) > MAX_MESSAGE_BYTES:
        raise ValueError("API response exceeds 1 MiB")
    if expect_empty and not raw:
        return {}
    try:
        result = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ValueError("API returned invalid JSON") from exc
    if not isinstance(result, dict):
        raise ValueError("API response must be an object")
    return result


def _decode_message(raw: str) -> Mapping[str, object]:
    try:
        result = json.loads(raw)
    except ValueError as exc:
        raise ValueError("API sent invalid JSON") from exc
    if not isinstance(result, dict) or any(not isinstance(key, str) for key in result):
        raise ValueError("API message must be an object")
    return result


def _exact_keys(value: Mapping[str, object], expected: set[str]) -> None:
    if set(value) != expected:
        raise ValueError("Web message has missing or unknown fields")


def _required_text(value: object, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{label} must contain 1-{maximum} characters")
    return value.strip()


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be true or false")
    return value


def _display_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ValueError(f"{label} must contain 1-256 characters")
    return value


def _optional_text(value: object, label: str, maximum: int) -> str | None:
    if value is None:
        return None
    return _required_text(value, label, maximum)


def _integer(value: object, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be an integer between {minimum} and {maximum}")
    return value


def _public_error(error: Exception) -> tuple[str, str]:
    known = {
        EditorSessionNotFoundError: "EDITOR_SESSION_NOT_FOUND",
        EditorSessionExpiredError: "EDITOR_SESSION_EXPIRED",
        EditorSessionConsumedError: "EDITOR_SESSION_CONSUMED",
        EditorSessionBusyError: "EDITOR_SESSION_BUSY",
        EditorActorMismatchError: "EDITOR_ACTOR_MISMATCH",
        EditorProtocolError: "EDITOR_PROTOCOL_ERROR",
        LookupError: "NOT_FOUND",
        ValueError: "INVALID_REQUEST",
    }
    for error_type, code in known.items():
        if isinstance(error, error_type):
            return code, (str(error).strip() or code)[:500]
    return "INTERNAL_ERROR", "The plugin could not complete the request"
