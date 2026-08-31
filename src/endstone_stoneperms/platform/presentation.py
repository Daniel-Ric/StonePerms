from __future__ import annotations

from typing import Protocol

PREFIX_ACCENT = "§e"
TEXT = "§7"
SYMBOL = "§8"
ERROR = "§c"
SUCCESS = "§a"

PREFIX = f"{PREFIX_ACCENT}StonePerms {SYMBOL}§l»§r"
DETAIL_PREFIX = f"{SYMBOL}  >"


class MessageTarget(Protocol):
    def send_message(self, message: str) -> None: ...

    def send_error_message(self, message: str) -> None: ...


def send_error(target: MessageTarget, message: str, hint: str) -> None:
    target.send_error_message(f"{PREFIX} {ERROR}{message}")
    target.send_message(f"{DETAIL_PREFIX} {TEXT}§o{hint}")
