from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from ..application.ports import (
    EditorStorageResult,
    EditorSubjectChange,
    EditorTrackChange,
    ExpiredNodes,
    RevisionConflictError,
)
from ..domain.model import (
    ContextSet,
    GroupRecord,
    Node,
    NodeType,
    PermissionSnapshot,
    PlayerProfile,
    SubjectRef,
    SubjectType,
    TrackRecord,
    UserRecord,
)
from ..domain.validation import normalize_group_name, normalize_track_name

SCHEMA_VERSION = 3

MIGRATION_1 = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    unique_id TEXT PRIMARY KEY,
    xuid TEXT,
    last_name TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS users_xuid_unique
    ON users(xuid) WHERE xuid IS NOT NULL AND xuid <> '';
CREATE INDEX IF NOT EXISTS users_last_name_lookup ON users(last_name COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS permission_groups (
    name TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    weight INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_type TEXT NOT NULL CHECK(subject_type IN ('user', 'group')),
    subject_id TEXT NOT NULL,
    node_type TEXT NOT NULL CHECK(node_type IN ('permission', 'parent', 'meta', 'prefix', 'suffix')),
    node_key TEXT NOT NULL,
    node_value TEXT NOT NULL,
    contexts_json TEXT NOT NULL DEFAULT '[]',
    expires_at INTEGER,
    priority INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS nodes_subject_lookup
    ON nodes(subject_type, subject_id);
CREATE INDEX IF NOT EXISTS nodes_expiry_lookup
    ON nodes(expires_at) WHERE expires_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS nodes_permission_lookup
    ON nodes(node_type, node_key);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at INTEGER NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    subject_type TEXT,
    subject_id TEXT,
    details_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_created_lookup ON audit_log(created_at DESC, id DESC);
"""

MIGRATION_2 = """
CREATE TABLE IF NOT EXISTS tracks (
    name TEXT PRIMARY KEY,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS track_groups (
    track_name TEXT NOT NULL REFERENCES tracks(name) ON DELETE CASCADE ON UPDATE CASCADE,
    group_name TEXT NOT NULL REFERENCES permission_groups(name) ON DELETE RESTRICT,
    position INTEGER NOT NULL CHECK(position >= 0),
    PRIMARY KEY(track_name, group_name),
    UNIQUE(track_name, position)
);
CREATE INDEX IF NOT EXISTS track_groups_position_lookup
    ON track_groups(track_name, position);
"""

MIGRATION_3 = """
ALTER TABLE users ADD COLUMN locale TEXT;
ALTER TABLE users ADD COLUMN device_os TEXT;
ALTER TABLE users ADD COLUMN game_version TEXT;
ALTER TABLE users ADD COLUMN game_mode TEXT;
ALTER TABLE users ADD COLUMN ping_ms INTEGER;
ALTER TABLE users ADD COLUMN total_exp INTEGER;
ALTER TABLE users ADD COLUMN exp_level INTEGER;
ALTER TABLE users ADD COLUMN skin_id TEXT;
ALTER TABLE users ADD COLUMN skin_hash TEXT;
ALTER TABLE users ADD COLUMN skin_width INTEGER;
ALTER TABLE users ADD COLUMN skin_height INTEGER;
ALTER TABLE users ADD COLUMN skin_rgba BLOB;
ALTER TABLE users ADD COLUMN cape_id TEXT;
ALTER TABLE users ADD COLUMN first_seen_at INTEGER;
ALTER TABLE users ADD COLUMN last_seen_at INTEGER;
ALTER TABLE users ADD COLUMN last_joined_at INTEGER;
ALTER TABLE users ADD COLUMN last_quit_at INTEGER;
ALTER TABLE users ADD COLUMN skin_updated_at INTEGER;
ALTER TABLE users ADD COLUMN online INTEGER NOT NULL DEFAULT 0 CHECK(online IN (0, 1));

UPDATE users
SET first_seen_at = created_at,
    last_seen_at = updated_at
WHERE first_seen_at IS NULL OR last_seen_at IS NULL;

CREATE INDEX IF NOT EXISTS users_last_seen_lookup ON users(last_seen_at DESC);
CREATE INDEX IF NOT EXISTS users_online_lookup ON users(online, last_seen_at DESC);
"""

_PROFILE_COLUMNS = """
unique_id, last_name, xuid, locale, device_os, game_version, game_mode,
ping_ms, total_exp, exp_level, skin_id, skin_hash, skin_width, skin_height,
skin_rgba, cape_id, first_seen_at, last_seen_at, last_joined_at,
last_quit_at, skin_updated_at, online
"""


class SqlitePermissionRepository:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._connection: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        self._revision = 0

    @property
    def revision(self) -> int:
        return self._revision

    def initialize(self, default_group: str) -> None:
        group_name = normalize_group_name(default_group)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._path, timeout=10, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute("PRAGMA busy_timeout = 10000")
        self._connection = connection

        with self._lock, connection:
            connection.executescript(MIGRATION_1)
            row = connection.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()
            current = int(row["version"] or 0)
            if current > SCHEMA_VERSION:
                raise RuntimeError(
                    f"StonePerms database schema {current} is newer than supported {SCHEMA_VERSION}"
                )
            if current < 1:
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (1, int(time.time())),
                )
                current = 1
            if current < 2:
                connection.executescript(MIGRATION_2)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (2, int(time.time())),
                )
                current = 2
            if current < 3:
                connection.executescript(MIGRATION_3)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (3, int(time.time())),
                )
            connection.execute("UPDATE users SET online = 0 WHERE online <> 0")
            timestamp = int(time.time())
            connection.execute(
                """
                INSERT OR IGNORE INTO permission_groups(name, display_name, weight, created_at, updated_at)
                VALUES (?, ?, 0, ?, ?)
                """,
                (group_name, group_name, timestamp, timestamp),
            )
        self._revision += 1

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def upsert_user(self, user: UserRecord) -> None:
        connection = self._require_connection()
        timestamp = int(time.time())
        xuid = str(user.xuid).strip() if user.xuid else None
        with self._lock, connection:
            connection.execute(
                """
                INSERT INTO users(unique_id, xuid, last_name, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(unique_id) DO UPDATE SET
                    xuid = excluded.xuid,
                    last_name = excluded.last_name,
                    updated_at = excluded.updated_at
                """,
                (str(user.unique_id), xuid, str(user.last_name), timestamp, timestamp),
            )

    def find_user(self, identifier: str) -> UserRecord | None:
        connection = self._require_connection()
        value = str(identifier).strip()
        with self._lock:
            row = connection.execute(
                """
                SELECT unique_id, xuid, last_name
                FROM users
                WHERE unique_id = ? OR xuid = ? OR last_name = ? COLLATE NOCASE
                ORDER BY CASE WHEN unique_id = ? THEN 0 WHEN xuid = ? THEN 1 ELSE 2 END
                LIMIT 1
                """,
                (value, value, value, value, value),
            ).fetchone()
        return self._row_to_user(row) if row is not None else None

    def list_users(self) -> tuple[UserRecord, ...]:
        connection = self._require_connection()
        with self._lock:
            rows = connection.execute(
                """
                SELECT unique_id, xuid, last_name
                FROM users
                ORDER BY last_name COLLATE NOCASE, unique_id
                """
            ).fetchall()
        return tuple(self._row_to_user(row) for row in rows)

    def upsert_player_profile(self, profile: PlayerProfile) -> PlayerProfile:
        connection = self._require_connection()
        xuid = str(profile.xuid).strip() if profile.xuid else None
        with self._lock, connection:
            connection.execute(
                """
                INSERT INTO users(
                    unique_id, xuid, last_name, created_at, updated_at,
                    locale, device_os, game_version, game_mode, ping_ms, total_exp, exp_level,
                    skin_id, skin_hash, skin_width, skin_height, skin_rgba, cape_id,
                    first_seen_at, last_seen_at, last_joined_at, last_quit_at,
                    skin_updated_at, online
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(unique_id) DO UPDATE SET
                    xuid = COALESCE(excluded.xuid, users.xuid),
                    last_name = excluded.last_name,
                    updated_at = excluded.updated_at,
                    locale = COALESCE(excluded.locale, users.locale),
                    device_os = COALESCE(excluded.device_os, users.device_os),
                    game_version = COALESCE(excluded.game_version, users.game_version),
                    game_mode = COALESCE(excluded.game_mode, users.game_mode),
                    ping_ms = COALESCE(excluded.ping_ms, users.ping_ms),
                    total_exp = COALESCE(excluded.total_exp, users.total_exp),
                    exp_level = COALESCE(excluded.exp_level, users.exp_level),
                    skin_id = CASE WHEN excluded.skin_hash IS NOT NULL
                        THEN excluded.skin_id ELSE users.skin_id END,
                    skin_hash = COALESCE(excluded.skin_hash, users.skin_hash),
                    skin_width = CASE WHEN excluded.skin_hash IS NOT NULL
                        THEN excluded.skin_width ELSE users.skin_width END,
                    skin_height = CASE WHEN excluded.skin_hash IS NOT NULL
                        THEN excluded.skin_height ELSE users.skin_height END,
                    skin_rgba = CASE WHEN excluded.skin_hash IS NOT NULL
                        THEN excluded.skin_rgba ELSE users.skin_rgba END,
                    cape_id = CASE WHEN excluded.skin_hash IS NOT NULL
                        THEN excluded.cape_id ELSE users.cape_id END,
                    first_seen_at = COALESCE(users.first_seen_at, excluded.first_seen_at),
                    last_seen_at = excluded.last_seen_at,
                    last_joined_at = COALESCE(excluded.last_joined_at, users.last_joined_at),
                    last_quit_at = COALESCE(excluded.last_quit_at, users.last_quit_at),
                    skin_updated_at = CASE
                        WHEN excluded.skin_hash IS NOT NULL
                             AND (users.skin_hash IS NULL OR excluded.skin_hash <> users.skin_hash)
                        THEN excluded.skin_updated_at
                        ELSE users.skin_updated_at
                    END,
                    online = excluded.online
                """,
                (
                    str(profile.unique_id),
                    xuid,
                    str(profile.last_name),
                    int(profile.first_seen_at),
                    int(profile.last_seen_at),
                    profile.locale,
                    profile.device_os,
                    profile.game_version,
                    profile.game_mode,
                    profile.ping_ms,
                    profile.total_exp,
                    profile.exp_level,
                    profile.skin_id,
                    profile.skin_hash,
                    profile.skin_width,
                    profile.skin_height,
                    profile.skin_rgba,
                    profile.cape_id,
                    int(profile.first_seen_at),
                    int(profile.last_seen_at),
                    profile.last_joined_at,
                    profile.last_quit_at,
                    profile.skin_updated_at,
                    int(profile.online),
                ),
            )
        stored = self.get_player_profile(profile.unique_id)
        if stored is None:
            raise RuntimeError("Player profile could not be read after persistence")
        return stored

    def get_player_profile(self, identifier: str) -> PlayerProfile | None:
        connection = self._require_connection()
        value = str(identifier).strip()
        with self._lock:
            row = connection.execute(
                f"""
                SELECT {_PROFILE_COLUMNS}
                FROM users
                WHERE unique_id = ? OR xuid = ? OR last_name = ? COLLATE NOCASE
                ORDER BY CASE WHEN unique_id = ? THEN 0 WHEN xuid = ? THEN 1 ELSE 2 END
                LIMIT 1
                """,
                (value, value, value, value, value),
            ).fetchone()
        return self._row_to_profile(row) if row is not None else None

    def list_player_profiles(self) -> tuple[PlayerProfile, ...]:
        connection = self._require_connection()
        with self._lock:
            rows = connection.execute(
                f"""
                SELECT {_PROFILE_COLUMNS}
                FROM users
                ORDER BY online DESC, last_seen_at DESC, last_name COLLATE NOCASE
                """
            ).fetchall()
        return tuple(self._row_to_profile(row) for row in rows)

    def create_group(self, group: GroupRecord, actor: str) -> bool:
        connection = self._require_connection()
        timestamp = int(time.time())
        with self._lock, connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO permission_groups(name, display_name, weight, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (group.name, group.display_name, group.weight, timestamp, timestamp),
            )
            created = cursor.rowcount > 0
            if created:
                self._insert_audit(
                    connection,
                    actor,
                    "group.create",
                    SubjectRef.group(group.name),
                    {"display_name": group.display_name, "weight": group.weight},
                    timestamp,
                )
        if created:
            self._revision += 1
        return created

    def get_group(self, name: str) -> GroupRecord | None:
        connection = self._require_connection()
        normalized = normalize_group_name(name)
        with self._lock:
            row = connection.execute(
                "SELECT name, display_name, weight FROM permission_groups WHERE name = ?",
                (normalized,),
            ).fetchone()
        return self._row_to_group(row) if row is not None else None

    def list_groups(self) -> tuple[GroupRecord, ...]:
        connection = self._require_connection()
        with self._lock:
            rows = connection.execute(
                "SELECT name, display_name, weight FROM permission_groups ORDER BY weight DESC, name"
            ).fetchall()
        return tuple(self._row_to_group(row) for row in rows)

    def set_group_weight(self, name: str, weight: int, actor: str) -> None:
        connection = self._require_connection()
        normalized = normalize_group_name(name)
        timestamp = int(time.time())
        with self._lock, connection:
            cursor = connection.execute(
                "UPDATE permission_groups SET weight = ?, updated_at = ? WHERE name = ?",
                (int(weight), timestamp, normalized),
            )
            if cursor.rowcount == 0:
                raise KeyError(normalized)
            self._insert_audit(
                connection,
                actor,
                "group.weight.set",
                SubjectRef.group(normalized),
                {"weight": int(weight)},
                timestamp,
            )
        self._revision += 1

    def delete_group(self, name: str, actor: str) -> bool:
        connection = self._require_connection()
        normalized = normalize_group_name(name)
        timestamp = int(time.time())
        with self._lock, connection:
            group = connection.execute(
                "SELECT display_name, weight FROM permission_groups WHERE name = ?",
                (normalized,),
            ).fetchone()
            if group is None:
                return False
            track_rows = connection.execute(
                "SELECT track_name FROM track_groups WHERE group_name = ? ORDER BY track_name",
                (normalized,),
            ).fetchall()
            track_names = tuple(row["track_name"] for row in track_rows)
            owned_nodes = connection.execute(
                "DELETE FROM nodes WHERE subject_type = 'group' AND subject_id = ?",
                (normalized,),
            ).rowcount
            parent_references = connection.execute(
                "DELETE FROM nodes WHERE node_type = 'parent' AND node_key = ?",
                (normalized,),
            ).rowcount
            connection.execute("DELETE FROM track_groups WHERE group_name = ?", (normalized,))
            for track_name in track_names:
                groups = self._load_track_groups(connection, track_name)
                for position, group_name in enumerate(groups):
                    connection.execute(
                        "UPDATE track_groups SET position = ? WHERE track_name = ? AND group_name = ?",
                        (position, track_name, group_name),
                    )
                connection.execute(
                    "UPDATE tracks SET updated_at = ? WHERE name = ?",
                    (timestamp, track_name),
                )
            cursor = connection.execute(
                "DELETE FROM permission_groups WHERE name = ?",
                (normalized,),
            )
            deleted = cursor.rowcount > 0
            if deleted:
                self._insert_audit(
                    connection,
                    actor,
                    "group.delete",
                    SubjectRef.group(normalized),
                    {
                        "display_name": group["display_name"],
                        "weight": int(group["weight"]),
                        "owned_nodes": owned_nodes,
                        "parent_references": parent_references,
                        "tracks": list(track_names),
                    },
                    timestamp,
                )
        if deleted:
            self._revision += 1
        return deleted

    def create_track(
        self,
        track: TrackRecord,
        actor: str,
        action: str = "track.create",
    ) -> bool:
        connection = self._require_connection()
        timestamp = int(time.time())
        with self._lock, connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO tracks(name, created_at, updated_at) VALUES (?, ?, ?)",
                (track.name, timestamp, timestamp),
            )
            created = cursor.rowcount > 0
            if created:
                self._insert_track_groups(connection, track.name, track.groups)
                self._insert_audit(
                    connection,
                    actor,
                    action,
                    ("track", track.name),
                    {"groups": list(track.groups)},
                    timestamp,
                )
        if created:
            self._revision += 1
        return created

    def get_track(self, name: str) -> TrackRecord | None:
        connection = self._require_connection()
        normalized = normalize_track_name(name)
        with self._lock:
            row = connection.execute("SELECT name FROM tracks WHERE name = ?", (normalized,)).fetchone()
            if row is None:
                return None
            groups = self._load_track_groups(connection, normalized)
        return TrackRecord(normalized, groups)

    def list_tracks(self) -> tuple[TrackRecord, ...]:
        connection = self._require_connection()
        with self._lock:
            rows = connection.execute("SELECT name FROM tracks ORDER BY name").fetchall()
            return tuple(
                TrackRecord(row["name"], self._load_track_groups(connection, row["name"]))
                for row in rows
            )

    def set_track_groups(
        self,
        name: str,
        groups: tuple[str, ...],
        actor: str,
        action: str,
        details: dict[str, Any],
    ) -> TrackRecord:
        connection = self._require_connection()
        track = TrackRecord(name, groups)
        timestamp = int(time.time())
        with self._lock, connection:
            cursor = connection.execute(
                "UPDATE tracks SET updated_at = ? WHERE name = ?",
                (timestamp, track.name),
            )
            if cursor.rowcount == 0:
                raise KeyError(track.name)
            connection.execute("DELETE FROM track_groups WHERE track_name = ?", (track.name,))
            self._insert_track_groups(connection, track.name, track.groups)
            self._insert_audit(
                connection,
                actor,
                action,
                ("track", track.name),
                {**details, "groups": list(track.groups)},
                timestamp,
            )
        self._revision += 1
        return track

    def rename_track(self, name: str, new_name: str, actor: str) -> bool:
        connection = self._require_connection()
        current = normalize_track_name(name)
        target = normalize_track_name(new_name)
        timestamp = int(time.time())
        with self._lock, connection:
            if connection.execute("SELECT 1 FROM tracks WHERE name = ?", (target,)).fetchone():
                return False
            cursor = connection.execute(
                "UPDATE tracks SET name = ?, updated_at = ? WHERE name = ?",
                (target, timestamp, current),
            )
            renamed = cursor.rowcount > 0
            if renamed:
                self._insert_audit(
                    connection,
                    actor,
                    "track.rename",
                    ("track", target),
                    {"from": current, "to": target},
                    timestamp,
                )
        if renamed:
            self._revision += 1
        return renamed

    def delete_track(self, name: str, actor: str) -> bool:
        connection = self._require_connection()
        normalized = normalize_track_name(name)
        timestamp = int(time.time())
        with self._lock, connection:
            groups = self._load_track_groups(connection, normalized)
            cursor = connection.execute("DELETE FROM tracks WHERE name = ?", (normalized,))
            deleted = cursor.rowcount > 0
            if deleted:
                self._insert_audit(
                    connection,
                    actor,
                    "track.delete",
                    ("track", normalized),
                    {"groups": list(groups)},
                    timestamp,
                )
        if deleted:
            self._revision += 1
        return deleted

    def save_node(self, node: Node, actor: str, action: str) -> Node:
        connection = self._require_connection()
        timestamp = int(time.time())
        contexts_json = node.contexts.to_json()
        with self._lock, connection:
            replacement_query, replacement_params = self._replacement_query(node, contexts_json)
            connection.execute(replacement_query, replacement_params)
            cursor = connection.execute(
                """
                INSERT INTO nodes(
                    subject_type, subject_id, node_type, node_key, node_value,
                    contexts_json, expires_at, priority, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    node.subject.type.value,
                    node.subject.identifier,
                    node.type.value,
                    node.key,
                    node.value,
                    contexts_json,
                    node.expires_at,
                    node.priority,
                    timestamp,
                ),
            )
            saved = Node(
                subject=node.subject,
                type=node.type,
                key=node.key,
                value=node.value,
                contexts=node.contexts,
                expires_at=node.expires_at,
                priority=node.priority,
                created_at=timestamp,
                id=int(cursor.lastrowid),
            )
            self._insert_audit(
                connection,
                actor,
                action,
                node.subject,
                self._node_details(saved),
                timestamp,
            )
        self._revision += 1
        return saved

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
    ) -> int:
        connection = self._require_connection()
        query = (
            "DELETE FROM nodes WHERE subject_type = ? AND subject_id = ? "
            "AND node_type = ? AND node_key = ? AND contexts_json = ?"
        )
        params: list[object] = [
            subject.type.value,
            subject.identifier,
            node_type.value,
            str(key),
            contexts.to_json(),
        ]
        if temporary is True:
            query += " AND expires_at IS NOT NULL"
        elif temporary is False:
            query += " AND expires_at IS NULL"
        if priority is not None:
            query += " AND priority = ?"
            params.append(int(priority))
        timestamp = int(time.time())
        with self._lock, connection:
            cursor = connection.execute(query, params)
            removed = cursor.rowcount
            if removed:
                self._insert_audit(
                    connection,
                    actor,
                    action,
                    subject,
                    {
                        "node_type": node_type.value,
                        "key": key,
                        "contexts": list(contexts.pairs),
                        "temporary": temporary,
                        "priority": priority,
                        "removed": removed,
                    },
                    timestamp,
                )
        if removed:
            self._revision += 1
        return removed

    def replace_parent_node(
        self,
        old_node: Node | None,
        new_node: Node | None,
        actor: str,
        action: str,
        details: dict[str, Any],
    ) -> Node | None:
        if old_node is None and new_node is None:
            raise ValueError("A parent replacement needs an old or a new node")
        subject = old_node.subject if old_node is not None else new_node.subject
        if old_node is not None and old_node.type is not NodeType.PARENT:
            raise ValueError("The old node must be a parent node")
        if new_node is not None and new_node.type is not NodeType.PARENT:
            raise ValueError("The new node must be a parent node")
        if new_node is not None and new_node.subject != subject:
            raise ValueError("Parent replacements must stay on the same subject")

        connection = self._require_connection()
        timestamp = int(time.time())
        saved: Node | None = None
        with self._lock, connection:
            if old_node is not None:
                if old_node.id is None:
                    raise ValueError("The old parent node must be persisted")
                cursor = connection.execute(
                    "DELETE FROM nodes WHERE id = ? AND subject_type = ? AND subject_id = ? "
                    "AND node_type = 'parent'",
                    (old_node.id, subject.type.value, subject.identifier),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("The parent assignment changed concurrently")
            if new_node is not None:
                contexts_json = new_node.contexts.to_json()
                replacement_query, replacement_params = self._replacement_query(
                    new_node, contexts_json
                )
                connection.execute(replacement_query, replacement_params)
                cursor = connection.execute(
                    """
                    INSERT INTO nodes(
                        subject_type, subject_id, node_type, node_key, node_value,
                        contexts_json, expires_at, priority, created_at
                    ) VALUES (?, ?, 'parent', ?, 'true', ?, ?, 0, ?)
                    """,
                    (
                        subject.type.value,
                        subject.identifier,
                        new_node.key,
                        contexts_json,
                        new_node.expires_at,
                        timestamp,
                    ),
                )
                saved = Node(
                    subject=subject,
                    type=NodeType.PARENT,
                    key=new_node.key,
                    value="true",
                    contexts=new_node.contexts,
                    expires_at=new_node.expires_at,
                    created_at=timestamp,
                    id=int(cursor.lastrowid),
                )
            self._insert_audit(
                connection,
                actor,
                action,
                subject,
                {**details, "new_node_id": saved.id if saved is not None else None},
                timestamp,
            )
        self._revision += 1
        return saved

    def apply_editor_batch(
        self,
        expected_revision: int,
        subject_changes: tuple[EditorSubjectChange, ...],
        track_changes: tuple[EditorTrackChange, ...],
        actor: str,
        session_id: str,
    ) -> EditorStorageResult:
        connection = self._require_connection()
        timestamp = int(time.time())
        with self._lock:
            if self._revision != int(expected_revision):
                raise RevisionConflictError(
                    f"Editor base revision {expected_revision} is stale; current revision is "
                    f"{self._revision}"
                )

            with connection:
                current_nodes = self._editor_subject_state(subject_changes)
                self._check_editor_tracks(connection, track_changes)
                nodes_added, nodes_removed, changed_subjects = self._apply_editor_subjects(
                    connection,
                    subject_changes,
                    current_nodes,
                    actor,
                    session_id,
                    timestamp,
                )
                changed_tracks = self._apply_editor_tracks(
                    connection,
                    track_changes,
                    actor,
                    session_id,
                    timestamp,
                )
                changed = bool(changed_subjects or changed_tracks)
                if changed:
                    self._insert_audit(
                        connection,
                        actor,
                        "editor.apply",
                        None,
                        {
                            "session_id": session_id,
                            "base_revision": int(expected_revision),
                            "changed_subjects": changed_subjects,
                            "changed_tracks": changed_tracks,
                            "nodes_added": nodes_added,
                            "nodes_removed": nodes_removed,
                        },
                        timestamp,
                    )

            if changed:
                self._revision += 1
            return EditorStorageResult(
                revision=self._revision,
                changed_subjects=changed_subjects,
                changed_tracks=changed_tracks,
                nodes_added=nodes_added,
                nodes_removed=nodes_removed,
            )

    def _editor_subject_state(
        self,
        changes: tuple[EditorSubjectChange, ...],
    ) -> dict[SubjectRef, tuple[Node, ...]]:
        current_nodes: dict[SubjectRef, tuple[Node, ...]] = {}
        for change in changes:
            current = self.nodes_for(change.subject, include_expired=True)
            if _node_counts(current) != _node_counts(change.before):
                raise RevisionConflictError(
                    f"Editor subject {change.subject.type.value}:"
                    f"{change.subject.identifier} changed since the session was created"
                )
            current_nodes[change.subject] = current
        return current_nodes

    def _check_editor_tracks(
        self,
        connection: sqlite3.Connection,
        changes: tuple[EditorTrackChange, ...],
    ) -> None:
        for change in changes:
            row = connection.execute(
                "SELECT name FROM tracks WHERE name = ?",
                (change.name,),
            ).fetchone()
            if row is None or self._load_track_groups(connection, change.name) != change.before:
                raise RevisionConflictError(
                    f"Editor track {change.name!r} changed since the session was created"
                )

    def _apply_editor_subjects(
        self,
        connection: sqlite3.Connection,
        changes: tuple[EditorSubjectChange, ...],
        current_nodes: dict[SubjectRef, tuple[Node, ...]],
        actor: str,
        session_id: str,
        timestamp: int,
    ) -> tuple[int, int, int]:
        added_total = 0
        removed_total = 0
        changed_total = 0
        for change in changes:
            before_counts = _node_counts(change.before)
            after_counts = _node_counts(change.after)
            removed = _node_difference(
                current_nodes[change.subject],
                before_counts,
                after_counts,
            )
            added = _node_difference(change.after, after_counts, before_counts)
            if not removed and not added:
                continue

            self._remove_editor_nodes(connection, change.subject, removed)
            for node in added:
                self._insert_editor_node(connection, node, timestamp)
            added_total += len(added)
            removed_total += len(removed)
            changed_total += 1
            self._insert_audit(
                connection,
                actor,
                "editor.subject.apply",
                change.subject,
                {
                    "session_id": session_id,
                    "added": [self._node_details(node) for node in added],
                    "removed": [self._node_details(node) for node in removed],
                },
                timestamp,
            )
        return added_total, removed_total, changed_total

    @staticmethod
    def _remove_editor_nodes(
        connection: sqlite3.Connection,
        subject: SubjectRef,
        nodes: tuple[Node, ...],
    ) -> None:
        for node in nodes:
            if node.id is None:
                raise RuntimeError("An editor session referenced an unpersisted node")
            cursor = connection.execute(
                "DELETE FROM nodes WHERE id = ? AND subject_type = ? AND subject_id = ?",
                (node.id, subject.type.value, subject.identifier),
            )
            if cursor.rowcount != 1:
                raise RevisionConflictError(
                    f"Editor subject {subject.type.value}:{subject.identifier} changed during apply"
                )

    def _apply_editor_tracks(
        self,
        connection: sqlite3.Connection,
        changes: tuple[EditorTrackChange, ...],
        actor: str,
        session_id: str,
        timestamp: int,
    ) -> int:
        changed_total = 0
        for change in changes:
            if change.before == change.after:
                continue
            connection.execute("DELETE FROM track_groups WHERE track_name = ?", (change.name,))
            self._insert_track_groups(connection, change.name, change.after)
            connection.execute(
                "UPDATE tracks SET updated_at = ? WHERE name = ?",
                (timestamp, change.name),
            )
            changed_total += 1
            self._insert_audit(
                connection,
                actor,
                "editor.track.apply",
                ("track", change.name),
                {
                    "session_id": session_id,
                    "before": list(change.before),
                    "after": list(change.after),
                },
                timestamp,
            )
        return changed_total

    def nodes_for(self, subject: SubjectRef, *, include_expired: bool = True) -> tuple[Node, ...]:
        connection = self._require_connection()
        query = "SELECT * FROM nodes WHERE subject_type = ? AND subject_id = ?"
        params: list[object] = [subject.type.value, subject.identifier]
        if not include_expired:
            query += " AND (expires_at IS NULL OR expires_at > ?)"
            params.append(int(time.time()))
        query += " ORDER BY id"
        with self._lock:
            rows = connection.execute(query, params).fetchall()
        return tuple(self._row_to_node(row) for row in rows)

    def load_snapshot(self, user: SubjectRef, default_group: str) -> PermissionSnapshot:
        if user.type is not SubjectType.USER:
            raise ValueError("Permission snapshots require a user subject")
        connection = self._require_connection()
        with self._lock:
            group_rows = connection.execute(
                "SELECT name, display_name, weight FROM permission_groups"
            ).fetchall()
            node_rows = connection.execute(
                """
                SELECT * FROM nodes
                WHERE subject_type = 'group' OR (subject_type = 'user' AND subject_id = ?)
                ORDER BY id
                """,
                (user.identifier,),
            ).fetchall()
        groups = {row["name"]: self._row_to_group(row) for row in group_rows}
        nodes: dict[SubjectRef, list[Node]] = {}
        for row in node_rows:
            node = self._row_to_node(row)
            nodes.setdefault(node.subject, []).append(node)
        return PermissionSnapshot(
            user=user,
            groups=groups,
            nodes={subject: tuple(values) for subject, values in nodes.items()},
            default_group=normalize_group_name(default_group),
        )

    def delete_expired(self, timestamp: int) -> ExpiredNodes:
        connection = self._require_connection()
        with self._lock, connection:
            rows = connection.execute(
                """
                SELECT DISTINCT subject_type, subject_id
                FROM nodes WHERE expires_at IS NOT NULL AND expires_at <= ?
                """,
                (int(timestamp),),
            ).fetchall()
            cursor = connection.execute(
                "DELETE FROM nodes WHERE expires_at IS NOT NULL AND expires_at <= ?",
                (int(timestamp),),
            )
            count = cursor.rowcount
            subjects = frozenset(
                SubjectRef(SubjectType(row["subject_type"]), row["subject_id"]) for row in rows
            )
            if count:
                self._insert_audit(
                    connection,
                    "system",
                    "node.expire",
                    None,
                    {"count": count, "subjects": len(subjects)},
                    int(timestamp),
                )
        if count:
            self._revision += 1
        return ExpiredNodes(count=count, subjects=subjects)

    def recent_audit(self, limit: int = 20) -> tuple[dict[str, object], ...]:
        connection = self._require_connection()
        bounded = max(1, min(200, int(limit)))
        with self._lock:
            rows = connection.execute(
                """
                SELECT id, created_at, actor, action, subject_type, subject_id, details_json
                FROM audit_log ORDER BY id DESC LIMIT ?
                """,
                (bounded,),
            ).fetchall()
        return tuple(
            {
                "id": int(row["id"]),
                "created_at": int(row["created_at"]),
                "actor": row["actor"],
                "action": row["action"],
                "subject_type": row["subject_type"],
                "subject_id": row["subject_id"],
                "details": json.loads(row["details_json"]),
            }
            for row in rows
        )

    def record_audit(self, actor: str, action: str, details: dict[str, Any]) -> None:
        connection = self._require_connection()
        with self._lock, connection:
            self._insert_audit(connection, actor, action, None, details, int(time.time()))

    def _replacement_query(self, node: Node, contexts_json: str) -> tuple[str, list[object]]:
        query = (
            "DELETE FROM nodes WHERE subject_type = ? AND subject_id = ? AND node_type = ? "
            "AND node_key = ? AND contexts_json = ?"
        )
        params: list[object] = [
            node.subject.type.value,
            node.subject.identifier,
            node.type.value,
            node.key,
            contexts_json,
        ]
        query += " AND expires_at IS NOT NULL" if node.temporary else " AND expires_at IS NULL"
        if node.type in {NodeType.PREFIX, NodeType.SUFFIX}:
            query += " AND priority = ?"
            params.append(node.priority)
        return query, params

    @staticmethod
    def _insert_editor_node(
        connection: sqlite3.Connection,
        node: Node,
        timestamp: int,
    ) -> None:
        connection.execute(
            """
            INSERT INTO nodes(
                subject_type, subject_id, node_type, node_key, node_value,
                contexts_json, expires_at, priority, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                node.subject.type.value,
                node.subject.identifier,
                node.type.value,
                node.key,
                node.value,
                node.contexts.to_json(),
                node.expires_at,
                node.priority,
                int(timestamp),
            ),
        )

    @staticmethod
    def _insert_track_groups(
        connection: sqlite3.Connection,
        track_name: str,
        groups: tuple[str, ...],
    ) -> None:
        connection.executemany(
            "INSERT INTO track_groups(track_name, group_name, position) VALUES (?, ?, ?)",
            ((track_name, group, position) for position, group in enumerate(groups)),
        )

    @staticmethod
    def _load_track_groups(connection: sqlite3.Connection, track_name: str) -> tuple[str, ...]:
        rows = connection.execute(
            "SELECT group_name FROM track_groups WHERE track_name = ? ORDER BY position",
            (track_name,),
        ).fetchall()
        return tuple(row["group_name"] for row in rows)

    @staticmethod
    def _insert_audit(
        connection: sqlite3.Connection,
        actor: str,
        action: str,
        subject: SubjectRef | tuple[str, str] | None,
        details: dict[str, Any],
        timestamp: int,
    ) -> None:
        connection.execute(
            """
            INSERT INTO audit_log(
                created_at, actor, action, subject_type, subject_id, details_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                int(timestamp),
                str(actor)[:128],
                str(action)[:128],
                subject.type.value
                if isinstance(subject, SubjectRef)
                else subject[0]
                if subject
                else None,
                subject.identifier
                if isinstance(subject, SubjectRef)
                else subject[1]
                if subject
                else None,
                json.dumps(details, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
            ),
        )

    @staticmethod
    def _node_details(node: Node) -> dict[str, Any]:
        return {
            "id": node.id,
            "node_type": node.type.value,
            "key": node.key,
            "value": node.value,
            "contexts": list(node.contexts.pairs),
            "expires_at": node.expires_at,
            "priority": node.priority,
        }

    @staticmethod
    def _row_to_user(row: sqlite3.Row) -> UserRecord:
        return UserRecord(unique_id=row["unique_id"], xuid=row["xuid"], last_name=row["last_name"])

    @staticmethod
    def _row_to_profile(row: sqlite3.Row) -> PlayerProfile:
        return PlayerProfile(
            unique_id=row["unique_id"],
            last_name=row["last_name"],
            xuid=row["xuid"],
            locale=row["locale"],
            device_os=row["device_os"],
            game_version=row["game_version"],
            game_mode=row["game_mode"],
            ping_ms=row["ping_ms"],
            total_exp=row["total_exp"],
            exp_level=row["exp_level"],
            skin_id=row["skin_id"],
            skin_hash=row["skin_hash"],
            skin_width=row["skin_width"],
            skin_height=row["skin_height"],
            skin_rgba=row["skin_rgba"],
            cape_id=row["cape_id"],
            first_seen_at=int(row["first_seen_at"] or 0),
            last_seen_at=int(row["last_seen_at"] or 0),
            last_joined_at=row["last_joined_at"],
            last_quit_at=row["last_quit_at"],
            skin_updated_at=row["skin_updated_at"],
            online=bool(row["online"]),
        )

    @staticmethod
    def _row_to_group(row: sqlite3.Row) -> GroupRecord:
        return GroupRecord(name=row["name"], display_name=row["display_name"], weight=row["weight"])

    @staticmethod
    def _row_to_node(row: sqlite3.Row) -> Node:
        return Node(
            id=int(row["id"]),
            subject=SubjectRef(SubjectType(row["subject_type"]), row["subject_id"]),
            type=NodeType(row["node_type"]),
            key=row["node_key"],
            value=row["node_value"],
            contexts=ContextSet.from_json(row["contexts_json"]),
            expires_at=row["expires_at"],
            priority=int(row["priority"]),
            created_at=int(row["created_at"]),
        )

    def _require_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("StonePerms repository is not initialized")
        return self._connection


def _node_fingerprint(node: Node) -> tuple[object, ...]:
    return (
        node.type.value,
        node.key,
        node.value,
        node.contexts.pairs,
        node.expires_at,
        node.priority,
    )


def _node_counts(nodes: tuple[Node, ...]) -> dict[tuple[object, ...], int]:
    counts: dict[tuple[object, ...], int] = {}
    for node in nodes:
        fingerprint = _node_fingerprint(node)
        counts[fingerprint] = counts.get(fingerprint, 0) + 1
    return counts


def _node_difference(
    nodes: tuple[Node, ...],
    own_counts: dict[tuple[object, ...], int],
    other_counts: dict[tuple[object, ...], int],
) -> tuple[Node, ...]:
    remaining = {
        fingerprint: max(count - other_counts.get(fingerprint, 0), 0)
        for fingerprint, count in own_counts.items()
    }
    selected: list[Node] = []
    for node in nodes:
        fingerprint = _node_fingerprint(node)
        if remaining.get(fingerprint, 0):
            selected.append(node)
            remaining[fingerprint] -= 1
    return tuple(selected)
