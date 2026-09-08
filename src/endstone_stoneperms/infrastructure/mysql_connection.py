from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from types import TracebackType
from typing import Any

import pymysql
from pymysql.constants import CLIENT
from pymysql.cursors import DictCursor

from ..settings import MySqlSettings


@dataclass(slots=True)
class MySqlResult:
    rowcount: int
    lastrowid: int | None
    rows: tuple[dict[str, Any], ...] = ()

    def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> tuple[dict[str, Any], ...]:
        return self.rows


class MySqlConnection:
    def __init__(self, settings: MySqlSettings, on_revision: Callable[[int], None]) -> None:
        self._settings = settings
        self._on_revision = on_revision
        self._transaction = False
        self._transaction_revision = 0
        self._connection = self._connect()

    def _connect(self) -> pymysql.Connection:
        settings = self._settings
        return pymysql.connect(
            host=settings.host,
            port=settings.port,
            user=settings.username,
            password=settings.password,
            database=settings.database,
            charset="utf8mb4",
            cursorclass=DictCursor,
            autocommit=True,
            client_flag=CLIENT.FOUND_ROWS,
            connect_timeout=settings.connect_timeout,
            read_timeout=settings.read_timeout,
            write_timeout=settings.read_timeout,
            ssl_ca=settings.ssl_ca or None,
            ssl_verify_cert=bool(settings.ssl_ca),
            ssl_verify_identity=bool(settings.ssl_ca),
        )

    def _ensure_connected(self) -> None:
        if self._transaction:
            return
        try:
            self._connection.ping(reconnect=False)
        except pymysql.err.Error:
            if self._connection.open:
                self._connection.close()
            self._connection = self._connect()

    def execute(self, query: str, parameters: Sequence[object] = ()) -> MySqlResult:
        self._ensure_connected()
        sql = query.replace("%", "%%").replace("?", "%s")
        ignore_duplicate = sql.lstrip().startswith("INSERT IGNORE INTO")
        if ignore_duplicate:
            sql = sql.replace("INSERT IGNORE INTO", "INSERT INTO", 1)
        with self._connection.cursor() as cursor:
            try:
                cursor.execute(sql, tuple(parameters))
            except pymysql.err.IntegrityError as exc:
                if ignore_duplicate and exc.args[0] == 1062:
                    return MySqlResult(0, None)
                raise
            rows = tuple(cursor.fetchall()) if cursor.description else ()
            return MySqlResult(cursor.rowcount, cursor.lastrowid, rows)

    def executemany(self, query: str, parameters: Iterable[Sequence[object]]) -> None:
        for values in parameters:
            self.execute(query, values)

    def __enter__(self) -> MySqlConnection:
        if self._transaction:
            raise RuntimeError("Nested MySQL transactions are not supported")
        self._ensure_connected()
        self._connection.begin()
        self._transaction = True
        try:
            row = self.execute("SELECT revision FROM storage_state WHERE id = 1 FOR UPDATE").fetchone()
            self._transaction_revision = int(row["revision"])
            self._on_revision(self._transaction_revision)
        except BaseException:
            self._transaction = False
            self._connection.rollback()
            raise
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            if exception_type is None:
                self._connection.commit()
            else:
                self._connection.rollback()
                self._on_revision(self._transaction_revision)
        except BaseException:
            self._on_revision(self._transaction_revision)
            raise
        finally:
            self._transaction = False

    def close(self) -> None:
        if self._connection.open:
            self._connection.close()
