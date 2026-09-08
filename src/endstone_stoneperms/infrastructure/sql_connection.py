from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from types import TracebackType
from typing import Any, Protocol


class SqlResult(Protocol):
    @property
    def rowcount(self) -> int:
        pass

    @property
    def lastrowid(self) -> int | None:
        pass

    def fetchone(self) -> Mapping[str, Any] | None:
        pass

    def fetchall(self) -> Sequence[Mapping[str, Any]]:
        pass


class SqlConnection(Protocol):
    def execute(self, query: str, parameters: Sequence[object] = ()) -> SqlResult:
        pass

    def executemany(self, query: str, parameters: Iterable[Sequence[object]]) -> object:
        pass

    def __enter__(self) -> SqlConnection:
        pass

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        pass

    def close(self) -> None:
        pass
