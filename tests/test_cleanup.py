from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from endstone_stoneperms.platform.attachments import AttachmentManager
from endstone_stoneperms.platform.papi import StonePermsPapiBridge
from endstone_stoneperms.platform.web import StonePermsWebConnector
from endstone_stoneperms.plugin import StonePermsPlugin


def _plugin() -> SimpleNamespace:
    return SimpleNamespace(logger=SimpleNamespace(warning=Mock()))


class AttachmentManagerCleanupTests(unittest.TestCase):
    def test_remove_player_clears_tracking_after_success(self) -> None:
        plugin = _plugin()
        manager = AttachmentManager(plugin, object(), object())
        attachment = SimpleNamespace(remove=Mock(return_value=True))
        manager._attachments["player-1"] = attachment
        manager._applied["player-1"] = {"stoneperms.use": True}

        manager.remove_player(SimpleNamespace(unique_id="player-1"))

        self.assertEqual(manager._attachments, {})
        self.assertEqual(manager._applied, {})
        attachment.remove.assert_called_once_with()
        plugin.logger.warning.assert_not_called()

    def test_close_clears_tracking_and_reports_remove_failures(self) -> None:
        plugin = _plugin()
        manager = AttachmentManager(plugin, object(), object())
        failed = SimpleNamespace(remove=Mock(side_effect=RuntimeError("attachment is stale")))
        refused = SimpleNamespace(remove=Mock(return_value=False))
        manager._attachments.update({"player-1": failed, "player-2": refused})
        manager._applied.update({"player-1": {}, "player-2": {}})
        manager._registered_permissions = frozenset({"stoneperms.use"})

        manager.close()

        self.assertEqual(manager._attachments, {})
        self.assertEqual(manager._applied, {})
        self.assertEqual(manager.permission_catalog, frozenset())
        self.assertEqual(plugin.logger.warning.call_count, 2)


class PapiCleanupTests(unittest.TestCase):
    def test_close_clears_registration_after_success(self) -> None:
        plugin = _plugin()
        bridge = StonePermsPapiBridge(plugin, object())
        api = SimpleNamespace(active=True, unregister_expansions=Mock())
        bridge._api = api
        bridge._mode = "modern"

        bridge.close()

        self.assertIsNone(bridge._api)
        self.assertIsNone(bridge._mode)
        api.unregister_expansions.assert_called_once_with(plugin)
        plugin.logger.warning.assert_not_called()

    def test_close_clears_registration_and_reports_failure(self) -> None:
        plugin = _plugin()
        bridge = StonePermsPapiBridge(plugin, object())
        api = SimpleNamespace(
            active=True,
            unregister_expansions=Mock(side_effect=RuntimeError("registry is unavailable")),
        )
        bridge._api = api
        bridge._mode = "modern"

        bridge.close()

        self.assertIsNone(bridge._api)
        self.assertIsNone(bridge._mode)
        plugin.logger.warning.assert_called_once()


class PluginCleanupTests(unittest.TestCase):
    def test_disable_continues_cleanup_after_service_unregister_failure(self) -> None:
        components = {
            "_web": SimpleNamespace(shutdown=Mock()),
            "_forms": SimpleNamespace(close=Mock()),
            "_editor": SimpleNamespace(close=Mock()),
            "_papi": SimpleNamespace(close=Mock()),
            "_attachments": SimpleNamespace(close=Mock()),
            "_display": SimpleNamespace(close=Mock()),
            "_repository": SimpleNamespace(close=Mock()),
        }
        service_manager = SimpleNamespace(
            unregister_all=Mock(side_effect=RuntimeError("registry is unavailable"))
        )
        plugin = SimpleNamespace(
            **components,
            _commands=object(),
            _service=object(),
            _configuration=object(),
            _contexts=object(),
            _manager=object(),
            _settings=object(),
            server=SimpleNamespace(service_manager=service_manager),
            logger=SimpleNamespace(warning=Mock(), info=Mock()),
        )

        StonePermsPlugin.on_disable(plugin)

        for component in components.values():
            cleanup = getattr(component, "shutdown", None) or component.close
            cleanup.assert_called_once_with()
        plugin.logger.warning.assert_called_once()
        plugin.logger.info.assert_called_once_with("StonePerms disabled")
        self.assertIsNone(plugin._repository)
        self.assertIsNone(plugin._attachments)
        self.assertIsNone(plugin._web)


class WebCleanupTests(unittest.TestCase):
    @staticmethod
    def _connector(plugin: SimpleNamespace, connection: object) -> StonePermsWebConnector:
        connector = StonePermsWebConnector.__new__(StonePermsWebConnector)
        connector._plugin = plugin
        connector._state_lock = threading.RLock()
        connector._stop = threading.Event()
        connector._thread = None
        connector._socket = connection
        connector._connected = True
        connector._ready = True
        return connector

    def test_close_clears_connection_after_success(self) -> None:
        plugin = _plugin()
        connection = SimpleNamespace(close=Mock())
        connector = self._connector(plugin, connection)

        connector.close()

        self.assertIsNone(connector._socket)
        self.assertFalse(connector._connected)
        self.assertFalse(connector._ready)
        connection.close.assert_called_once_with()
        plugin.logger.warning.assert_not_called()

    def test_close_clears_connection_and_reports_failure(self) -> None:
        plugin = _plugin()
        connection = SimpleNamespace(close=Mock(side_effect=OSError("socket is closed")))
        connector = self._connector(plugin, connection)

        connector.close()

        self.assertIsNone(connector._socket)
        self.assertFalse(connector._connected)
        self.assertFalse(connector._ready)
        plugin.logger.warning.assert_called_once()

    def test_reconnect_cleanup_can_suppress_shutdown_noise(self) -> None:
        plugin = _plugin()
        connection = SimpleNamespace(close=Mock(side_effect=OSError("socket is closed")))
        connector = self._connector(plugin, connection)

        connector._close_connection(connection, report_failure=False)

        plugin.logger.warning.assert_not_called()


if __name__ == "__main__":
    unittest.main()
