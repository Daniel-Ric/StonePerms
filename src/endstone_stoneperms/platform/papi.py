from __future__ import annotations

import importlib
from typing import Any

from endstone.plugin import Plugin

from .service import StonePermsService


class StonePermsPlaceholderResolver:
    def __init__(self, service: StonePermsService) -> None:
        self._service = service

    def resolve(self, player: object | None, params: str) -> str | None:
        if player is None:
            return None
        raw = str(params).strip()
        normalized = raw.casefold()
        try:
            if normalized == "prefix":
                return self._service.get_prefix(player) or ""
            if normalized == "suffix":
                return self._service.get_suffix(player) or ""
            if normalized in {"primary-group", "primary_group", "primarygroup"}:
                return self._service.get_primary_group(player)
            if normalized == "groups":
                return ",".join(self._service.get_groups(player))
            track_value = self._resolve_track(player, raw)
            if track_value is not None:
                return track_value
            meta_key = self._meta_key(raw)
            if meta_key is not None:
                return self._service.get_meta(player, meta_key) or ""
        except (LookupError, TypeError, ValueError):
            return None
        return None

    def _resolve_track(self, player: object, params: str) -> str | None:
        normalized = params.casefold()
        markers = {
            "track.current.": "current",
            "current_group_on_track.": "current",
            "track.next.": "next",
            "next_group_on_track.": "next",
            "track.previous.": "previous",
            "previous_group_on_track.": "previous",
            "track.has.": "has",
            "has_groups_on_track.": "has",
        }
        match = next(
            ((marker, action) for marker, action in markers.items() if normalized.startswith(marker)),
            None,
        )
        if match is None:
            return None
        marker, action = match
        track_name = params[len(marker) :]
        if not track_name:
            return ""
        track = self._service.get_track(track_name)
        positions = self._service.get_user_tracks(player).get(track.name, ())
        if action == "has":
            return str(bool(positions)).lower()
        if len(positions) != 1:
            return ""
        index = track.groups.index(positions[0])
        if action == "current":
            return positions[0]
        if action == "next":
            return track.groups[index + 1] if index + 1 < len(track.groups) else ""
        return track.groups[index - 1] if index > 0 else ""

    @staticmethod
    def _meta_key(params: str) -> str | None:
        normalized = params.casefold()
        for marker in ("meta.", "meta:", "meta_"):
            if normalized.startswith(marker) and len(params) > len(marker):
                return params[len(marker) :]
        return None


class StonePermsPapiBridge:
    IDENTIFIER = "stoneperms"

    def __init__(self, plugin: Plugin, service: StonePermsService) -> None:
        self._plugin = plugin
        self._resolver = StonePermsPlaceholderResolver(service)
        self._api: Any | None = None
        self._mode: str | None = None

    @property
    def registered(self) -> bool:
        if self._api is None or self._mode is None:
            return False
        if self._mode == "modern":
            return bool(getattr(self._api, "active", False))
        return True

    def register(self) -> bool:
        if self.registered:
            return True
        plugin_manager = self._plugin.server.plugin_manager
        if plugin_manager.get_plugin("papi") is None:
            return False
        try:
            module = importlib.import_module("endstone_papi")
        except ImportError as exc:
            self._plugin.logger.warning(f"PAPI is installed but its Python API could not load: {exc}")
            return False

        api_class = getattr(module, "PlaceholderAPI", None)
        expansion_class = getattr(module, "PlaceholderExpansion", None)
        if api_class is not None and expansion_class is not None and hasattr(api_class, "load"):
            api = api_class.load(self._plugin.server.service_manager)
            if api is None or not getattr(api, "active", False):
                self._plugin.logger.warning("PAPI service is unavailable or inactive")
                return False
            expansion = self._modern_expansion(expansion_class)
            if not api.register_expansion(self._plugin, expansion):
                self._plugin.logger.warning("Could not register the 'stoneperms' PAPI expansion")
                return False
            self._api = api
            self._mode = "modern"
            self._plugin.logger.info("Registered modern PAPI expansion 'stoneperms'")
            return True

        api = self._plugin.server.service_manager.load("PlaceholderAPI")
        if api is None or not hasattr(api, "register_placeholder"):
            self._plugin.logger.warning("Legacy PAPI service is unavailable")
            return False
        if not api.register_placeholder(self._plugin, self.IDENTIFIER, self._legacy_request):
            self._plugin.logger.warning("Could not register the legacy 'stoneperms' PAPI placeholder")
            return False
        self._api = api
        self._mode = "legacy"
        self._plugin.logger.info("Registered legacy PAPI placeholder 'stoneperms'")
        return True

    def close(self) -> None:
        api = self._api
        mode = self._mode
        self._api = None
        self._mode = None
        if api is None or mode != "modern" or not getattr(api, "active", False):
            return
        try:
            api.unregister_expansions(self._plugin)
        except (AttributeError, RuntimeError):
            pass

    def _modern_expansion(self, expansion_class: type[Any]) -> Any:
        resolver = self._resolver
        plugin_version = str(self._plugin.version)

        class StonePermsExpansion(expansion_class):
            identifier = "stoneperms"
            author = "StonePerms contributors"
            version = plugin_version

            def on_request(self, player: object | None, params: str) -> str | None:
                return resolver.resolve(player, params)

        return StonePermsExpansion()

    def _legacy_request(self, player: object | None, params: str) -> str:
        return self._resolver.resolve(player, params) or ""
