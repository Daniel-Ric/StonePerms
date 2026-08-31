from __future__ import annotations

import re


class DurationParseError(ValueError):
    pass


_PART_PATTERN = re.compile(r"(?P<amount>[1-9][0-9]*)(?P<unit>mo|[smhdw])", re.IGNORECASE)
_SECONDS_PER_UNIT = {
    "s": 1,
    "m": 60,
    "h": 60 * 60,
    "d": 24 * 60 * 60,
    "w": 7 * 24 * 60 * 60,
    "mo": 30 * 24 * 60 * 60,
}
MAX_DURATION_SECONDS = 10 * 365 * 24 * 60 * 60


def parse_duration(value: str) -> int:
    text = str(value).strip().casefold()
    if not text:
        raise DurationParseError("A duration is required")

    position = 0
    seconds = 0
    for match in _PART_PATTERN.finditer(text):
        if match.start() != position:
            raise DurationParseError(f"Invalid duration near {text[position:]!r}")
        position = match.end()
        unit = match.group("unit").casefold()
        seconds += int(match.group("amount")) * _SECONDS_PER_UNIT[unit]
        if seconds > MAX_DURATION_SECONDS:
            raise DurationParseError("Duration may not exceed 10 years")

    if position != len(text) or seconds <= 0:
        raise DurationParseError(f"Invalid duration: {value!r}")
    return seconds
