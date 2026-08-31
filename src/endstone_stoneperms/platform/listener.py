from collections.abc import Callable

from endstone.event import (
    EventPriority,
    PlayerChatEvent,
    PlayerDimensionChangeEvent,
    PlayerGameModeChangeEvent,
    PlayerJoinEvent,
    PlayerQuitEvent,
    PlayerSkinChangeEvent,
    PluginEnableEvent,
    event_handler,
)
from endstone.plugin import Plugin

from .attachments import AttachmentManager
from .display import StonePermsDisplay
from .identity import player_unique_id


class StonePermsListener:
    def __init__(
        self,
        plugin: Plugin,
        attachments: AttachmentManager,
        display: StonePermsDisplay,
        on_plugin_enabled: Callable[[], None] | None = None,
    ) -> None:
        self._plugin = plugin
        self._attachments = attachments
        self._display = display
        self._on_plugin_enabled = on_plugin_enabled

    @event_handler(priority=EventPriority.MONITOR)
    def on_player_join(self, event: PlayerJoinEvent) -> None:
        unique_id = player_unique_id(event.player)
        self._attachments.register_player(event.player, joined=True)
        self._plugin.server.scheduler.run_task(
            self._plugin,
            lambda: self._attachments.apply_by_unique_id(unique_id),
            delay=1,
        )

    @event_handler(priority=EventPriority.MONITOR)
    def on_player_quit(self, event: PlayerQuitEvent) -> None:
        self._attachments.record_player_quit(event.player)
        self._display.forget_player(event.player)
        self._attachments.remove_player(event.player)

    @event_handler(priority=EventPriority.HIGHEST, ignore_cancelled=True)
    def on_player_chat(self, event: PlayerChatEvent) -> None:
        self._display.apply_chat_format(event)

    @event_handler(priority=EventPriority.MONITOR, ignore_cancelled=True)
    def on_player_skin_change(self, event: PlayerSkinChangeEvent) -> None:
        self._attachments.update_player_profile(event.player, skin=event.new_skin)

    @event_handler(priority=EventPriority.MONITOR)
    def on_dimension_change(self, event: PlayerDimensionChangeEvent) -> None:
        unique_id = player_unique_id(event.player)
        self._plugin.server.scheduler.run_task(
            self._plugin,
            lambda: self._attachments.apply_by_unique_id(unique_id),
            delay=1,
        )

    @event_handler(priority=EventPriority.MONITOR, ignore_cancelled=True)
    def on_game_mode_change(self, event: PlayerGameModeChangeEvent) -> None:
        unique_id = player_unique_id(event.player)
        self._plugin.server.scheduler.run_task(
            self._plugin,
            lambda: self._attachments.apply_by_unique_id(unique_id),
            delay=1,
        )

    @event_handler(priority=EventPriority.MONITOR)
    def on_plugin_enable(self, event: PluginEnableEvent) -> None:
        if event.plugin is self._plugin:
            return
        self._plugin.server.scheduler.run_task(
            self._plugin,
            self._after_plugin_enable,
            delay=1,
        )

    def _after_plugin_enable(self) -> None:
        self._attachments.refresh_permission_catalog()
        if self._on_plugin_enabled is not None:
            self._on_plugin_enabled()
