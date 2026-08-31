from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

from .validation import (
    normalize_context_key,
    normalize_context_value,
    normalize_group_name,
    normalize_meta_key,
    normalize_permission,
    normalize_track_name,
)


class SubjectType(StrEnum):
    USER = "user"
    GROUP = "group"


class NodeType(StrEnum):
    PERMISSION = "permission"
    PARENT = "parent"
    META = "meta"
    PREFIX = "prefix"
    SUFFIX = "suffix"


@dataclass(frozen=True, slots=True, order=True)
class SubjectRef:
    type: SubjectType
    identifier: str

    def __post_init__(self) -> None:
        normalized = str(self.identifier).strip()
        if self.type is SubjectType.GROUP:
            normalized = normalize_group_name(normalized)
        elif not normalized:
            raise ValueError("A user subject id is required")
        object.__setattr__(self, "identifier", normalized)

    @classmethod
    def user(cls, unique_id: str) -> SubjectRef:
        return cls(SubjectType.USER, str(unique_id))

    @classmethod
    def group(cls, name: str) -> SubjectRef:
        return cls(SubjectType.GROUP, name)


@dataclass(frozen=True, slots=True)
class ContextSet:
    pairs: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        normalized = tuple(
            sorted(
                {
                    (normalize_context_key(key), normalize_context_value(value))
                    for key, value in self.pairs
                }
            )
        )
        object.__setattr__(self, "pairs", normalized)

    @classmethod
    def of(cls, pairs: Iterable[tuple[str, str]]) -> ContextSet:
        return cls(tuple(pairs))

    @classmethod
    def parse(cls, value: str | Iterable[str] | None) -> ContextSet:
        if value is None:
            return cls()
        tokens = str(value).split() if isinstance(value, str) else list(value)
        pairs: list[tuple[str, str]] = []
        for token in tokens:
            if "=" not in token:
                raise ValueError(f"Context must use key=value syntax: {token!r}")
            key, item_value = token.split("=", 1)
            pairs.append((key, item_value))
        return cls.of(pairs)

    @classmethod
    def from_json(cls, value: str) -> ContextSet:
        raw = json.loads(value)
        if not isinstance(raw, list):
            raise ValueError("Stored contexts must be a list")
        return cls.of((str(item[0]), str(item[1])) for item in raw)

    def to_json(self) -> str:
        return json.dumps(self.pairs, ensure_ascii=True, separators=(",", ":"))

    def grouped(self) -> Mapping[str, frozenset[str]]:
        values: dict[str, set[str]] = {}
        for key, value in self.pairs:
            values.setdefault(key, set()).add(value)
        return MappingProxyType({key: frozenset(items) for key, items in values.items()})

    def matches(self, active: ContextSet) -> bool:
        required = self.grouped()
        current = active.grouped()
        return all(key in current and bool(values & current[key]) for key, values in required.items())

    @property
    def specificity(self) -> int:
        return len(self.grouped())


@dataclass(frozen=True, slots=True)
class Node:
    subject: SubjectRef
    type: NodeType
    key: str
    value: str
    contexts: ContextSet = field(default_factory=ContextSet)
    expires_at: int | None = None
    priority: int = 0
    created_at: int = 0
    id: int | None = None

    def __post_init__(self) -> None:
        key = str(self.key).strip()
        value = str(self.value)
        if self.type is NodeType.PERMISSION:
            key = normalize_permission(key)
            value = value.strip().casefold()
            if value not in {"true", "false"}:
                raise ValueError("Permission node values must be true or false")
        elif self.type is NodeType.PARENT:
            key = normalize_group_name(key)
            value = "true"
        elif self.type is NodeType.META:
            key = normalize_meta_key(key)
        elif self.type in {NodeType.PREFIX, NodeType.SUFFIX}:
            if not value.strip():
                raise ValueError(f"{self.type.value} values may not be empty")
            key = self.type.value
        if self.expires_at is not None and int(self.expires_at) <= 0:
            raise ValueError("Expiry timestamps must be positive")
        object.__setattr__(self, "key", key)
        object.__setattr__(self, "value", value)
        if self.expires_at is not None:
            object.__setattr__(self, "expires_at", int(self.expires_at))
        object.__setattr__(self, "priority", int(self.priority))

    @property
    def permission_value(self) -> bool:
        if self.type is not NodeType.PERMISSION:
            raise TypeError("Only permission nodes have a boolean value")
        return self.value == "true"

    @property
    def temporary(self) -> bool:
        return self.expires_at is not None

    def active_at(self, timestamp: int) -> bool:
        return self.expires_at is None or self.expires_at > timestamp


@dataclass(frozen=True, slots=True)
class UserRecord:
    unique_id: str
    last_name: str
    xuid: str | None = None


@dataclass(frozen=True, slots=True)
class PlayerProfile:
    unique_id: str
    last_name: str
    xuid: str | None = None
    locale: str | None = None
    device_os: str | None = None
    game_version: str | None = None
    game_mode: str | None = None
    ping_ms: int | None = None
    total_exp: int | None = None
    exp_level: int | None = None
    skin_id: str | None = None
    skin_hash: str | None = None
    skin_width: int | None = None
    skin_height: int | None = None
    skin_rgba: bytes | None = None
    cape_id: str | None = None
    first_seen_at: int = 0
    last_seen_at: int = 0
    last_joined_at: int | None = None
    last_quit_at: int | None = None
    skin_updated_at: int | None = None
    online: bool = False

    @property
    def user(self) -> UserRecord:
        return UserRecord(self.unique_id, self.last_name, self.xuid)


@dataclass(frozen=True, slots=True)
class GroupRecord:
    name: str
    display_name: str
    weight: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", normalize_group_name(self.name))
        if not str(self.display_name).strip():
            object.__setattr__(self, "display_name", self.name)
        object.__setattr__(self, "weight", int(self.weight))


@dataclass(frozen=True, slots=True)
class TrackRecord:
    name: str
    groups: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        name = normalize_track_name(self.name)
        groups = tuple(normalize_group_name(group) for group in self.groups)
        if len(groups) != len(set(groups)):
            raise ValueError("A group may only appear once in a track")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "groups", groups)


class TrackMoveAction(StrEnum):
    PROMOTE = "promote"
    DEMOTE = "demote"


class TrackMoveStatus(StrEnum):
    SUCCESS = "success"
    ADDED_TO_FIRST_GROUP = "added_to_first_group"
    REMOVED_FROM_FIRST_GROUP = "removed_from_first_group"
    NOT_ON_TRACK = "not_on_track"
    END_OF_TRACK = "end_of_track"
    FIRST_GROUP_PROTECTED = "first_group_protected"
    AMBIGUOUS_CALL = "ambiguous_call"


@dataclass(frozen=True, slots=True)
class TrackMoveResult:
    action: TrackMoveAction
    status: TrackMoveStatus
    track: str
    group_from: str | None = None
    group_to: str | None = None
    changed: bool = False

    @property
    def successful(self) -> bool:
        return self.changed


@dataclass(frozen=True, slots=True)
class PermissionSnapshot:
    user: SubjectRef
    groups: Mapping[str, GroupRecord]
    nodes: Mapping[SubjectRef, tuple[Node, ...]]
    default_group: str = "default"


@dataclass(frozen=True, slots=True)
class PermissionCandidate:
    node: Node
    origin: SubjectRef
    direct: bool
    inheritance_distance: int
    group_weight: int
    match_specificity: int


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    permission: str
    value: bool | None
    selected: PermissionCandidate | None
    candidates: tuple[PermissionCandidate, ...] = ()

    @property
    def defined(self) -> bool:
        return self.value is not None


@dataclass(frozen=True, slots=True)
class MetaCandidate:
    node: Node
    origin: SubjectRef
    direct: bool
    inheritance_distance: int
    group_weight: int


@dataclass(frozen=True, slots=True)
class MetaDecision:
    type: NodeType
    key: str
    value: str | None
    selected: MetaCandidate | None
    candidates: tuple[MetaCandidate, ...] = ()

    @property
    def defined(self) -> bool:
        return self.value is not None
