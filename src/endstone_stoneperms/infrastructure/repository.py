from pathlib import Path

from ..application.ports import PermissionRepository
from ..settings import StonePermsSettings
from .sqlite_repository import SqlitePermissionRepository


def create_repository(settings: StonePermsSettings, data_folder: Path) -> PermissionRepository:
    if settings.storage_backend == "mysql":
        try:
            from .mysql_repository import MySqlPermissionRepository
        except ModuleNotFoundError as exc:
            if exc.name != "pymysql":
                raise
            raise RuntimeError(
                "MySQL storage requires PyMySQL; install endstone-stoneperms[mysql] "
                "in Endstone's Python environment"
            ) from exc

        return MySqlPermissionRepository(settings.mysql, settings.storage_server_id)
    return SqlitePermissionRepository(data_folder / settings.database_file)
