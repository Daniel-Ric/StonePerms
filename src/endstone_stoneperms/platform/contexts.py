from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from typing import Any

from endstone import Player

from ..domain.model import ContextSet
from ..domain.validation import normalize_context_key, normalize_context_value
from ..settings import StonePermsSettings

ContextProvider = Callable[[Player], str | Iterable[str] | None]


class EndstoneContextCalculator:
    def __init__(self, settings: StonePermsSettings) -> None:
        self._settings = settings
        self._providers: dict[tuple[str, str], ContextProvider] = {}
        self._lock = threading.RLock()

    def calculate(self, player: Player) -> ContextSet:
        pairs: list[tuple[str, str]] = [("server", self._settings.server_context)]
        pairs.extend(
            [
                ("world", _safe_context_value(getattr(getattr(player, "level", None), "name", "world"))),
                (
                    "dimension",
                    _safe_context_value(getattr(getattr(player, "dimension", None), "name", "unknown")),
                ),
                ("gamemode", _enum_context_value(getattr(player, "game_mode", "unknown"))),
            ]
        )
        if self._settings.include_device_os_context:
            pairs.append(("device_os", _safe_context_value(getattr(player, "device_os", "unknown"))))
        if self._settings.include_locale_context:
            pairs.append(("locale", _safe_context_value(getattr(player, "locale", "unknown"))))

        with self._lock:
            providers = tuple(self._providers.items())
        for (_, key), provider in providers:
            values = provider(player)
            if values is None:
                continue
            if isinstance(values, str):
                values = (values,)
            for value in values:
                pairs.append((key, normalize_context_value(value)))
        return ContextSet.of(pairs)

    def update_settings(self, settings: StonePermsSettings) -> None:
        with self._lock:
            self._settings = settings

    def register_provider(self, owner: str, key: str, provider: ContextProvider) -> None:
        owner_name = str(owner).strip().casefold()
        if not owner_name:
            raise ValueError("A context provider owner is required")
        if not callable(provider):
            raise TypeError("A context provider must be callable")
        normalized_key = normalize_context_key(key)
        with self._lock:
            self._providers[(owner_name, normalized_key)] = provider

    def unregister_owner(self, owner: str) -> None:
        owner_name = str(owner).strip().casefold()
        with self._lock:
            self._providers = {
                identity: provider
                for identity, provider in self._providers.items()
                if identity[0] != owner_name
            }


def _enum_context_value(value: Any) -> str:
    name = getattr(value, "name", None)
    return _safe_context_value(name if name is not None else str(value))


def _safe_context_value(value: Any) -> str:
    text = str(value).strip().casefold().replace(" ", "_")
    try:
        return normalize_context_value(text)
    except ValueError:
        return "unknown"
