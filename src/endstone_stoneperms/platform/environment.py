from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from endstone.plugin import Plugin

from ..settings import StonePermsSettings
from ..web_defaults import PUBLIC_DASHBOARD_URL


@dataclass(frozen=True, slots=True)
class ServerConfigurationNotice:
    title: str
    detail: str
    change: str
    required: bool = True


@dataclass(frozen=True, slots=True)
class ServerConfigurationReport:
    server_root: Path
    properties_path: Path
    notices: tuple[ServerConfigurationNotice, ...]


def inspect_server_configuration(
    plugin: Plugin,
    settings: StonePermsSettings,
) -> ServerConfigurationReport:
    server_root = _server_root(plugin)
    properties_path = server_root / "server.properties"
    properties = _read_properties(properties_path)
    notices: list[ServerConfigurationNotice] = []

    if not settings.startup.check_server_properties:
        return ServerConfigurationReport(
            server_root=server_root,
            properties_path=properties_path,
            notices=(),
        )

    if not bool(plugin.server.online_mode):
        notices.append(
            ServerConfigurationNotice(
                title="Xbox authentication is disabled",
                detail="Player permissions rely on stable UUID and XUID identities.",
                change="Set online-mode=true in server.properties, then restart the server.",
            )
        )

    permission_level = properties.get("default-player-permission-level", "member").casefold()
    if permission_level == "operator":
        notices.append(
            ServerConfigurationNotice(
                title="New players receive operator access",
                detail="Operators inherit the StonePerms administration permission by default.",
                change=(
                    "Set default-player-permission-level=member in server.properties unless this "
                    "is intentional."
                ),
            )
        )

    chat_restriction = properties.get("chat-restriction", "none").casefold()
    if settings.display.chat_enabled and chat_restriction in {"dropped", "disabled"}:
        detail = (
            "Bedrock drops chat messages before StonePerms can format them."
            if chat_restriction == "dropped"
            else "Non-operators do not receive the chat interface used by StonePerms formatting."
        )
        notices.append(
            ServerConfigurationNotice(
                title="Chat formatting is blocked by server.properties",
                detail=detail,
                change="Set chat-restriction=None in server.properties, then restart the server.",
            )
        )

    if _property_enabled(properties, "disable-custom-skins"):
        notices.append(
            ServerConfigurationNotice(
                title="Custom player skins are disabled",
                detail="Dashboard portraits may fall back to a generic player face.",
                change="Set disable-custom-skins=false to keep custom skin previews.",
                required=False,
            )
        )

    return ServerConfigurationReport(
        server_root=server_root,
        properties_path=properties_path,
        notices=tuple(notices),
    )


def log_startup_report(
    plugin: Plugin,
    settings: StonePermsSettings,
    *,
    repository: Any,
    papi_registered: bool,
    web_status: Any,
) -> None:
    report = inspect_server_configuration(plugin, settings)
    groups = len(tuple(repository.list_groups()))
    tracks = len(tuple(repository.list_tracks()))
    line = "=" * 68
    divider = "-" * 68

    if not settings.startup.show_summary:
        plugin.logger.info(
            f"StonePerms v{plugin.version} ready with SQLite storage and default group "
            f"{settings.default_group!r}"
        )
        _log_notices(plugin, report, divider)
        return

    plugin.logger.info(f"§8{line}")
    plugin.logger.info(f"§eSTONEPERMS§r  §7v{plugin.version}§r  §8|§r  §aPERMISSIONS READY")
    plugin.logger.info(f"§8{divider}")
    _log_row(
        plugin,
        "Runtime",
        f"Endstone {plugin.server.version}  |  Minecraft {plugin.server.minecraft_version}",
    )
    _log_row(
        plugin,
        "Data",
        f"SQLite  |  Default: {settings.default_group}  |  "
        f"{_count(groups, 'group')}  |  {_count(tracks, 'track')}",
    )
    _log_row(
        plugin,
        "Display",
        f"Chat {_state(settings.display.chat_enabled)}  |  "
        f"Nametags {_state(settings.display.nametag_enabled)}",
    )
    _log_row(plugin, "PAPI", _papi_state(plugin, papi_registered))
    _log_row(plugin, "Dashboard", _web_state(web_status))
    _log_notices(plugin, report, divider)
    if not report.notices:
        _log_row(plugin, "Checks", "§aOK§r  No conflicts in server.properties")
    plugin.logger.info(f"§8{divider}")
    _log_row(plugin, "Commands", "/stoneperms help")
    if not bool(web_status.configured):
        _log_row(plugin, "Dashboard", PUBLIC_DASHBOARD_URL)
        _log_row(plugin, "Dashboard", "/stoneperms web login")
    plugin.logger.info(f"§8{line}")


def _log_notices(plugin: Plugin, report: ServerConfigurationReport, divider: str) -> None:
    if not report.notices:
        return
    required = sum(notice.required for notice in report.notices)
    recommended = len(report.notices) - required
    counts: list[str] = []
    if required:
        counts.append(f"{required} required")
    if recommended:
        counts.append(f"{recommended} recommended")
    plugin.logger.warning(divider)
    plugin.logger.warning(f"SERVER CONFIGURATION  |  {', '.join(counts)}")
    for index, notice in enumerate(report.notices, start=1):
        label = "Required" if notice.required else "Recommended"
        plugin.logger.warning(f"{index}. {label}: {notice.title}")
        plugin.logger.warning(f"   {notice.detail}")
        plugin.logger.warning(f"   {notice.change}")
    plugin.logger.warning(f"File: {report.properties_path}")


def _log_row(plugin: Plugin, label: str, value: str) -> None:
    plugin.logger.info(f"§7{label:<11}§r {value}")


def _server_root(plugin: Plugin) -> Path:
    data_folder = Path(plugin.data_folder).resolve()
    plugin_root = data_folder.parent.parent
    if (plugin_root / "server.properties").is_file():
        return plugin_root
    return Path.cwd().resolve()


def _read_properties(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    properties: dict[str, str] = {}
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        properties[key.strip().casefold()] = value.strip()
    return properties


def _property_enabled(properties: dict[str, str], key: str) -> bool:
    return properties.get(key, "false").casefold() == "true"


def _state(enabled: bool) -> str:
    return "enabled" if enabled else "disabled"


def _count(value: int, label: str) -> str:
    suffix = "" if value == 1 else "s"
    return f"{value} {label}{suffix}"


def _papi_state(plugin: Plugin, registered: bool) -> str:
    if registered:
        return "registered"
    if plugin.server.plugin_manager.get_plugin("papi") is None:
        return "not installed"
    return "installed, unavailable"


def _web_state(status: Any) -> str:
    if bool(status.ready):
        return "connected and ready"
    if bool(status.connected):
        return "connecting"
    if bool(status.configured):
        return "paired, currently offline"
    return "not paired"
