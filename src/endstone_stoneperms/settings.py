from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from string import Formatter

from .domain.validation import normalize_context_value, normalize_group_name
from .web_defaults import PUBLIC_API_URL

DEFAULT_CHAT_FORMAT = "{prefix}§f{name}{suffix} §8» §f{message}"
DEFAULT_NAMETAG_FORMAT = "{prefix}§f{name}{suffix}"
CHAT_PLACEHOLDERS = frozenset({"prefix", "name", "suffix", "message"})
NAMETAG_PLACEHOLDERS = frozenset({"prefix", "name", "suffix"})


@dataclass(frozen=True, slots=True)
class DisplaySettings:
    chat_enabled: bool = False
    chat_format: str = DEFAULT_CHAT_FORMAT
    nametag_enabled: bool = False
    nametag_format: str = DEFAULT_NAMETAG_FORMAT


@dataclass(frozen=True, slots=True)
class StartupSettings:
    show_summary: bool = True
    check_server_properties: bool = True


@dataclass(frozen=True, slots=True)
class MySqlSettings:
    host: str = "127.0.0.1"
    port: int = 3306
    database: str = "stoneperms"
    username: str = "stoneperms"
    password: str = dataclass_field(default="", repr=False)
    connect_timeout: int = 5
    read_timeout: int = 10
    ssl_ca: str = ""


@dataclass(frozen=True, slots=True)
class StonePermsSettings:
    database_file: str = "stoneperms.db"
    default_group: str = "default"
    server_context: str = "global"
    expiry_check_ticks: int = 20
    catalog_check_ticks: int = 100
    include_device_os_context: bool = False
    include_locale_context: bool = False
    debug: bool = False
    web_enabled: bool = False
    web_api_url: str = PUBLIC_API_URL
    web_server_id: str = ""
    web_server_token: str = ""
    web_server_name: str = "Endstone server"
    startup: StartupSettings = StartupSettings()
    display: DisplaySettings = DisplaySettings()
    storage_backend: str = "sqlite"
    storage_server_id: str = ""
    storage_sync_ticks: int = 20
    mysql: MySqlSettings = MySqlSettings()


def load_settings(raw: Mapping[str, object]) -> StonePermsSettings:
    storage = _section(raw, "storage")
    permissions = _section(raw, "permissions")
    contexts = _section(raw, "contexts")
    maintenance = _section(raw, "maintenance")
    startup = _section(raw, "startup")
    web = _section(raw, "web")
    display = _section(raw, "display")
    chat_display = _section(display, "chat")
    nametag_display = _section(display, "nametag")
    mysql = _section(storage, "mysql")

    backend = str(storage.get("backend", "sqlite")).strip().casefold()
    if backend not in {"sqlite", "mysql"}:
        raise ValueError("storage.backend must be sqlite or mysql")
    server_id = str(storage.get("server_id", "")).strip()
    if backend == "mysql" and not server_id:
        raise ValueError("storage.server_id must identify this server when using MySQL")
    if server_id:
        server_id = normalize_context_value(server_id)
    mysql_settings = MySqlSettings(
        host=_bounded_text(mysql.get("host"), "127.0.0.1", 255),
        port=_bounded_int(mysql.get("port"), 3306, 1, 65535),
        database=_bounded_text(mysql.get("database"), "stoneperms", 64),
        username=_bounded_text(mysql.get("username"), "stoneperms", 128),
        password=str(mysql.get("password", "")),
        connect_timeout=_bounded_int(mysql.get("connect_timeout"), 5, 1, 60),
        read_timeout=_bounded_int(mysql.get("read_timeout"), 10, 1, 120),
        ssl_ca=_bounded_text(mysql.get("ssl_ca"), "", 1024),
    )
    if backend == "mysql" and not all(
        (mysql_settings.host, mysql_settings.database, mysql_settings.username)
    ):
        raise ValueError("MySQL host, database, and username must not be empty")

    database_file = str(storage.get("database", "stoneperms.db")).strip()
    if not database_file or "/" in database_file or "\\" in database_file or database_file in {".", ".."}:
        raise ValueError("storage.database must be a filename inside the plugin data directory")

    return StonePermsSettings(
        database_file=database_file,
        storage_backend=backend,
        storage_server_id=server_id,
        storage_sync_ticks=_bounded_int(storage.get("sync_ticks"), 20, 20, 1200),
        mysql=mysql_settings,
        default_group=normalize_group_name(str(permissions.get("default_group", "default"))),
        server_context=normalize_context_value(str(contexts.get("server", "global"))),
        expiry_check_ticks=_bounded_int(maintenance.get("expiry_check_ticks"), 20, 20, 1200),
        catalog_check_ticks=_bounded_int(maintenance.get("catalog_check_ticks"), 100, 20, 6000),
        include_device_os_context=bool(contexts.get("include_device_os", False)),
        include_locale_context=bool(contexts.get("include_locale", False)),
        debug=bool(raw.get("debug", False)),
        web_enabled=bool(web.get("enabled", False)),
        web_api_url=_bounded_text(web.get("api_url"), PUBLIC_API_URL, 512),
        web_server_id=_bounded_text(web.get("server_id"), "", 64),
        web_server_token=_bounded_text(web.get("server_token"), "", 128),
        web_server_name=_bounded_text(web.get("server_name"), "Endstone server", 80),
        startup=StartupSettings(
            show_summary=bool(startup.get("show_summary", True)),
            check_server_properties=bool(startup.get("check_server_properties", True)),
        ),
        display=DisplaySettings(
            chat_enabled=bool(chat_display.get("enabled", False)),
            chat_format=validate_display_format(
                chat_display.get("format", DEFAULT_CHAT_FORMAT),
                allowed=CHAT_PLACEHOLDERS,
                required={"name", "message"},
                label="display.chat.format",
            ),
            nametag_enabled=bool(nametag_display.get("enabled", False)),
            nametag_format=validate_display_format(
                nametag_display.get("format", DEFAULT_NAMETAG_FORMAT),
                allowed=NAMETAG_PLACEHOLDERS,
                required={"name"},
                label="display.nametag.format",
            ),
        ),
    )


def validate_display_format(
    value: object,
    *,
    allowed: frozenset[str],
    required: set[str],
    label: str,
) -> str:
    result = str(value) if value is not None else ""
    if not result or len(result) > 256 or "\x00" in result or "\n" in result or "\r" in result:
        raise ValueError(f"{label} must contain 1-256 characters on one line")
    try:
        parsed = tuple(Formatter().parse(result))
    except ValueError as exc:
        raise ValueError(f"{label} contains unbalanced braces") from exc
    fields: set[str] = set()
    for _literal, field, format_spec, conversion in parsed:
        if field is None:
            continue
        if field not in allowed:
            raise ValueError(f"{label} contains unsupported placeholder {{{field}}}")
        if format_spec or conversion:
            raise ValueError(f"{label} placeholders do not support conversions or format specs")
        fields.add(field)
    missing = required - fields
    if missing:
        names = ", ".join(f"{{{name}}}" for name in sorted(missing))
        raise ValueError(f"{label} must include {names}")
    return result


def _section(raw: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = raw.get(key, {})
    if not isinstance(value, Mapping):
        raise ValueError(f"Configuration section {key!r} must be a table")
    return value


def _bounded_int(value: object, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value) if value is not None else default
    except (TypeError, ValueError):
        return default
    return min(maximum, max(minimum, parsed))


def _bounded_text(value: object, default: str, maximum: int) -> str:
    result = str(value).strip() if value is not None else default
    if len(result) > maximum or "\x00" in result:
        raise ValueError(f"Configuration text must contain at most {maximum} characters")
    return result
