from __future__ import annotations

import os
import sqlite3
import tempfile
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from endstone_stoneperms.application.manager import StonePermsManager
from endstone_stoneperms.application.ports import (
    EditorSubjectChange,
    EditorTrackChange,
    RevisionConflictError,
)
from endstone_stoneperms.domain.model import (
    ContextSet,
    GroupRecord,
    Node,
    NodeType,
    PlayerProfile,
    SubjectRef,
    TrackRecord,
    UserRecord,
)
from endstone_stoneperms.infrastructure.repository import create_repository
from endstone_stoneperms.infrastructure.sqlite_repository import (
    MIGRATION_1,
    SqlitePermissionRepository,
)
from endstone_stoneperms.plugin import StonePermsPlugin
from endstone_stoneperms.settings import MySqlSettings, load_settings


class RepositoryContract:
    def test_global_and_server_permissions_and_tags(self) -> None:
        manager = StonePermsManager(self.repository)
        manager.register_user("player", "Player", "123")
        subject = SubjectRef.user("player")
        test1 = ContextSet.parse("server=test1")
        test2 = ContextSet.parse("server=test2")
        manager.create_group("vip", actor="test")
        manager.add_parent(subject, "vip", actor="test")
        manager.set_permission(subject, "fly.use", True, actor="test")
        manager.set_permission(subject, "kill.use", True, actor="test", contexts=test1)
        manager.set_permission(subject, "fly.use", False, actor="test", contexts=test2)
        manager.set_prefix(SubjectRef.group("vip"), "§6[VIP]", 10, actor="test")
        manager.set_prefix(subject, "§a[Test1]", 20, actor="test", contexts=test1)
        manager.set_suffix(subject, " ★", 10, actor="test")
        manager.set_meta(subject, "rank", "VIP", actor="test")
        self.assertTrue(manager.check_permission(subject, "fly.use", test1).value)
        self.assertFalse(manager.check_permission(subject, "fly.use", test2).value)
        self.assertTrue(manager.check_permission(subject, "kill.use", test1).value)
        self.assertIsNone(manager.check_permission(subject, "kill.use", test2).value)
        self.assertEqual(manager.resolve_prefix(subject, test1).value, "§a[Test1]")
        self.assertEqual(manager.resolve_prefix(subject, test2).value, "§6[VIP]")
        self.assertEqual(manager.resolve_suffix(subject, test2).value, " ★")
        self.assertEqual(manager.resolve_meta(subject, "rank", test2).value, "VIP")
        manager.unset_permission(subject, "kill.use", actor="test", contexts=test1)
        self.assertIsNone(manager.check_permission(subject, "kill.use", test1).value)

    def test_tracks_and_group_deletion(self) -> None:
        repository = self.repository
        for name in ("one", "two", "three"):
            self.assertTrue(repository.create_group(GroupRecord(name, name), "test"))
            self.assertFalse(repository.create_group(GroupRecord(name, name), "test"))
        self.assertTrue(repository.create_track(TrackRecord("staff", ("one", "two", "three")), "test"))
        self.assertFalse(repository.create_track(TrackRecord("staff"), "test"))
        repository.set_track_groups("staff", ("three", "one", "two"), "test", "test", {})
        repository.set_track_groups("staff", ("three", "one", "two"), "test", "test", {})
        self.assertTrue(repository.rename_track("staff", "team", "test"))
        self.assertEqual(repository.list_tracks(), (TrackRecord("team", ("three", "one", "two")),))
        repository.set_group_weight("two", 0, "test")
        self.assertTrue(repository.delete_group("one", "test"))
        self.assertEqual(repository.get_track("team").groups, ("three", "two"))
        self.assertTrue(repository.delete_track("team", "test"))
        self.assertFalse(repository.delete_track("team", "test"))
        self.assertTrue(repository.recent_audit())

    def test_profile_updates_preserve_skin_and_first_seen(self) -> None:
        profile = PlayerProfile(
            "player", "Player", "123", first_seen_at=10, last_seen_at=20, online=True,
            skin_hash="old", skin_rgba=b"\x00\xff\x80", skin_width=1, skin_height=1,
            skin_updated_at=20, ping_ms=50,
        )
        self.repository.upsert_player_profile(profile)
        self.repository.upsert_player_profile(replace(
            profile, first_seen_at=30, last_seen_at=30, skin_hash="new", skin_rgba=b"\xff\x00",
            skin_updated_at=30,
        ))
        stored = self.repository.upsert_player_profile(PlayerProfile(
            "player", "Renamed", last_seen_at=40, online=False,
        ))
        self.assertEqual(stored.first_seen_at, 10)
        self.assertEqual(stored.skin_hash, "new")
        self.assertEqual(stored.skin_rgba, b"\xff\x00")
        self.assertEqual(stored.skin_updated_at, 30)
        self.assertEqual(stored.ping_ms, 50)
        self.assertEqual(stored.xuid, "123")
        self.assertFalse(stored.online)
        self.assertEqual(self.repository.find_user("rEnAmEd").unique_id, "player")
        self.assertEqual(self.repository.get_player_profile("123"), stored)
        self.assertEqual(self.repository.list_player_profiles(), (stored,))

    def test_expiry_and_parent_replacement(self) -> None:
        repository = self.repository
        subject = SubjectRef.user("player")
        now = int(time.time())
        node = repository.save_node(Node(
            subject, NodeType.PERMISSION, "fly.use", "true", expires_at=now - 1,
        ), "test", "test")
        self.assertEqual(repository.nodes_for(subject, include_expired=False), ())
        self.assertIsNotNone(node.id)
        self.assertEqual(repository.delete_expired(now).count, 1)
        self.assertEqual(repository.delete_expired(now).count, 0)
        parent = repository.replace_parent_node(
            None, Node(subject, NodeType.PARENT, "default", "true"), "test", "test", {},
        )
        self.assertEqual(repository.nodes_for(subject), (parent,))
        repository.replace_parent_node(parent, None, "test", "test", {})
        self.assertEqual(repository.nodes_for(subject), ())

    def test_editor_atomicity_and_revision_conflicts(self) -> None:
        repository = self.repository
        subject = SubjectRef.group("default")
        node = Node(subject, NodeType.PERMISSION, "fly.use", "true")
        revision = repository.revision
        result = repository.apply_editor_batch(
            revision, (EditorSubjectChange(subject, (), (node,)),), (), "test", "session",
        )
        self.assertTrue(result.changed)
        self.assertGreater(result.revision, revision)
        with self.assertRaises(RevisionConflictError):
            repository.apply_editor_batch(revision, (), (), "test", "session")
        before = repository.nodes_for(subject)
        repository.create_track(TrackRecord("staff", ("default",)), "test")
        with self.assertRaises(self.integrity_error):
            repository.apply_editor_batch(
                repository.revision,
                (EditorSubjectChange(subject, before, ()),),
                (EditorTrackChange("staff", ("default",), ("missing",)),),
                "test", "session",
            )
        self.assertEqual(repository.nodes_for(subject), before)
        self.assertEqual(repository.get_track("staff").groups, ("default",))


class SqliteRepositoryTests(RepositoryContract, unittest.TestCase):
    integrity_error = sqlite3.IntegrityError

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "stoneperms.db"
        self.repository = SqlitePermissionRepository(self.path)
        self.repository.initialize("default")
        self.addCleanup(self.repository.close)

    def test_existing_database_survives_reopening(self) -> None:
        self.repository.upsert_user(UserRecord("player", "Player", "123"))
        node = self.repository.save_node(Node(
            SubjectRef.user("player"), NodeType.PREFIX, "prefix", "§6[VIP]",
            contexts=ContextSet.parse("server=test1"),
        ), "test", "test")
        self.repository.create_track(TrackRecord("staff", ("default",)), "test")
        self.repository.close()
        self.repository.initialize("default")
        self.assertEqual(self.repository.find_user("123").unique_id, "player")
        self.assertEqual(self.repository.nodes_for(node.subject), (node,))
        self.assertEqual(self.repository.get_track("staff").groups, ("default",))
        self.assertFalse(self.repository.refresh())

    def test_schema_one_upgrade_preserves_data(self) -> None:
        path = self.path.with_name("old.db")
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.executescript(MIGRATION_1)
            connection.execute("INSERT INTO schema_migrations VALUES (1, 10)")
            connection.execute("INSERT INTO users VALUES ('player', '123', 'Player', 10, 20)")
        repository = SqlitePermissionRepository(path)
        self.addCleanup(repository.close)
        repository.initialize("default")
        self.assertEqual(repository.get_player_profile("123").first_seen_at, 10)
        self.assertEqual(repository.get_player_profile("123").last_seen_at, 20)


class StorageSettingsTests(unittest.TestCase):
    def test_legacy_configuration_uses_sqlite(self) -> None:
        settings = load_settings({"storage": {"database": "existing.db"}})
        self.assertEqual(settings.database_file, "existing.db")
        self.assertEqual(settings.storage_backend, "sqlite")
        self.assertEqual(settings.server_context, "global")
        with patch.dict("sys.modules", {"pymysql": None}):
            self.assertIsInstance(create_repository(settings, Path(".")), SqlitePermissionRepository)

    def test_mysql_requires_explicit_stable_server_id(self) -> None:
        with self.assertRaisesRegex(ValueError, "storage.server_id"):
            load_settings({"storage": {"backend": "mysql"}})
        settings = load_settings({"storage": {
            "backend": "mysql", "server_id": "Test1", "mysql": {"password": " secret "},
        }})
        self.assertEqual(settings.storage_server_id, "test1")
        self.assertEqual(settings.mysql.password, " secret ")
        self.assertNotIn("secret", repr(settings))

    def test_unknown_backend_fails_without_fallback(self) -> None:
        with self.assertRaises(ValueError):
            load_settings({"storage": {"backend": "unknown"}})

    def test_failed_attachment_sync_is_retried(self) -> None:
        plugin = SimpleNamespace(
            _repository=SimpleNamespace(refresh=Mock(side_effect=[True, False])),
            _attachments=SimpleNamespace(refresh_all=Mock(side_effect=[RuntimeError("offline"), 1])),
            _storage_sync_pending=False,
            logger=SimpleNamespace(warning=Mock()),
        )
        StonePermsPlugin._sync_storage(plugin)
        self.assertTrue(plugin._storage_sync_pending)
        StonePermsPlugin._sync_storage(plugin)
        self.assertFalse(plugin._storage_sync_pending)
        self.assertEqual(plugin._attachments.refresh_all.call_count, 2)


@unittest.skipUnless(os.environ.get("STONEPERMS_TEST_MYSQL_HOST"), "MySQL test server is not configured")
class MySqlRepositoryTests(RepositoryContract, unittest.TestCase):
    def setUp(self) -> None:
        import pymysql

        from endstone_stoneperms.infrastructure.mysql_repository import MySqlPermissionRepository

        self.integrity_error = pymysql.err.IntegrityError
        self.database = f"stoneperms_test_{uuid.uuid4().hex}"
        self.settings = MySqlSettings(
            host=os.environ["STONEPERMS_TEST_MYSQL_HOST"],
            port=int(os.environ.get("STONEPERMS_TEST_MYSQL_PORT", "3306")),
            username=os.environ.get("STONEPERMS_TEST_MYSQL_USER", "root"),
            password=os.environ.get("STONEPERMS_TEST_MYSQL_PASSWORD", ""),
            database=self.database,
        )
        admin = pymysql.connect(
            host=self.settings.host, port=self.settings.port,
            user=self.settings.username, password=self.settings.password, autocommit=True,
        )
        self.addCleanup(admin.close)
        with admin.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE `{self.database}`")
        self.addCleanup(self._drop_database, admin)
        self.repository = MySqlPermissionRepository(self.settings, "test1")
        self.addCleanup(self.repository.close)
        self.repository.initialize("default")
        self.other = MySqlPermissionRepository(self.settings, "test2")
        self.addCleanup(self.other.close)
        self.other.initialize("default")

    def _drop_database(self, admin: object) -> None:
        with admin.cursor() as cursor:
            cursor.execute(f"DROP DATABASE `{self.database}`")

    def test_shared_permissions_tags_and_separate_profiles(self) -> None:
        first = StonePermsManager(self.repository)
        second = StonePermsManager(self.other)
        profile = PlayerProfile("player", "Player", "123", online=True, ping_ms=20)
        first.observe_player(profile)
        second.observe_player(replace(profile, ping_ms=80, game_mode="creative"))
        subject = SubjectRef.user("player")
        test1 = ContextSet.parse("server=test1")
        test2 = ContextSet.parse("server=test2")
        self.assertIsNone(second.check_permission(subject, "fly.use", test2).value)
        first.set_permission(subject, "fly.use", True, actor="test")
        first.set_permission(subject, "kill.use", True, actor="test", contexts=test1)
        first.create_group("vip", actor="test")
        first.add_parent(subject, "vip", actor="test")
        first.set_prefix(SubjectRef.group("vip"), "§6[VIP]", 10, actor="test")
        first.create_track("staff", actor="test")
        first.append_track_group("staff", "vip", actor="test")
        self.assertTrue(self.other.refresh())
        self.assertTrue(second.check_permission(subject, "fly.use", test2).value)
        self.assertIsNone(second.check_permission(subject, "kill.use", test2).value)
        self.assertEqual(second.resolve_prefix(subject, test2).value, "§6[VIP]")
        self.assertEqual(second.get_track("staff").groups, ("vip",))
        self.assertFalse(self.other.refresh())
        first.observe_player(replace(profile, online=False))
        self.assertTrue(second.get_player_profile("player").online)
        self.assertEqual(second.get_player_profile("player").ping_ms, 80)
        self.repository.close()
        self.repository.initialize("default")
        self.assertTrue(second.get_player_profile("player").online)
        self.assertFalse(first.get_player_profile("player").online)

    def test_stale_editor_is_rejected_without_polling(self) -> None:
        revision = self.other.revision
        self.repository.create_group(GroupRecord("vip", "VIP"), "test")
        with self.assertRaises(RevisionConflictError):
            self.other.apply_editor_batch(revision, (), (), "test", "session")

    def test_duplicate_xuid_does_not_overwrite_another_player(self) -> None:
        self.repository.upsert_user(UserRecord("one", "One", "123"))
        with self.assertRaises(ValueError):
            self.repository.upsert_user(UserRecord("two", "Two", "123"))
        self.assertEqual(self.repository.find_user("123").last_name, "One")
        self.assertIsNone(self.repository.find_user("two"))

    def test_lost_idle_connection_is_reopened(self) -> None:
        self.repository._connection._connection.close()
        self.repository.create_group(GroupRecord("vip", "VIP"), "test")
        self.assertIsNotNone(self.other.get_group("vip"))

    def test_database_revision_is_rolled_back_with_failed_batch(self) -> None:
        self.repository.create_track(TrackRecord("staff", ("default",)), "test")
        self.other.refresh()
        revision = self.other.revision
        subject = SubjectRef.group("default")
        with patch.object(self.repository, "_insert_audit", side_effect=RuntimeError("audit failed")):
            with self.assertRaises(RuntimeError):
                self.repository.save_node(Node(
                    subject, NodeType.PERMISSION, "fly.use", "true",
                ), "test", "test")
        self.assertFalse(self.other.refresh())
        self.assertEqual(self.other.revision, revision)
        self.assertEqual(self.other.nodes_for(subject), ())

    def test_concurrent_replacements_keep_one_node_and_shared_revision(self) -> None:
        subject = SubjectRef.group("default")
        revision = self.repository.revision

        def write_nodes(repository: object, value: str) -> None:
            for _ in range(10):
                repository.save_node(Node(
                    subject, NodeType.PERMISSION, "fly.use", value,
                ), "test", "test")

        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(write_nodes, self.repository, "true")
            second = executor.submit(write_nodes, self.other, "false")
            first.result(timeout=30)
            second.result(timeout=30)
        self.repository.refresh()
        self.other.refresh()
        self.assertEqual(self.repository.revision, revision + 20)
        self.assertEqual(self.other.revision, revision + 20)
        self.assertEqual(len(self.repository.nodes_for(subject)), 1)
        self.assertEqual(self.repository.nodes_for(subject), self.other.nodes_for(subject))
