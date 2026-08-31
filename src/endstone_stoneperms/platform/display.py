from __future__ import annotations

from string import Formatter
from typing import Any

from endstone import Player
from endstone.plugin import Plugin

from ..application.manager import StonePermsManager
from ..settings import (
    CHAT_PLACEHOLDERS,
    NAMETAG_PLACEHOLDERS,
    DisplaySettings,
    validate_display_format,
)
from .contexts import EndstoneContextCalculator
from .identity import player_subject, player_unique_id


class StonePermsDisplay:
    def __init__(
        self,
        plugin: Plugin,
        manager: StonePermsManager,
        contexts: EndstoneContextCalculator,
        settings: DisplaySettings,
    ) -> None:
        self._plugin = plugin
        self._manager = manager
        self._contexts = contexts
        self._settings = settings
        self._original_name_tags: dict[str, str] = {}
        self._applied_name_tags: dict[str, str] = {}

    @property
    def settings(self) -> DisplaySettings:
        return self._settings

    def get_web_settings(self) -> dict[str, object]:
        return {
            "chat": {
                "enabled": self._settings.chat_enabled,
                "format": self._settings.chat_format,
                "placeholders": ["prefix", "name", "suffix", "message"],
            },
            "nametag": {
                "enabled": self._settings.nametag_enabled,
                "format": self._settings.nametag_format,
                "placeholders": ["prefix", "name", "suffix"],
            },
        }

    def update_settings(
        self,
        *,
        chat_enabled: bool,
        chat_format: str,
        nametag_enabled: bool,
        nametag_format: str,
    ) -> dict[str, object]:
        updated = DisplaySettings(
            chat_enabled=chat_enabled,
            chat_format=validate_display_format(
                chat_format,
                allowed=CHAT_PLACEHOLDERS,
                required={"name", "message"},
                label="chatFormat",
            ),
            nametag_enabled=nametag_enabled,
            nametag_format=validate_display_format(
                nametag_format,
                allowed=NAMETAG_PLACEHOLDERS,
                required={"name"},
                label="nametagFormat",
            ),
        )
        previous = self._settings
        self._settings = updated
        display_config = {
            "chat": {"enabled": updated.chat_enabled, "format": updated.chat_format},
            "nametag": {"enabled": updated.nametag_enabled, "format": updated.nametag_format},
        }
        self._plugin.config["display"] = display_config
        self._plugin.save_config()

        if previous.nametag_enabled and not updated.nametag_enabled:
            self.restore_all_name_tags()
        elif updated.nametag_enabled:
            self.refresh_all_name_tags()
        return self.get_web_settings()

    def apply_chat_format(self, event: Any) -> None:
        if not self._settings.chat_enabled:
            return
        values = self._player_values(event.player)
        event.format = _render_template(
            self._settings.chat_format,
            values,
            message_marker="{1}",
            for_endstone_format=True,
        )

    def apply_name_tag(self, player: Player) -> bool:
        if not self._settings.nametag_enabled:
            return self.restore_name_tag(player)
        identity = player_unique_id(player)
        if identity not in self._original_name_tags:
            self._original_name_tags[identity] = str(getattr(player, "name_tag", player.name))
        rendered = _render_template(
            self._settings.nametag_format,
            self._player_values(player),
        )
        if str(getattr(player, "name_tag", "")) == rendered:
            self._applied_name_tags[identity] = rendered
            return False
        player.name_tag = rendered
        self._applied_name_tags[identity] = rendered
        return True

    def restore_name_tag(self, player: Player) -> bool:
        identity = player_unique_id(player)
        original = self._original_name_tags.pop(identity, None)
        applied = self._applied_name_tags.pop(identity, None)
        if original is None or applied is None or str(getattr(player, "name_tag", "")) != applied:
            return False
        player.name_tag = original
        return True

    def forget_player(self, player: Player) -> None:
        self.restore_name_tag(player)

    def refresh_all_name_tags(self) -> int:
        return sum(self.apply_name_tag(player) for player in tuple(self._plugin.server.online_players))

    def restore_all_name_tags(self) -> int:
        return sum(self.restore_name_tag(player) for player in tuple(self._plugin.server.online_players))

    def close(self) -> None:
        self.restore_all_name_tags()
        self._original_name_tags.clear()
        self._applied_name_tags.clear()

    def _player_values(self, player: Player) -> dict[str, str]:
        subject = player_subject(player)
        contexts = self._contexts.calculate(player)
        return {
            "prefix": self._manager.resolve_prefix(subject, contexts).value or "",
            "name": str(player.name),
            "suffix": self._manager.resolve_suffix(subject, contexts).value or "",
        }


def _render_template(
    template: str,
    values: dict[str, str],
    *,
    message_marker: str = "",
    for_endstone_format: bool = False,
) -> str:
    result: list[str] = []
    for literal, field, _format_spec, _conversion in Formatter().parse(template):
        result.append(_escape_braces(literal) if for_endstone_format else literal)
        if field is None:
            continue
        if field == "message":
            result.append(message_marker)
        else:
            value = values.get(field, "")
            result.append(_escape_braces(value) if for_endstone_format else value)
    return "".join(result)


def _escape_braces(value: str) -> str:
    return value.replace("{", "{{").replace("}", "}}")
