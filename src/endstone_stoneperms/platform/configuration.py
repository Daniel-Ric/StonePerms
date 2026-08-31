from __future__ import annotations

from collections.abc import Callable, MutableMapping
from dataclasses import replace

from endstone.plugin import Plugin

from ..application.manager import StonePermsManager
from ..domain.validation import normalize_context_value, normalize_group_name
from ..settings import StonePermsSettings
from .contexts import EndstoneContextCalculator


class StonePermsConfiguration:
    def __init__(
        self,
        plugin: Plugin,
        manager: StonePermsManager,
        contexts: EndstoneContextCalculator,
        settings: StonePermsSettings,
        *,
        on_apply: Callable[[StonePermsSettings], object] | None = None,
    ) -> None:
        self._plugin = plugin
        self._manager = manager
        self._contexts = contexts
        self._configured = settings
        self._active = settings
        self._on_apply = on_apply

    def get_web_settings(self) -> dict[str, object]:
        return {
            "configured": _serialize(self._configured),
            "active": _serialize(self._active),
            "restartRequired": self._restart_required(),
            "limits": {
                "expiryCheckSeconds": {"minimum": 1, "maximum": 60},
                "catalogRefreshSeconds": {"minimum": 1, "maximum": 300},
            },
        }

    def update_settings(
        self,
        *,
        default_group: str,
        server_context: str,
        include_device_os_context: bool,
        include_locale_context: bool,
        expiry_check_seconds: int,
        catalog_refresh_seconds: int,
        debug: bool,
        actor: str,
    ) -> dict[str, object]:
        updated = replace(
            self._configured,
            default_group=normalize_group_name(default_group),
            server_context=normalize_context_value(server_context),
            include_device_os_context=bool(include_device_os_context),
            include_locale_context=bool(include_locale_context),
            expiry_check_ticks=_seconds_to_ticks(expiry_check_seconds, "expiryCheckSeconds", 60),
            catalog_check_ticks=_seconds_to_ticks(
                catalog_refresh_seconds, "catalogRefreshSeconds", 300
            ),
            debug=bool(debug),
        )
        before = _serialize(self._configured)
        after = _serialize(updated)
        changed = tuple(key for key, value in after.items() if before[key] != value)
        if not changed:
            return self.get_web_settings()

        _table(self._plugin.config, "permissions")["default_group"] = updated.default_group
        contexts = _table(self._plugin.config, "contexts")
        contexts.update(
            server=updated.server_context,
            include_device_os=updated.include_device_os_context,
            include_locale=updated.include_locale_context,
        )
        maintenance = _table(self._plugin.config, "maintenance")
        maintenance.update(
            expiry_check_ticks=updated.expiry_check_ticks,
            catalog_check_ticks=updated.catalog_check_ticks,
        )
        self._plugin.config["debug"] = updated.debug
        self._plugin.save_config()

        self._configured = updated
        self._active = replace(
            self._active,
            server_context=updated.server_context,
            include_device_os_context=updated.include_device_os_context,
            include_locale_context=updated.include_locale_context,
            debug=updated.debug,
        )
        self._contexts.update_settings(self._active)
        if self._on_apply is not None:
            self._on_apply(self._active)

        restart_required = self._restart_required()
        self._manager.record_settings_change(
            actor=actor,
            fields=changed,
            restart_required=restart_required,
        )
        return self.get_web_settings()

    def _restart_required(self) -> list[str]:
        fields: list[str] = []
        if self._configured.default_group != self._active.default_group:
            fields.append("defaultGroup")
        if self._configured.expiry_check_ticks != self._active.expiry_check_ticks:
            fields.append("expiryCheckSeconds")
        if self._configured.catalog_check_ticks != self._active.catalog_check_ticks:
            fields.append("catalogRefreshSeconds")
        return fields


def _serialize(settings: StonePermsSettings) -> dict[str, object]:
    return {
        "defaultGroup": settings.default_group,
        "serverContext": settings.server_context,
        "includeDeviceOsContext": settings.include_device_os_context,
        "includeLocaleContext": settings.include_locale_context,
        "expiryCheckSeconds": settings.expiry_check_ticks // 20,
        "catalogRefreshSeconds": settings.catalog_check_ticks // 20,
        "debug": settings.debug,
    }


def _seconds_to_ticks(value: int, label: str, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a whole number of seconds")
    try:
        seconds = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a whole number of seconds") from exc
    if seconds < 1 or seconds > maximum:
        raise ValueError(f"{label} must be between 1 and {maximum} seconds")
    return seconds * 20


def _table(root: MutableMapping[str, object], key: str) -> MutableMapping[str, object]:
    value = root.setdefault(key, {})
    if not isinstance(value, MutableMapping):
        raise ValueError(f"Configuration section {key!r} must be a table")
    return value
