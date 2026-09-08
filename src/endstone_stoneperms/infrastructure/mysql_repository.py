from __future__ import annotations

import hashlib
import re
import time

from ..domain.model import PermissionSnapshot, SubjectRef
from ..domain.validation import normalize_context_value, normalize_group_name
from ..settings import MySqlSettings
from .mysql_connection import MySqlConnection
from .mysql_schema import SCHEMA, SCHEMA_VERSION, USER_SCHEMA
from .sql_connection import SqlConnection
from .sql_repository import SqlPermissionRepository


class MySqlPermissionRepository(SqlPermissionRepository):
    _insert_ignore = "INSERT IGNORE"

    def __init__(self, settings: MySqlSettings, server_id: str) -> None:
        super().__init__()
        self._settings = settings
        self._server_id = normalize_context_value(server_id)
        digest = hashlib.sha256(self._server_id.encode("utf-8")).hexdigest()[:24]
        self._users_table = f"users_{digest}"
        self._last_refreshed_revision = 0

    def initialize(self, default_group: str) -> None:
        group_name = normalize_group_name(default_group)
        connection = MySqlConnection(self._settings, self._set_revision)
        self._connection = connection
        digest = hashlib.sha256(self._settings.database.encode("utf-8")).hexdigest()[:24]
        lock_name = f"stoneperms.schema.{digest}"
        locked = False
        try:
            row = connection.execute("SELECT GET_LOCK(?, 10) AS acquired", (lock_name,)).fetchone()
            if row["acquired"] != 1:
                raise RuntimeError("Could not acquire the StonePerms schema migration lock")
            locked = True
            connection.execute(SCHEMA[0])
            row = connection.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()
            current = int(row["version"] or 0)
            if current > SCHEMA_VERSION:
                raise RuntimeError(
                    f"StonePerms MySQL schema {current} is newer than supported {SCHEMA_VERSION}"
                )
            for statement in SCHEMA[1:]:
                connection.execute(statement)
            connection.execute(USER_SCHEMA.format(users_table=self._users_table))
            connection.execute("INSERT IGNORE INTO storage_state(id, revision) VALUES (1, 0)")
            with connection:
                connection.execute(
                    "INSERT IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (SCHEMA_VERSION, int(time.time())),
                )
                connection.execute(
                    "INSERT IGNORE INTO storage_servers(server_id, users_table) VALUES (?, ?)",
                    (self._server_id, self._users_table),
                )
                connection.execute(f"UPDATE {self._users_table} SET online = 0 WHERE online <> 0")
                timestamp = int(time.time())
                result = connection.execute(
                    """
                    INSERT IGNORE INTO permission_groups(
                        name, display_name, weight, created_at, updated_at
                    ) VALUES (?, ?, 0, ?, ?)
                    """,
                    (group_name, group_name, timestamp, timestamp),
                )
                if result.rowcount:
                    self._advance_revision()
            self._last_refreshed_revision = self._revision
        except BaseException:
            self.close()
            raise
        finally:
            if locked and self._connection is not None:
                connection.execute("SELECT RELEASE_LOCK(?)", (lock_name,))

    def refresh(self) -> bool:
        with self._lock:
            row = self._require_connection().execute(
                "SELECT revision FROM storage_state WHERE id = 1"
            ).fetchone()
            self._revision = int(row["revision"])
            changed = self._revision != self._last_refreshed_revision
            self._last_refreshed_revision = self._revision
            return changed

    def load_snapshot(self, user: SubjectRef, default_group: str) -> PermissionSnapshot:
        with self._lock, self._require_connection():
            return super().load_snapshot(user, default_group)

    def _advance_revision(self) -> None:
        self._require_connection().execute("UPDATE storage_state SET revision = revision + 1 WHERE id = 1")
        self._revision += 1

    def _set_revision(self, revision: int) -> None:
        self._revision = revision

    def _user_upsert(self) -> str:
        return _mysql_upsert(super()._user_upsert())

    def _validate_identity(self, connection: SqlConnection, unique_id: str, xuid: str | None) -> None:
        if xuid is None:
            return
        row = connection.execute(
            f"SELECT unique_id FROM {self._users_table} WHERE xuid = ?", (xuid,)
        ).fetchone()
        if row is not None and row["unique_id"] != unique_id:
            raise ValueError("This XUID is already associated with another player UUID")

    def _profile_upsert(self) -> str:
        query = super()._profile_upsert()
        assignment = f"skin_hash = COALESCE(excluded.skin_hash, {self._users_table}.skin_hash),"
        query = query.replace(assignment, "")
        query = query.replace("online = excluded.online", f"online = excluded.online, {assignment[:-1]}")
        return _mysql_upsert(query)


def _mysql_upsert(query: str) -> str:
    query = query.replace("ON CONFLICT(unique_id) DO UPDATE SET", "ON DUPLICATE KEY UPDATE")
    return re.sub(r"excluded\.([a-z_]+)", r"VALUES(\1)", query)
