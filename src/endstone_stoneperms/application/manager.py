from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable

from ..domain.model import (
    ContextSet,
    GroupRecord,
    MetaDecision,
    Node,
    NodeType,
    PermissionDecision,
    PermissionSnapshot,
    PlayerProfile,
    SubjectRef,
    SubjectType,
    TrackMoveAction,
    TrackMoveResult,
    TrackMoveStatus,
    TrackRecord,
    UserRecord,
)
from ..domain.resolver import PermissionResolver
from ..domain.validation import normalize_group_name, normalize_permission, normalize_track_name
from .ports import (
    EditorStorageResult,
    EditorSubjectChange,
    EditorTrackChange,
    ExpiredNodes,
    PermissionRepository,
    RevisionConflictError,
)


class UnknownSubjectError(LookupError):
    pass


class StonePermsManager:
    def __init__(
        self,
        repository: PermissionRepository,
        *,
        default_group: str = "default",
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._repository = repository
        self._default_group = normalize_group_name(default_group)
        self._clock = clock
        self._resolver = PermissionResolver()
        self._snapshot_cache: dict[str, tuple[int, PermissionSnapshot]] = {}
        self._track_lock = threading.RLock()

    @property
    def default_group(self) -> str:
        return self._default_group

    @property
    def repository(self) -> PermissionRepository:
        return self._repository

    def register_user(self, unique_id: str, name: str, xuid: str | None = None) -> UserRecord:
        user = UserRecord(unique_id=str(unique_id), last_name=str(name), xuid=xuid or None)
        self._repository.upsert_user(user)
        return user

    def find_user(self, identifier: str) -> UserRecord:
        user = self._repository.find_user(identifier)
        if user is None:
            raise UnknownSubjectError(
                f"Unknown user {identifier!r}; the player must join once or be addressed by a known UUID"
            )
        return user

    def list_users(self) -> tuple[UserRecord, ...]:
        return self._repository.list_users()

    def observe_player(self, profile: PlayerProfile) -> PlayerProfile:
        return self._repository.upsert_player_profile(profile)

    def get_player_profile(self, identifier: str) -> PlayerProfile | None:
        return self._repository.get_player_profile(identifier)

    def list_player_profiles(self) -> tuple[PlayerProfile, ...]:
        return self._repository.list_player_profiles()

    def user_subject(self, identifier: str) -> SubjectRef:
        return SubjectRef.user(self.find_user(identifier).unique_id)

    def group_subject(self, name: str) -> SubjectRef:
        normalized = normalize_group_name(name)
        if self._repository.get_group(normalized) is None:
            raise UnknownSubjectError(f"Unknown group {normalized!r}")
        return SubjectRef.group(normalized)

    def create_group(
        self,
        name: str,
        *,
        actor: str,
        weight: int = 0,
        display_name: str | None = None,
    ) -> bool:
        normalized = normalize_group_name(name)
        created = self._repository.create_group(
            GroupRecord(normalized, display_name or normalized, int(weight)), actor
        )
        self._invalidate()
        return created

    def list_groups(self) -> tuple[GroupRecord, ...]:
        return self._repository.list_groups()

    def set_group_weight(self, name: str, weight: int, *, actor: str) -> None:
        normalized = normalize_group_name(name)
        if self._repository.get_group(normalized) is None:
            raise UnknownSubjectError(f"Unknown group {normalized!r}")
        self._repository.set_group_weight(normalized, int(weight), actor)
        self._invalidate()

    def create_track(self, name: str, *, actor: str) -> bool:
        track = TrackRecord(normalize_track_name(name))
        created = self._repository.create_track(track, actor)
        self._invalidate()
        return created

    def get_track(self, name: str) -> TrackRecord:
        normalized = normalize_track_name(name)
        track = self._repository.get_track(normalized)
        if track is None:
            raise UnknownSubjectError(f"Unknown track {normalized!r}")
        return track

    def list_tracks(self) -> tuple[TrackRecord, ...]:
        return self._repository.list_tracks()

    def append_track_group(self, name: str, group: str, *, actor: str) -> TrackRecord:
        with self._track_lock:
            track = self.get_track(name)
            group_name = self._require_group(group)
            if group_name in track.groups:
                raise ValueError(f"Group {group_name!r} is already on track {track.name!r}")
            return self._set_track_groups(
                track,
                (*track.groups, group_name),
                actor,
                "track.group.append",
                {"group": group_name, "position": len(track.groups) + 1},
            )

    def insert_track_group(
        self,
        name: str,
        group: str,
        position: int,
        *,
        actor: str,
    ) -> TrackRecord:
        with self._track_lock:
            track = self.get_track(name)
            group_name = self._require_group(group)
            if group_name in track.groups:
                raise ValueError(f"Group {group_name!r} is already on track {track.name!r}")
            one_based = int(position)
            if one_based < 1 or one_based > len(track.groups) + 1:
                raise ValueError(
                    f"Track position must be between 1 and {len(track.groups) + 1}"
                )
            groups = list(track.groups)
            groups.insert(one_based - 1, group_name)
            return self._set_track_groups(
                track,
                tuple(groups),
                actor,
                "track.group.insert",
                {"group": group_name, "position": one_based},
            )

    def remove_track_group(self, name: str, group: str, *, actor: str) -> TrackRecord:
        with self._track_lock:
            track = self.get_track(name)
            group_name = normalize_group_name(group)
            if group_name not in track.groups:
                raise ValueError(f"Group {group_name!r} is not on track {track.name!r}")
            position = track.groups.index(group_name) + 1
            return self._set_track_groups(
                track,
                tuple(item for item in track.groups if item != group_name),
                actor,
                "track.group.remove",
                {"group": group_name, "position": position},
            )

    def clear_track(self, name: str, *, actor: str) -> TrackRecord:
        with self._track_lock:
            track = self.get_track(name)
            if not track.groups:
                return track
            return self._set_track_groups(
                track,
                (),
                actor,
                "track.clear",
                {"removed_groups": list(track.groups)},
            )

    def rename_track(self, name: str, new_name: str, *, actor: str) -> TrackRecord:
        with self._track_lock:
            track = self.get_track(name)
            target = normalize_track_name(new_name)
            if target == track.name:
                return track
            if not self._repository.rename_track(track.name, target, actor):
                raise ValueError(f"Track {target!r} already exists")
            self._invalidate()
            return self.get_track(target)

    def clone_track(self, name: str, clone_name: str, *, actor: str) -> TrackRecord:
        with self._track_lock:
            source = self.get_track(name)
            clone = TrackRecord(clone_name, source.groups)
            if not self._repository.create_track(clone, actor, "track.clone"):
                raise ValueError(f"Track {clone.name!r} already exists")
            self._invalidate()
            return clone

    def delete_track(self, name: str, *, actor: str) -> bool:
        with self._track_lock:
            track = self.get_track(name)
            deleted = self._repository.delete_track(track.name, actor)
            self._invalidate()
            return deleted

    def promote(
        self,
        user: SubjectRef,
        track_name: str,
        *,
        actor: str,
        contexts: ContextSet | None = None,
        add_to_first: bool = True,
    ) -> TrackMoveResult:
        return self._move_on_track(
            user,
            track_name,
            TrackMoveAction.PROMOTE,
            actor=actor,
            contexts=contexts or ContextSet(),
            cross_boundary=add_to_first,
        )

    def demote(
        self,
        user: SubjectRef,
        track_name: str,
        *,
        actor: str,
        contexts: ContextSet | None = None,
        remove_from_first: bool = True,
    ) -> TrackMoveResult:
        return self._move_on_track(
            user,
            track_name,
            TrackMoveAction.DEMOTE,
            actor=actor,
            contexts=contexts or ContextSet(),
            cross_boundary=remove_from_first,
        )

    def user_tracks(
        self,
        user: SubjectRef,
        contexts: ContextSet | None = None,
    ) -> dict[str, tuple[str, ...]]:
        self._ensure_subject(user)
        if user.type is not SubjectType.USER:
            raise ValueError("Track positions require a user subject")
        nodes = self._active_direct_parents(user, contexts)
        positions: dict[str, tuple[str, ...]] = {}
        for track in self.list_tracks():
            matched = tuple(node.key for node in nodes if node.key in track.groups)
            if matched:
                positions[track.name] = tuple(
                    group for group in track.groups if group in set(matched)
                )
        return positions

    def set_permission(
        self,
        subject: SubjectRef,
        permission: str,
        value: bool,
        *,
        actor: str,
        contexts: ContextSet | None = None,
        expires_at: int | None = None,
    ) -> Node:
        self._ensure_subject(subject)
        node = Node(
            subject=subject,
            type=NodeType.PERMISSION,
            key=normalize_permission(permission),
            value="true" if bool(value) else "false",
            contexts=contexts or ContextSet(),
            expires_at=expires_at,
            created_at=self._now(),
        )
        saved = self._repository.save_node(
            node,
            actor,
            "permission.settemp" if expires_at is not None else "permission.set",
        )
        self._invalidate()
        return saved

    def unset_permission(
        self,
        subject: SubjectRef,
        permission: str,
        *,
        actor: str,
        contexts: ContextSet | None = None,
        temporary: bool | None = False,
    ) -> int:
        self._ensure_subject(subject)
        normalized = normalize_permission(permission)
        removed = self._repository.remove_nodes(
            subject,
            NodeType.PERMISSION,
            normalized,
            contexts or ContextSet(),
            actor,
            "permission.unset",
            temporary=temporary,
        )
        self._invalidate()
        return removed

    def set_meta(
        self,
        subject: SubjectRef,
        key: str,
        value: str,
        *,
        actor: str,
        contexts: ContextSet | None = None,
        expires_at: int | None = None,
    ) -> Node:
        return self._set_string_node(
            subject,
            NodeType.META,
            key,
            value,
            actor=actor,
            contexts=contexts,
            expires_at=expires_at,
        )

    def unset_meta(
        self,
        subject: SubjectRef,
        key: str,
        *,
        actor: str,
        contexts: ContextSet | None = None,
        temporary: bool | None = False,
    ) -> int:
        return self._unset_string_node(
            subject,
            NodeType.META,
            key,
            actor=actor,
            contexts=contexts,
            temporary=temporary,
        )

    def set_prefix(
        self,
        subject: SubjectRef,
        value: str,
        priority: int,
        *,
        actor: str,
        contexts: ContextSet | None = None,
        expires_at: int | None = None,
    ) -> Node:
        return self._set_string_node(
            subject,
            NodeType.PREFIX,
            NodeType.PREFIX.value,
            value,
            priority=priority,
            actor=actor,
            contexts=contexts,
            expires_at=expires_at,
        )

    def unset_prefix(
        self,
        subject: SubjectRef,
        priority: int,
        *,
        actor: str,
        contexts: ContextSet | None = None,
        temporary: bool | None = False,
    ) -> int:
        return self._unset_string_node(
            subject,
            NodeType.PREFIX,
            NodeType.PREFIX.value,
            priority=priority,
            actor=actor,
            contexts=contexts,
            temporary=temporary,
        )

    def set_suffix(
        self,
        subject: SubjectRef,
        value: str,
        priority: int,
        *,
        actor: str,
        contexts: ContextSet | None = None,
        expires_at: int | None = None,
    ) -> Node:
        return self._set_string_node(
            subject,
            NodeType.SUFFIX,
            NodeType.SUFFIX.value,
            value,
            priority=priority,
            actor=actor,
            contexts=contexts,
            expires_at=expires_at,
        )

    def unset_suffix(
        self,
        subject: SubjectRef,
        priority: int,
        *,
        actor: str,
        contexts: ContextSet | None = None,
        temporary: bool | None = False,
    ) -> int:
        return self._unset_string_node(
            subject,
            NodeType.SUFFIX,
            NodeType.SUFFIX.value,
            priority=priority,
            actor=actor,
            contexts=contexts,
            temporary=temporary,
        )

    def add_parent(
        self,
        subject: SubjectRef,
        parent: str,
        *,
        actor: str,
        contexts: ContextSet | None = None,
        expires_at: int | None = None,
    ) -> Node:
        self._ensure_subject(subject)
        parent_name = normalize_group_name(parent)
        if self._repository.get_group(parent_name) is None:
            raise UnknownSubjectError(f"Unknown parent group {parent_name!r}")
        if subject.type is SubjectType.GROUP:
            if subject.identifier == parent_name or self._group_reaches(parent_name, subject.identifier):
                raise ValueError(
                    f"Adding {parent_name!r} as parent of {subject.identifier!r} would create a cycle"
                )
        node = Node(
            subject=subject,
            type=NodeType.PARENT,
            key=parent_name,
            value="true",
            contexts=contexts or ContextSet(),
            expires_at=expires_at,
            created_at=self._now(),
        )
        saved = self._repository.save_node(
            node,
            actor,
            "parent.addtemp" if expires_at is not None else "parent.add",
        )
        self._invalidate()
        return saved

    def remove_parent(
        self,
        subject: SubjectRef,
        parent: str,
        *,
        actor: str,
        contexts: ContextSet | None = None,
        temporary: bool | None = False,
    ) -> int:
        self._ensure_subject(subject)
        parent_name = normalize_group_name(parent)
        removed = self._repository.remove_nodes(
            subject,
            NodeType.PARENT,
            parent_name,
            contexts or ContextSet(),
            actor,
            "parent.remove",
            temporary=temporary,
        )
        self._invalidate()
        return removed

    def check_permission(
        self,
        user: SubjectRef,
        permission: str,
        contexts: ContextSet | None = None,
    ) -> PermissionDecision:
        snapshot = self._snapshot(user)
        return self._resolver.resolve(snapshot, permission, contexts, now=self._now())

    def effective_groups(
        self, user: SubjectRef, contexts: ContextSet | None = None
    ) -> tuple[str, ...]:
        snapshot = self._snapshot(user)
        return self._resolver.effective_groups(snapshot, contexts, now=self._now())

    def primary_group(self, user: SubjectRef, contexts: ContextSet | None = None) -> str:
        snapshot = self._snapshot(user)
        return self._resolver.primary_group(snapshot, contexts, now=self._now())

    def resolve_meta(
        self,
        user: SubjectRef,
        key: str,
        contexts: ContextSet | None = None,
    ) -> MetaDecision:
        return self._resolver.resolve_meta(self._snapshot(user), key, contexts, now=self._now())

    def resolve_prefix(
        self,
        user: SubjectRef,
        contexts: ContextSet | None = None,
    ) -> MetaDecision:
        return self._resolver.resolve_prefix(self._snapshot(user), contexts, now=self._now())

    def resolve_suffix(
        self,
        user: SubjectRef,
        contexts: ContextSet | None = None,
    ) -> MetaDecision:
        return self._resolver.resolve_suffix(self._snapshot(user), contexts, now=self._now())

    def meta_map(
        self,
        user: SubjectRef,
        contexts: ContextSet | None = None,
    ) -> dict[str, str]:
        return self._resolver.resolve_meta_map(self._snapshot(user), contexts, now=self._now())

    def resolvable_permission_keys(self, user: SubjectRef) -> frozenset[str]:
        snapshot = self._snapshot(user)
        return frozenset(
            node.key
            for nodes in snapshot.nodes.values()
            for node in nodes
            if node.type is NodeType.PERMISSION and "*" not in node.key
        )

    def resolve_permissions(
        self,
        user: SubjectRef,
        permissions: Iterable[str],
        contexts: ContextSet | None = None,
    ) -> dict[str, bool]:
        active = contexts or ContextSet()
        values: dict[str, bool] = {}
        for permission in sorted(set(permissions)):
            decision = self.check_permission(user, permission, active)
            if decision.value is not None:
                values[decision.permission] = decision.value
        return values

    def nodes_for(self, subject: SubjectRef) -> tuple[Node, ...]:
        self._ensure_subject(subject)
        return self._repository.nodes_for(subject, include_expired=False)

    def cleanup_expired(self) -> ExpiredNodes:
        result = self._repository.delete_expired(self._now())
        if result.count:
            self._invalidate()
        return result

    def recent_audit(self, limit: int = 20) -> tuple[dict[str, object], ...]:
        return self._repository.recent_audit(limit)

    def record_settings_change(
        self,
        *,
        actor: str,
        fields: Iterable[str],
        restart_required: Iterable[str],
    ) -> None:
        normalized_actor = str(actor).strip()
        if not normalized_actor or len(normalized_actor) > 128:
            raise ValueError("Settings actor must contain 1-128 characters")
        changed = tuple(dict.fromkeys(str(field) for field in fields))
        if not changed:
            return
        self._repository.record_audit(
            normalized_actor,
            "settings.update",
            {
                "fields": list(changed),
                "restart_required": list(dict.fromkeys(str(field) for field in restart_required)),
            },
        )

    def apply_editor_batch(
        self,
        expected_revision: int,
        subject_changes: tuple[EditorSubjectChange, ...],
        track_changes: tuple[EditorTrackChange, ...],
        *,
        actor: str,
        session_id: str,
    ) -> EditorStorageResult:
        with self._track_lock:
            if self._repository.revision != int(expected_revision):
                raise RevisionConflictError(
                    f"Editor base revision {expected_revision} is stale; current revision is "
                    f"{self._repository.revision}"
                )
            normalized_actor = str(actor).strip()
            if not normalized_actor or len(normalized_actor) > 128:
                raise ValueError("Editor actor must contain 1-128 characters")
            if not str(session_id).strip():
                raise ValueError("An editor session id is required")

            seen_subjects: set[SubjectRef] = set()
            for change in subject_changes:
                if change.subject in seen_subjects:
                    raise ValueError(
                        f"Duplicate editor subject {change.subject.type.value}:"
                        f"{change.subject.identifier}"
                    )
                seen_subjects.add(change.subject)
                self._ensure_subject(change.subject)
                self._validate_editor_nodes(change.subject, change.before, allow_expired=True)
                self._validate_editor_nodes(change.subject, change.after, allow_expired=False)

            seen_tracks: set[str] = set()
            normalized_tracks: list[EditorTrackChange] = []
            for change in track_changes:
                track = self.get_track(change.name)
                if track.name in seen_tracks:
                    raise ValueError(f"Duplicate editor track {track.name!r}")
                seen_tracks.add(track.name)
                before = TrackRecord(track.name, change.before).groups
                after = TrackRecord(track.name, change.after).groups
                for group in after:
                    self._require_group(group)
                normalized_tracks.append(EditorTrackChange(track.name, before, after))

            self._validate_editor_group_graph(subject_changes)
            result = self._repository.apply_editor_batch(
                int(expected_revision),
                subject_changes,
                tuple(normalized_tracks),
                normalized_actor,
                str(session_id),
            )
            if result.changed:
                self._invalidate()
            return result

    def _snapshot(self, user: SubjectRef) -> PermissionSnapshot:
        if user.type is not SubjectType.USER:
            raise ValueError("Permission checks require a user subject")
        cached = self._snapshot_cache.get(user.identifier)
        if cached is not None and cached[0] == self._repository.revision:
            return cached[1]
        snapshot = self._repository.load_snapshot(user, self._default_group)
        self._snapshot_cache[user.identifier] = (self._repository.revision, snapshot)
        return snapshot

    def _validate_editor_nodes(
        self,
        subject: SubjectRef,
        nodes: tuple[Node, ...],
        *,
        allow_expired: bool,
    ) -> None:
        slots: set[tuple[object, ...]] = set()
        now = self._now()
        for node in nodes:
            if node.subject != subject:
                raise ValueError("Every editor node must belong to its declared subject")
            if not allow_expired and not node.active_at(now):
                raise ValueError(
                    f"Editor node {node.type.value}:{node.key} is already expired"
                )
            if node.type is NodeType.PARENT:
                self._require_group(node.key)
            if node.type not in {NodeType.PREFIX, NodeType.SUFFIX} and node.priority != 0:
                raise ValueError(
                    f"Priority is only supported for prefix and suffix nodes, not {node.type.value}"
                )
            slot = (
                node.type,
                node.key,
                node.contexts.pairs,
                node.temporary,
                node.priority if node.type in {NodeType.PREFIX, NodeType.SUFFIX} else 0,
            )
            if slot in slots:
                raise ValueError(
                    f"Duplicate editor node slot {node.type.value}:{node.key} on "
                    f"{subject.type.value}:{subject.identifier}"
                )
            slots.add(slot)

    def _validate_editor_group_graph(
        self,
        subject_changes: tuple[EditorSubjectChange, ...],
    ) -> None:
        groups = {group.name for group in self.list_groups()}
        replacements = {
            change.subject.identifier: change.after
            for change in subject_changes
            if change.subject.type is SubjectType.GROUP
        }
        graph: dict[str, set[str]] = {}
        now = self._now()
        for group in groups:
            nodes = replacements.get(group)
            if nodes is None:
                nodes = self._repository.nodes_for(
                    SubjectRef.group(group), include_expired=True
                )
            parents = {
                node.key
                for node in nodes
                if node.type is NodeType.PARENT and node.active_at(now)
            }
            unknown = parents - groups
            if unknown:
                raise UnknownSubjectError(f"Unknown parent group {sorted(unknown)[0]!r}")
            graph[group] = parents

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(group: str) -> None:
            if group in visiting:
                raise ValueError(f"Editor changes would create a group inheritance cycle at {group!r}")
            if group in visited:
                return
            visiting.add(group)
            for parent in graph[group]:
                visit(parent)
            visiting.remove(group)
            visited.add(group)

        for group in sorted(groups):
            visit(group)

    def _ensure_subject(self, subject: SubjectRef) -> None:
        if subject.type is SubjectType.GROUP:
            if self._repository.get_group(subject.identifier) is None:
                raise UnknownSubjectError(f"Unknown group {subject.identifier!r}")
        elif self._repository.find_user(subject.identifier) is None:
            raise UnknownSubjectError(f"Unknown user UUID {subject.identifier!r}")

    def _set_string_node(
        self,
        subject: SubjectRef,
        node_type: NodeType,
        key: str,
        value: str,
        *,
        actor: str,
        contexts: ContextSet | None,
        expires_at: int | None,
        priority: int = 0,
    ) -> Node:
        if node_type not in {NodeType.META, NodeType.PREFIX, NodeType.SUFFIX}:
            raise ValueError(f"Unsupported string node type: {node_type.value}")
        self._ensure_subject(subject)
        node = Node(
            subject=subject,
            type=node_type,
            key=key,
            value=str(value),
            contexts=contexts or ContextSet(),
            expires_at=expires_at,
            priority=priority,
            created_at=self._now(),
        )
        suffix = "settemp" if expires_at is not None else "set"
        saved = self._repository.save_node(node, actor, f"{node_type.value}.{suffix}")
        self._invalidate()
        return saved

    def _unset_string_node(
        self,
        subject: SubjectRef,
        node_type: NodeType,
        key: str,
        *,
        actor: str,
        contexts: ContextSet | None,
        temporary: bool | None,
        priority: int | None = None,
    ) -> int:
        if node_type not in {NodeType.META, NodeType.PREFIX, NodeType.SUFFIX}:
            raise ValueError(f"Unsupported string node type: {node_type.value}")
        self._ensure_subject(subject)
        normalized_key = Node(subject, node_type, key, "validation", priority=priority or 0).key
        removed = self._repository.remove_nodes(
            subject,
            node_type,
            normalized_key,
            contexts or ContextSet(),
            actor,
            f"{node_type.value}.unset",
            temporary=temporary,
            priority=priority,
        )
        self._invalidate()
        return removed

    def _group_reaches(self, start: str, target: str) -> bool:
        queue = [normalize_group_name(start)]
        visited: set[str] = set()
        while queue:
            current = queue.pop()
            if current == target:
                return True
            if current in visited:
                continue
            visited.add(current)
            queue.extend(
                node.key
                for node in self._repository.nodes_for(
                    SubjectRef.group(current), include_expired=False
                )
                if node.type is NodeType.PARENT
            )
        return False

    def _require_group(self, name: str) -> str:
        normalized = normalize_group_name(name)
        if self._repository.get_group(normalized) is None:
            raise UnknownSubjectError(f"Unknown group {normalized!r}")
        return normalized

    def _set_track_groups(
        self,
        track: TrackRecord,
        groups: tuple[str, ...],
        actor: str,
        action: str,
        details: dict[str, object],
    ) -> TrackRecord:
        updated = self._repository.set_track_groups(
            track.name,
            groups,
            actor,
            action,
            details,
        )
        self._invalidate()
        return updated

    def _move_on_track(
        self,
        user: SubjectRef,
        track_name: str,
        action: TrackMoveAction,
        *,
        actor: str,
        contexts: ContextSet,
        cross_boundary: bool,
    ) -> TrackMoveResult:
        with self._track_lock:
            self._ensure_subject(user)
            if user.type is not SubjectType.USER:
                raise ValueError("Only users can be promoted or demoted")
            track = self.get_track(track_name)
            if len(track.groups) < 2:
                raise ValueError(
                    f"Track {track.name!r} needs at least two groups for promote/demote"
                )
            matching = tuple(
                node
                for node in self._active_direct_parents(user, contexts)
                if node.key in track.groups
            )
            if len(matching) > 1:
                return TrackMoveResult(
                    action,
                    TrackMoveStatus.AMBIGUOUS_CALL,
                    track.name,
                )
            if not matching:
                if action is TrackMoveAction.DEMOTE or not cross_boundary:
                    return TrackMoveResult(
                        action,
                        TrackMoveStatus.NOT_ON_TRACK,
                        track.name,
                    )
                destination = track.groups[0]
                new_node = Node(
                    user,
                    NodeType.PARENT,
                    destination,
                    "true",
                    contexts=contexts,
                    created_at=self._now(),
                )
                self._repository.replace_parent_node(
                    None,
                    new_node,
                    actor,
                    "track.promote",
                    {
                        "track": track.name,
                        "status": TrackMoveStatus.ADDED_TO_FIRST_GROUP.value,
                        "from": None,
                        "to": destination,
                        "contexts": list(contexts.pairs),
                    },
                )
                self._invalidate()
                return TrackMoveResult(
                    action,
                    TrackMoveStatus.ADDED_TO_FIRST_GROUP,
                    track.name,
                    group_to=destination,
                    changed=True,
                )

            old_node = matching[0]
            index = track.groups.index(old_node.key)
            if action is TrackMoveAction.PROMOTE:
                if index == len(track.groups) - 1:
                    return TrackMoveResult(
                        action,
                        TrackMoveStatus.END_OF_TRACK,
                        track.name,
                        group_from=old_node.key,
                    )
                destination = track.groups[index + 1]
                status = TrackMoveStatus.SUCCESS
            elif index == 0:
                if not cross_boundary:
                    return TrackMoveResult(
                        action,
                        TrackMoveStatus.FIRST_GROUP_PROTECTED,
                        track.name,
                        group_from=old_node.key,
                    )
                destination = None
                status = TrackMoveStatus.REMOVED_FROM_FIRST_GROUP
            else:
                destination = track.groups[index - 1]
                status = TrackMoveStatus.SUCCESS

            new_node = (
                Node(
                    user,
                    NodeType.PARENT,
                    destination,
                    "true",
                    contexts=old_node.contexts,
                    expires_at=old_node.expires_at,
                    created_at=self._now(),
                )
                if destination is not None
                else None
            )
            self._repository.replace_parent_node(
                old_node,
                new_node,
                actor,
                f"track.{action.value}",
                {
                    "track": track.name,
                    "status": status.value,
                    "from": old_node.key,
                    "to": destination,
                    "contexts": list(contexts.pairs),
                    "preserved_expiry": old_node.expires_at,
                },
            )
            self._invalidate()
            return TrackMoveResult(
                action,
                status,
                track.name,
                group_from=old_node.key,
                group_to=destination,
                changed=True,
            )

    def _active_direct_parents(
        self,
        user: SubjectRef,
        contexts: ContextSet | None,
    ) -> tuple[Node, ...]:
        now = self._now()
        return tuple(
            node
            for node in self._repository.nodes_for(user, include_expired=True)
            if node.type is NodeType.PARENT
            and (contexts is None or node.contexts == contexts)
            and node.active_at(now)
        )

    def _invalidate(self) -> None:
        self._snapshot_cache.clear()

    def _now(self) -> int:
        return int(self._clock())
