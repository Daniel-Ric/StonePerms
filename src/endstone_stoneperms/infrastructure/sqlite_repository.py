from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from ..domain.validation import normalize_group_name
from .sql_repository import SqlPermissionRepository

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


class SqlitePermissionRepository(SqlPermissionRepository):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = Path(path)

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
