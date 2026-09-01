from __future__ import annotations

from collections.abc import Callable
from typing import Any

from endstone import Player
from endstone.plugin import Plugin

from ..application.manager import StonePermsManager
from ..domain.validation import normalize_permission
from .contexts import EndstoneContextCalculator
from .identity import player_subject, player_unique_id
from .profiles import capture_player_profile


class AttachmentManager:
    def __init__(
        self,
        plugin: Plugin,
        manager: StonePermsManager,
        contexts: EndstoneContextCalculator,
        on_player_applied: Callable[[Player], object] | None = None,
    ) -> None:
        self._plugin = plugin
        self._manager = manager
        self._contexts = contexts
        self._on_player_applied = on_player_applied
        self._attachments: dict[str, Any] = {}
        self._applied: dict[str, dict[str, bool]] = {}
        self._registered_permissions: frozenset[str] = frozenset()

    def register_player(self, player: Player, *, joined: bool = False) -> None:
        self._manager.observe_player(capture_player_profile(player, joined=joined))

    def update_player_profile(self, player: Player, *, skin: Any | None = None) -> None:
        self._manager.observe_player(capture_player_profile(player, skin=skin))

    def record_player_quit(self, player: Player) -> None:
        self._manager.observe_player(capture_player_profile(player, online=False, quit=True))

    @property
    def permission_catalog(self) -> frozenset[str]:
        return self._registered_permissions

    def apply_player(self, player: Player) -> bool:
        self.register_player(player)
        identity = player_unique_id(player)
        subject = player_subject(player)
        permission_names = set(self._registered_permissions)
        permission_names.update(self._manager.resolvable_permission_keys(subject))
        desired = self._manager.resolve_permissions(
            subject,
            permission_names,
            self._contexts.calculate(player),
        )
        previous = self._applied.get(identity, {})
        if desired == previous:
            self._notify_player_applied(player)
            return False

        attachment = self._attachments.get(identity)
        if attachment is None or getattr(attachment, "permissible", player) is None:
            attachment = player.add_attachment(self._plugin)
            self._attachments[identity] = attachment

        for permission in set(previous) - set(desired):
            attachment.unset_permission(permission)
        for permission, value in desired.items():
            if previous.get(permission) != value:
                attachment.set_permission(permission, value)

        player.recalculate_permissions()
        player.update_commands()
        self._applied[identity] = desired
        self._notify_player_applied(player)
        return True

    def apply_by_unique_id(self, unique_id: str) -> bool:
        player = next(
            (
                candidate
                for candidate in self._plugin.server.online_players
                if player_unique_id(candidate) == str(unique_id)
            ),
            None,
        )
        return self.apply_player(player) if player is not None else False

    def refresh_all(self) -> int:
        changed = 0
        for player in tuple(self._plugin.server.online_players):
            changed += int(self.apply_player(player))
        return changed

    def refresh_permission_catalog(self) -> bool:
        catalog_values: set[str] = set()
        for permission in self._plugin.server.plugin_manager.permissions:
            try:
                catalog_values.add(normalize_permission(permission.name))
            except (AttributeError, TypeError, ValueError):
                continue
        catalog = frozenset(catalog_values)
        if catalog == self._registered_permissions:
            return False
        self._registered_permissions = catalog
        self.refresh_all()
        return True

    def remove_player(self, player: Player) -> None:
        identity = player_unique_id(player)
        attachment = self._attachments.pop(identity, None)
        self._applied.pop(identity, None)
        if attachment is not None:
            self._remove_attachment(identity, attachment)

    def close(self) -> None:
        for identity, attachment in tuple(self._attachments.items()):
            self._remove_attachment(identity, attachment)
        self._attachments.clear()
        self._applied.clear()
        self._registered_permissions = frozenset()

    def _remove_attachment(self, identity: str, attachment: Any) -> None:
        try:
            removed = attachment.remove()
        except (AttributeError, RuntimeError) as exc:
            self._plugin.logger.warning(
                f"Could not remove the permission attachment for player {identity}: {exc}"
            )
            return
        if removed is False:
            self._plugin.logger.warning(
                f"Could not remove the permission attachment for player {identity}"
            )

    def _notify_player_applied(self, player: Player) -> None:
        if self._on_player_applied is not None:
            self._on_player_applied(player)
