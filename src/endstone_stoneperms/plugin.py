from pathlib import Path
from typing import Any, ClassVar

from endstone.command import Command, CommandSender
from endstone.plugin import Plugin, ServicePriority

from .application.editor import StonePermsEditorProtocol
from .application.manager import StonePermsManager
from .application.ports import PermissionRepository
from .infrastructure.repository import create_repository
from .platform.attachments import AttachmentManager
from .platform.command_schema import COMMAND_USAGES, build_command_usages
from .platform.commands import StonePermsCommandRouter
from .platform.configuration import StonePermsConfiguration
from .platform.contexts import EndstoneContextCalculator
from .platform.display import StonePermsDisplay
from .platform.environment import log_startup_report
from .platform.forms import StonePermsFormController
from .platform.listener import StonePermsListener
from .platform.papi import StonePermsPapiBridge
from .platform.service import SERVICE_NAME, StonePermsService
from .platform.web import StonePermsWebConnector
from .settings import StonePermsSettings, load_settings
from .version import VERSION


class StonePermsPlugin(Plugin):
    api_version = "0.11"
    version = VERSION
    description = "Permissions, groups, tracks, prefixes, and suffixes for Endstone"
    authors: ClassVar[list[str]] = ["StonePerms contributors"]
    prefix = "StonePerms"
    soft_depend: ClassVar[list[str]] = ["papi"]

    commands: ClassVar[dict[str, Any]] = {
        "stoneperms": {
            "description": (
                "Inspect and manage players, groups, permissions, tracks, metadata, and web access"
            ),
            "aliases": ["sp", "perms"],
            "permissions": ["stoneperms.command.admin"],
            "usages": list(COMMAND_USAGES),
        }
    }
    permissions: ClassVar[dict[str, Any]] = {
        "stoneperms.command.admin": {
            "description": "Allows full StonePerms administration through commands and Bedrock Forms",
            "default": "op",
        }
    }

    def __init__(self) -> None:
        super().__init__()
        self._settings: StonePermsSettings | None = None
        self._repository: PermissionRepository | None = None
        self._manager: StonePermsManager | None = None
        self._contexts: EndstoneContextCalculator | None = None
        self._attachments: AttachmentManager | None = None
        self._display: StonePermsDisplay | None = None
        self._configuration: StonePermsConfiguration | None = None
        self._service: StonePermsService | None = None
        self._editor: StonePermsEditorProtocol | None = None
        self._commands: StonePermsCommandRouter | None = None
        self._forms: StonePermsFormController | None = None
        self._papi: StonePermsPapiBridge | None = None
        self._web: StonePermsWebConnector | None = None
        self._storage_sync_pending = False

    def on_load(self) -> None:
        repository: PermissionRepository | None = None
        try:
            self.save_default_config()
            settings = load_settings(self.config)
            repository = create_repository(settings, Path(self.data_folder))
            repository.initialize(settings.default_group)
            usages = build_command_usages(
                group_names=(group.name for group in repository.list_groups()),
                track_names=(track.name for track in repository.list_tracks()),
            )
            description = self._description
            if description is None:
                raise RuntimeError("plugin description is not available")
            command = next(
                (candidate for candidate in description.commands if candidate.name == "stoneperms"),
                None,
            )
            if command is None:
                raise RuntimeError("StonePerms command metadata is missing")
            command.usages = list(usages)
        except Exception as exc:
            self.logger.warning(
                f"Could not add stored names to command suggestions; using built-in actions: {exc}"
            )
        finally:
            if repository is not None:
                repository.close()

    def on_enable(self) -> None:
        self.save_default_config()
        settings = load_settings(self.config)
        repository = create_repository(settings, Path(self.data_folder))
        repository.initialize(settings.default_group)
        manager = StonePermsManager(repository, default_group=settings.default_group)
        contexts = EndstoneContextCalculator(settings)
        display = StonePermsDisplay(self, manager, contexts, settings.display)
        attachments = AttachmentManager(self, manager, contexts, display.apply_name_tag)
        configuration = StonePermsConfiguration(
            self,
            manager,
            contexts,
            settings,
            on_apply=self._apply_runtime_settings,
        )
        editor = StonePermsEditorProtocol(
            manager,
            known_permissions=lambda: tuple(attachments.permission_catalog),
            product_version=self.version,
        )
        service = StonePermsService(
            manager,
            contexts,
            attachments.apply_by_unique_id,
            editor=editor,
            on_editor_change=attachments.refresh_all,
            display=display,
            configuration=configuration,
        )
        forms = StonePermsFormController(self, manager, attachments)
        web = StonePermsWebConnector(
            self,
            service,
            enabled=settings.web_enabled,
            api_url=settings.web_api_url,
            server_id=settings.web_server_id,
            server_token=settings.web_server_token,
            server_name=settings.web_server_name,
        )

        self._settings = settings
        self._repository = repository
        self._manager = manager
        self._contexts = contexts
        self._attachments = attachments
        self._display = display
        self._configuration = configuration
        self._service = service
        self._editor = editor
        self._forms = forms
        self._web = web
        self._commands = StonePermsCommandRouter(self, manager, attachments, forms, web)
        self._papi = StonePermsPapiBridge(self, service)

        self.server.service_manager.register(SERVICE_NAME, service, self, ServicePriority.NORMAL)
        self.register_events(StonePermsListener(self, attachments, display, self._register_papi))
        attachments.refresh_permission_catalog()
        self._register_papi()
        self.server.scheduler.run_task(
            self,
            self._expire_nodes,
            delay=settings.expiry_check_ticks,
            period=settings.expiry_check_ticks,
        )
        web.start()
        if settings.storage_backend == "mysql":
            self.server.scheduler.run_task(
                self,
                self._sync_storage,
                delay=settings.storage_sync_ticks,
                period=settings.storage_sync_ticks,
            )
        self.server.scheduler.run_task(
            self,
            attachments.refresh_permission_catalog,
            delay=settings.catalog_check_ticks,
            period=settings.catalog_check_ticks,
        )
        log_startup_report(
            self,
            settings,
            repository=repository,
            papi_registered=self._papi.registered,
            web_status=web.status,
        )

    def on_disable(self) -> None:
        if self._web is not None:
            self._web.shutdown()
        if self._forms is not None:
            self._forms.close()
        if self._editor is not None:
            self._editor.close()
        if self._papi is not None:
            self._papi.close()
        try:
            self.server.service_manager.unregister_all(self)
        except (AttributeError, RuntimeError) as exc:
            self.logger.warning(f"Could not unregister StonePerms services: {exc}")
        if self._attachments is not None:
            self._attachments.close()
        if self._display is not None:
            self._display.close()
        if self._repository is not None:
            self._repository.close()
        self._commands = None
        self._forms = None
        self._papi = None
        self._web = None
        self._service = None
        self._editor = None
        self._attachments = None
        self._display = None
        self._configuration = None
        self._contexts = None
        self._manager = None
        self._repository = None
        self._settings = None
        self.logger.info("StonePerms disabled")

    def _register_papi(self) -> None:
        if self._papi is not None:
            self._papi.register()

    def _apply_runtime_settings(self, settings: StonePermsSettings) -> None:
        self._settings = settings
        if self._attachments is not None:
            self._attachments.refresh_all()

    def on_command(self, sender: CommandSender, command: Command, args: list[str]) -> bool:
        if command.name != "stoneperms" or self._commands is None:
            return False
        return self._commands.handle(sender, args)

    def _expire_nodes(self) -> None:
        if self._manager is None or self._attachments is None:
            return
        expired = self._manager.cleanup_expired()
        if expired.count:
            self._attachments.refresh_all()
            if self._settings is not None and self._settings.debug:
                self.logger.info(f"Expired {expired.count} temporary permission node(s)")

    def _sync_storage(self) -> None:
        if self._repository is None or self._attachments is None:
            return
        try:
            if self._repository.refresh():
                self._storage_sync_pending = True
            if self._storage_sync_pending:
                self._attachments.refresh_all()
                self._storage_sync_pending = False
        except Exception as exc:
            self.logger.warning(f"Could not synchronize permission storage: {exc}")
