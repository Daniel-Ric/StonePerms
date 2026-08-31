from __future__ import annotations

import copy
import json
import secrets
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..domain.model import ContextSet, Node, NodeType, SubjectRef, SubjectType, TrackRecord
from ..domain.validation import normalize_permission
from .manager import StonePermsManager
from .ports import EditorSubjectChange, EditorTrackChange

PROTOCOL_VERSION = 1
SESSION_SCHEMA = "stoneperms.editor/session"
CHANGES_SCHEMA = "stoneperms.editor/changes"
RESULT_SCHEMA = "stoneperms.editor/result"

MAX_PAYLOAD_BYTES = 1_048_576
MAX_SUBJECTS = 500
MAX_TRACKS = 200
MAX_NODES = 5_000
MAX_NODES_PER_SUBJECT = 2_000
MAX_CONTEXTS_PER_NODE = 32
MAX_TRACK_GROUPS = 500


class EditorProtocolError(ValueError):
    pass


class EditorSessionNotFoundError(EditorProtocolError):
    pass


class EditorSessionExpiredError(EditorProtocolError):
    pass


class EditorSessionConsumedError(EditorProtocolError):
    pass


class EditorSessionBusyError(EditorProtocolError):
    pass


class EditorActorMismatchError(PermissionError):
    pass


@dataclass(slots=True)
class _EditorSession:
    session_id: str
    actor: str
    base_revision: int
    created_at: int
    expires_at: int
    subjects: dict[SubjectRef, tuple[Node, ...]]
    tracks: dict[str, tuple[str, ...]]
    document: dict[str, Any]
    status: str = "open"


@dataclass(frozen=True, slots=True)
class _EditorScope:
    base_revision: int
    users: tuple[SubjectRef, ...]
    include_groups: bool
    include_tracks: bool
    groups: tuple[Any, ...]
    tracks: tuple[TrackRecord, ...]
    subjects: dict[SubjectRef, tuple[Node, ...]]


class StonePermsEditorProtocol:
    def __init__(
        self,
        manager: StonePermsManager,
        *,
        known_permissions: Callable[[], Sequence[str]] | None = None,
        product_version: str,
        session_ttl_seconds: int = 900,
        max_sessions: int = 128,
        clock: Callable[[], float] = time.time,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        ttl = int(session_ttl_seconds)
        if ttl < 60 or ttl > 3_600:
            raise ValueError("Editor session TTL must be between 60 and 3600 seconds")
        self._manager = manager
        self._known_permissions = known_permissions or (lambda: ())
        self._product_version = str(product_version)
        self._ttl = ttl
        self._max_sessions = max(1, min(1_024, int(max_sessions)))
        self._clock = clock
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._sessions: dict[str, _EditorSession] = {}
        self._lock = threading.RLock()
        self._enabled = True

    def close(self) -> None:
        with self._lock:
            self._enabled = False
            self._sessions.clear()

    def create_session(
        self,
        actor: str,
        *,
        users: Sequence[str] = (),
        include_groups: bool = True,
        include_tracks: bool = True,
    ) -> dict[str, Any]:
        normalized_actor = _actor(actor)
        if isinstance(users, (str, bytes)):
            raise EditorProtocolError("Editor users must be a sequence, not one string")
        if not isinstance(include_groups, bool) or not isinstance(include_tracks, bool):
            raise EditorProtocolError("Editor scope flags must be true or false")

        self._require_enabled()
        self._manager.cleanup_expired()
        requested_users = self._requested_users(users)
        scope = self._capture_scope(requested_users, include_groups, include_tracks)
        created_at = int(self._clock())
        return self._store_session(normalized_actor, scope, created_at)

    def _requested_users(self, identifiers: Sequence[str]) -> tuple[SubjectRef, ...]:
        requested: list[SubjectRef] = []
        seen: set[str] = set()
        for identifier in identifiers:
            user = self._manager.find_user(str(identifier))
            if user.unique_id not in seen:
                requested.append(SubjectRef.user(user.unique_id))
                seen.add(user.unique_id)
        return tuple(requested)

    def _capture_scope(
        self,
        users: tuple[SubjectRef, ...],
        include_groups: bool,
        include_tracks: bool,
    ) -> _EditorScope:
        for _ in range(3):
            base_revision = self._manager.repository.revision
            groups = self._manager.list_groups()
            tracks = self._manager.list_tracks() if include_tracks else ()
            subject_refs = (
                tuple(SubjectRef.group(group.name) for group in groups)
                if include_groups
                else ()
            ) + users
            if len(subject_refs) > MAX_SUBJECTS:
                raise EditorProtocolError(f"Editor scope exceeds {MAX_SUBJECTS} subjects")
            if len(tracks) > MAX_TRACKS:
                raise EditorProtocolError(f"Editor scope exceeds {MAX_TRACKS} tracks")
            subjects = {
                subject: self._manager.nodes_for(subject)
                for subject in subject_refs
            }
            if sum(len(nodes) for nodes in subjects.values()) > MAX_NODES:
                raise EditorProtocolError(f"Editor scope exceeds {MAX_NODES} nodes")
            if self._manager.repository.revision == base_revision:
                return _EditorScope(
                    base_revision=base_revision,
                    users=users,
                    include_groups=include_groups,
                    include_tracks=include_tracks,
                    groups=tuple(groups),
                    tracks=tuple(tracks),
                    subjects=subjects,
                )
        raise EditorProtocolError("Permissions changed repeatedly while creating the session")

    def _store_session(
        self,
        actor: str,
        scope: _EditorScope,
        created_at: int,
    ) -> dict[str, Any]:
        expires_at = created_at + self._ttl
        with self._lock:
            self._require_enabled()
            self._remove_expired(created_at)
            active_sessions = sum(
                session.status != "consumed" for session in self._sessions.values()
            )
            if active_sessions >= self._max_sessions:
                raise EditorProtocolError("Too many editor sessions are currently open")
            self._trim_consumed()
            session_id = self._new_session_id()
            document = self._build_document(session_id, created_at, expires_at, scope)
            self._sessions[session_id] = _EditorSession(
                session_id=session_id,
                actor=actor,
                base_revision=scope.base_revision,
                created_at=created_at,
                expires_at=expires_at,
                subjects=scope.subjects,
                tracks={track.name: track.groups for track in scope.tracks},
                document=document,
            )
            return copy.deepcopy(document)

    def apply_changes(
        self,
        actor: str,
        payload: str | Mapping[str, Any],
    ) -> dict[str, Any]:
        normalized_actor = _actor(actor)
        raw = _parse_payload(payload)
        session_id = _required_text(raw.get("sessionId"), "sessionId", 128)
        now = int(self._clock())

        with self._lock:
            self._require_enabled()
            session = self._sessions.get(session_id)
            if session is None:
                raise EditorSessionNotFoundError("Unknown editor session")
            if session.expires_at <= now:
                del self._sessions[session_id]
                raise EditorSessionExpiredError("Editor session has expired")
            if session.actor != normalized_actor:
                raise EditorActorMismatchError("Editor session belongs to a different actor")
            if session.status == "consumed":
                raise EditorSessionConsumedError("Editor session has already been applied")
            if session.status == "applying":
                raise EditorSessionBusyError("Editor session is already being applied")
            session.status = "applying"

        try:
            subject_changes, track_changes = self._decode_changes(raw, session, now)
            storage = self._manager.apply_editor_batch(
                session.base_revision,
                subject_changes,
                track_changes,
                actor=normalized_actor,
                session_id=session.session_id,
            )
        except Exception:
            with self._lock:
                current = self._sessions.get(session_id)
                if current is session and current.status == "applying":
                    current.status = "open"
            raise

        with self._lock:
            session.status = "consumed"
        return {
            "schema": RESULT_SCHEMA,
            "version": PROTOCOL_VERSION,
            "sessionId": session.session_id,
            "baseRevision": session.base_revision,
            "revision": storage.revision,
            "changed": storage.changed,
            "changedSubjects": storage.changed_subjects,
            "changedTracks": storage.changed_tracks,
            "nodesAdded": storage.nodes_added,
            "nodesRemoved": storage.nodes_removed,
        }

    def _decode_changes(
        self,
        raw: Mapping[str, Any],
        session: _EditorSession,
        now: int,
    ) -> tuple[tuple[EditorSubjectChange, ...], tuple[EditorTrackChange, ...]]:
        _exact_keys(
            raw,
            {"schema", "version", "sessionId", "baseRevision", "subjects", "tracks"},
            "changeset",
        )
        if raw["schema"] != CHANGES_SCHEMA:
            raise EditorProtocolError(f"Unsupported editor schema {raw['schema']!r}")
        if _integer(raw["version"], "version", 1, 1) != PROTOCOL_VERSION:
            raise EditorProtocolError("Unsupported editor protocol version")
        base_revision = _integer(raw["baseRevision"], "baseRevision", 0, 2**63 - 1)
        if base_revision != session.base_revision:
            raise EditorProtocolError("Changeset baseRevision does not match the editor session")

        subjects = self._decode_subject_changes(raw["subjects"], session, now)
        tracks = self._decode_track_changes(raw["tracks"], session)
        return subjects, tracks

    def _decode_subject_changes(
        self,
        value: object,
        session: _EditorSession,
        now: int,
    ) -> tuple[EditorSubjectChange, ...]:
        changes: list[EditorSubjectChange] = []
        seen: set[SubjectRef] = set()
        node_count = 0
        for item in _list(value, "subjects", MAX_SUBJECTS):
            mapping = _mapping(item, "subject")
            _exact_keys(mapping, {"type", "id", "nodes"}, "subject")
            subject_type = _enum(SubjectType, mapping["type"], "subject type")
            identifier = _required_text(mapping["id"], "subject id", 128)
            subject = SubjectRef(subject_type, identifier)
            if identifier != subject.identifier or subject not in session.subjects:
                raise EditorProtocolError(
                    f"Subject {subject_type.value}:{identifier} is outside this editor session"
                )
            if subject in seen:
                raise EditorProtocolError(
                    f"Duplicate subject {subject.type.value}:{subject.identifier}"
                )
            seen.add(subject)

            raw_nodes = _list(mapping["nodes"], "nodes", MAX_NODES_PER_SUBJECT)
            node_count += len(raw_nodes)
            if node_count > MAX_NODES:
                raise EditorProtocolError(f"Changeset exceeds {MAX_NODES} nodes")
            after = tuple(self._decode_node(subject, node, now) for node in raw_nodes)
            changes.append(EditorSubjectChange(subject, session.subjects[subject], after))
        return tuple(changes)

    @staticmethod
    def _decode_track_changes(
        value: object,
        session: _EditorSession,
    ) -> tuple[EditorTrackChange, ...]:
        changes: list[EditorTrackChange] = []
        seen: set[str] = set()
        for item in _list(value, "tracks", MAX_TRACKS):
            mapping = _mapping(item, "track")
            _exact_keys(mapping, {"name", "groups"}, "track")
            name = _required_text(mapping["name"], "track name", 64)
            normalized = TrackRecord(name).name
            if name != normalized or normalized not in session.tracks:
                raise EditorProtocolError(f"Track {name!r} is outside this editor session")
            if normalized in seen:
                raise EditorProtocolError(f"Duplicate track {normalized!r}")
            seen.add(normalized)

            raw_groups = _list(mapping["groups"], "track groups", MAX_TRACK_GROUPS)
            if any(not isinstance(group, str) for group in raw_groups):
                raise EditorProtocolError("Track groups must be strings")
            after = TrackRecord(normalized, tuple(raw_groups)).groups
            if list(after) != raw_groups:
                raise EditorProtocolError("Track groups must use canonical lowercase names")
            changes.append(EditorTrackChange(normalized, session.tracks[normalized], after))
        return tuple(changes)

    @staticmethod
    def _decode_node(subject: SubjectRef, raw: object, now: int) -> Node:
        mapping = _mapping(raw, "node")
        _exact_keys(
            mapping,
            {"type", "key", "value", "contexts", "expiresAt", "priority"},
            "node",
        )
        node_type = _enum(NodeType, mapping["type"], "node type")
        key = _required_text(mapping["key"], "node key", 255)
        value = _required_text(mapping["value"], "node value", 1_024, strip=False)
        raw_contexts = _list(mapping["contexts"], "node contexts", MAX_CONTEXTS_PER_NODE)
        pairs: list[tuple[str, str]] = []
        for item in raw_contexts:
            context = _mapping(item, "context")
            _exact_keys(context, {"key", "value"}, "context")
            pairs.append(
                (
                    _required_text(context["key"], "context key", 64),
                    _required_text(context["value"], "context value", 128),
                )
            )
        contexts = ContextSet.of(pairs)
        if len(contexts.pairs) != len(pairs):
            raise EditorProtocolError("Duplicate node context pair")
        if tuple(pairs) != contexts.pairs:
            raise EditorProtocolError("Node contexts must be canonical, normalized, and sorted")
        expiry_raw = mapping["expiresAt"]
        expires_at = (
            None
            if expiry_raw is None
            else _integer(expiry_raw, "expiresAt", 1, 2**63 - 1)
        )
        if expires_at is not None and expires_at <= now:
            raise EditorProtocolError("Submitted editor nodes must not already be expired")
        priority = _integer(mapping["priority"], "priority", -(2**31), 2**31 - 1)
        try:
            node = Node(
                subject,
                node_type,
                key,
                value,
                contexts=contexts,
                expires_at=expires_at,
                priority=priority,
            )
        except ValueError as exc:
            raise EditorProtocolError(str(exc)) from exc
        if node.key != key or node.value != value:
            raise EditorProtocolError("Node key and value must use their canonical representation")
        return node

    def _build_document(
        self,
        session_id: str,
        created_at: int,
        expires_at: int,
        scope: _EditorScope,
    ) -> dict[str, Any]:
        group_records = {group.name: group for group in scope.groups}
        subjects: list[dict[str, Any]] = []
        for subject in sorted(scope.subjects):
            entry: dict[str, Any] = {
                "type": subject.type.value,
                "id": subject.identifier,
                "nodes": [
                    _serialize_node(node)
                    for node in sorted(scope.subjects[subject], key=_node_key)
                ],
            }
            if subject.type is SubjectType.GROUP:
                group = group_records[subject.identifier]
                entry.update(displayName=group.display_name, weight=group.weight)
            else:
                user = self._manager.find_user(subject.identifier)
                entry.update(name=user.last_name, xuid=user.xuid)
            subjects.append(entry)

        all_nodes = tuple(node for nodes in scope.subjects.values() for node in nodes)
        known_permissions: set[str] = {
            node.key for node in all_nodes if node.type is NodeType.PERMISSION
        }
        for permission in self._known_permissions():
            try:
                known_permissions.add(normalize_permission(str(permission)))
            except (TypeError, ValueError):
                continue
        potential_contexts: dict[str, set[str]] = {}
        for node in all_nodes:
            for key, value in node.contexts.pairs:
                potential_contexts.setdefault(key, set()).add(value)

        return {
            "schema": SESSION_SCHEMA,
            "version": PROTOCOL_VERSION,
            "sessionId": session_id,
            "baseRevision": scope.base_revision,
            "createdAt": created_at,
            "expiresAt": expires_at,
            "scope": {
                "users": [subject.identifier for subject in scope.users],
                "groups": scope.include_groups,
                "tracks": scope.include_tracks,
            },
            "metadata": {
                "product": "StonePerms",
                "productVersion": self._product_version,
                "defaultGroup": self._manager.default_group,
                "groups": [
                    {
                        "name": group.name,
                        "displayName": group.display_name,
                        "weight": group.weight,
                    }
                    for group in scope.groups
                ],
            },
            "subjects": subjects,
            "tracks": [
                {"name": track.name, "groups": list(track.groups)} for track in scope.tracks
            ],
            "knownPermissions": sorted(known_permissions),
            "potentialContexts": [
                {"key": key, "values": sorted(values)}
                for key, values in sorted(potential_contexts.items())
            ],
        }

    def _new_session_id(self) -> str:
        for _ in range(10):
            session_id = str(self._token_factory()).strip()
            if 32 <= len(session_id) <= 128 and session_id not in self._sessions:
                return session_id
        raise RuntimeError("Could not allocate a unique editor session id")

    def _remove_expired(self, now: int) -> None:
        for session_id, session in tuple(self._sessions.items()):
            if session.expires_at <= now and session.status != "applying":
                del self._sessions[session_id]

    def _trim_consumed(self) -> None:
        excess = len(self._sessions) - self._max_sessions * 2
        if excess < 0:
            return
        consumed = sorted(
            (
                session
                for session in self._sessions.values()
                if session.status == "consumed"
            ),
            key=lambda session: session.created_at,
        )
        for session in consumed[: excess + 1]:
            del self._sessions[session.session_id]

    def _require_enabled(self) -> None:
        if not self._enabled:
            raise EditorProtocolError("StonePerms editor protocol is disabled")


def _parse_payload(payload: str | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(payload, str):
        if len(payload.encode("utf-8")) > MAX_PAYLOAD_BYTES:
            raise EditorProtocolError(f"Editor payload exceeds {MAX_PAYLOAD_BYTES} bytes")
        try:
            raw = json.loads(
                payload,
                object_pairs_hook=_unique_object,
                parse_constant=lambda value: (_ for _ in ()).throw(
                    EditorProtocolError(f"Invalid JSON constant {value}")
                ),
            )
        except json.JSONDecodeError as exc:
            raise EditorProtocolError("Editor payload is not valid JSON") from exc
    elif isinstance(payload, Mapping):
        raw = payload
    else:
        raise EditorProtocolError("Editor payload must be a JSON object or mapping")
    return _mapping(raw, "changeset")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EditorProtocolError(f"Duplicate JSON field {key!r}")
        result[key] = value
    return result


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise EditorProtocolError(f"Editor {label} must be an object")
    return value


def _list(value: object, label: str, maximum: int) -> list[Any]:
    if not isinstance(value, list):
        raise EditorProtocolError(f"Editor {label} must be an array")
    if len(value) > maximum:
        raise EditorProtocolError(f"Editor {label} exceeds the limit of {maximum}")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        details = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if unknown:
            details.append(f"unknown {', '.join(unknown)}")
        raise EditorProtocolError(f"Invalid editor {label}: {'; '.join(details)}")


def _required_text(value: object, label: str, maximum: int, *, strip: bool = True) -> str:
    if not isinstance(value, str):
        raise EditorProtocolError(f"Editor {label} must be text")
    result = value.strip() if strip else value
    if not result.strip() or len(result) > maximum:
        raise EditorProtocolError(f"Editor {label} must contain 1-{maximum} characters")
    return result


def _integer(value: object, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EditorProtocolError(f"Editor {label} must be an integer")
    if value < minimum or value > maximum:
        raise EditorProtocolError(f"Editor {label} is outside the supported range")
    return value


def _enum(enum_type: type[Any], value: object, label: str) -> Any:
    if not isinstance(value, str):
        raise EditorProtocolError(f"Editor {label} must be text")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise EditorProtocolError(f"Unsupported editor {label} {value!r}") from exc


def _actor(value: str) -> str:
    actor = str(value).strip()
    if not actor or len(actor) > 128:
        raise EditorProtocolError("Editor actor must contain 1-128 characters")
    return actor


def _serialize_node(node: Node) -> dict[str, Any]:
    return {
        "type": node.type.value,
        "key": node.key,
        "value": node.value,
        "contexts": [{"key": key, "value": value} for key, value in node.contexts.pairs],
        "expiresAt": node.expires_at,
        "priority": node.priority,
    }


def _node_key(node: Node) -> tuple[object, ...]:
    return (
        node.type.value,
        node.key,
        node.contexts.pairs,
        node.expires_at or 0,
        node.priority,
        node.value,
    )
