from __future__ import annotations

import re

GROUP_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
TRACK_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
PERMISSION_SEGMENT_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
CONTEXT_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
CONTEXT_VALUE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.:/-]{0,127}$")
META_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")


def normalize_group_name(value: str) -> str:
    name = str(value).strip().casefold()
    if not GROUP_PATTERN.fullmatch(name):
        raise ValueError(
            "Group names must contain 1-64 lowercase letters, numbers, underscores, or dashes"
        )
    return name


def normalize_track_name(value: str) -> str:
    name = str(value).strip().casefold()
    if not TRACK_PATTERN.fullmatch(name):
        raise ValueError(
            "Track names must contain 1-64 lowercase letters, numbers, underscores, or dashes"
        )
    return name


def normalize_permission(value: str) -> str:
    permission = str(value).strip().casefold()
    if permission == "*":
        return permission
    segments = permission.split(".")
    if len(segments) < 2 or any(not segment for segment in segments):
        raise ValueError("Permission nodes must contain at least one namespace separator")
    wildcard_indexes = [index for index, segment in enumerate(segments) if segment == "*"]
    if wildcard_indexes and wildcard_indexes != [len(segments) - 1]:
        raise ValueError("A wildcard is only allowed as the final permission segment")
    for segment in segments:
        if segment != "*" and not PERMISSION_SEGMENT_PATTERN.fullmatch(segment):
            raise ValueError(f"Invalid permission segment: {segment!r}")
    return permission


def normalize_context_key(value: str) -> str:
    key = str(value).strip().casefold()
    if not CONTEXT_KEY_PATTERN.fullmatch(key):
        raise ValueError(f"Invalid context key: {value!r}")
    return key


def normalize_context_value(value: str) -> str:
    normalized = str(value).strip().casefold()
    if not CONTEXT_VALUE_PATTERN.fullmatch(normalized):
        raise ValueError(f"Invalid context value: {value!r}")
    return normalized


def normalize_meta_key(value: str) -> str:
    key = str(value).strip().casefold()
    if not META_KEY_PATTERN.fullmatch(key):
        raise ValueError(f"Invalid metadata key: {value!r}")
    return key
