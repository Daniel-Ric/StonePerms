from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ..domain.model import (
    ContextSet,
    GroupRecord,
    Node,
    NodeType,
    PermissionSnapshot,
    PlayerProfile,
    SubjectRef,
    TrackRecord,
    UserRecord,
)


@dataclass(frozen=True, slots=True)
class ExpiredNodes:
    count: int
    subjects: frozenset[SubjectRef]


@dataclass(frozen=True, slots=True)
class EditorSubjectChange:
    subject: SubjectRef
    before: tuple[Node, ...]
    after: tuple[Node, ...]


@dataclass(frozen=True, slots=True)
class EditorTrackChange:
    name: str
    before: tuple[str, ...]
    after: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EditorStorageResult:
    revision: int
    changed_subjects: int = 0
    changed_tracks: int = 0
    nodes_added: int = 0
    nodes_removed: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.changed_subjects or self.changed_tracks)


class RevisionConflictError(RuntimeError):
    pass


class PermissionRepository(Protocol):
    @property
    def revision(self) -> int: ...

    def initialize(self, default_group: str) -> None: ...

    def close(self) -> None: ...

    def upsert_user(self, user: UserRecord) -> None: ...

    def find_user(self, identifier: str) -> UserRecord | None: ...

    def list_users(self) -> tuple[UserRecord, ...]: ...

    def upsert_player_profile(self, profile: PlayerProfile) -> PlayerProfile: ...

    def get_player_profile(self, identifier: str) -> PlayerProfile | None: ...

    def list_player_profiles(self) -> tuple[PlayerProfile, ...]: ...

    def create_group(self, group: GroupRecord, actor: str) -> bool: ...

    def get_group(self, name: str) -> GroupRecord | None: ...

    def list_groups(self) -> tuple[GroupRecord, ...]: ...

    def set_group_weight(self, name: str, weight: int, actor: str) -> None: ...

    def create_track(self, track: TrackRecord, actor: str, action: str = "track.create") -> bool: ...

    def get_track(self, name: str) -> TrackRecord | None: ...

    def list_tracks(self) -> tuple[TrackRecord, ...]: ...

    def set_track_groups(
        self,
        name: str,
        groups: tuple[str, ...],
        actor: str,
        action: str,
        details: dict[str, Any],
    ) -> TrackRecord: ...

    def rename_track(self, name: str, new_name: str, actor: str) -> bool: ...

    def delete_track(self, name: str, actor: str) -> bool: ...

    def save_node(self, node: Node, actor: str, action: str) -> Node: ...

    def remove_nodes(
        self,
        subject: SubjectRef,
        node_type: NodeType,
        key: str,
        contexts: ContextSet,
        actor: str,
        action: str,
        *,
        temporary: bool | None = None,
        priority: int | None = None,
    ) -> int: ...

    def replace_parent_node(
        self,
        old_node: Node | None,
        new_node: Node | None,
        actor: str,
        action: str,
        details: dict[str, Any],
    ) -> Node | None: ...

    def apply_editor_batch(
        self,
        expected_revision: int,
        subject_changes: tuple[EditorSubjectChange, ...],
        track_changes: tuple[EditorTrackChange, ...],
        actor: str,
        session_id: str,
    ) -> EditorStorageResult: ...

    def nodes_for(self, subject: SubjectRef, *, include_expired: bool = True) -> tuple[Node, ...]: ...

    def load_snapshot(self, user: SubjectRef, default_group: str) -> PermissionSnapshot: ...

    def delete_expired(self, timestamp: int) -> ExpiredNodes: ...

    def recent_audit(self, limit: int = 20) -> tuple[dict[str, object], ...]: ...

    def record_audit(self, actor: str, action: str, details: dict[str, Any]) -> None: ...
