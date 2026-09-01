from __future__ import annotations

import base64
from collections.abc import Callable, Iterable

from endstone import OfflinePlayer, Player
from endstone.plugin import Service

from ..application.editor import PROTOCOL_VERSION, StonePermsEditorProtocol
from ..application.manager import StonePermsManager
from ..domain.model import (
    ContextSet,
    MetaDecision,
    Node,
    PermissionDecision,
    PlayerProfile,
    SubjectRef,
    TrackMoveResult,
    TrackRecord,
)
from ..domain.validation import normalize_group_name
from ..version import VERSION
from .configuration import StonePermsConfiguration
from .contexts import EndstoneContextCalculator
from .display import StonePermsDisplay
from .identity import player_subject
from .profiles import render_player_face_png

SERVICE_NAME = "stoneperms.permissions.v1"
SubjectLike = Player | OfflinePlayer | str


def _serialize_web_profile_summary(profile: PlayerProfile) -> dict[str, object]:
    return {
        "id": profile.unique_id,
        "name": profile.last_name,
        "xuid": profile.xuid,
        "online": profile.online,
        "lastSeenAt": profile.last_seen_at,
        "deviceOs": profile.device_os,
        "gameVersion": profile.game_version,
        "skinHash": profile.skin_hash,
    }


def _serialize_web_profile(profile: PlayerProfile) -> dict[str, object]:
    return {
        "locale": profile.locale,
        "deviceOs": profile.device_os,
        "gameVersion": profile.game_version,
        "gameMode": profile.game_mode,
        "pingMs": profile.ping_ms,
        "totalExp": profile.total_exp,
        "expLevel": profile.exp_level,
        "skinId": profile.skin_id,
        "skinHash": profile.skin_hash,
        "skinWidth": profile.skin_width,
        "skinHeight": profile.skin_height,
        "capeId": profile.cape_id,
        "firstSeenAt": profile.first_seen_at,
        "lastSeenAt": profile.last_seen_at,
        "lastJoinedAt": profile.last_joined_at,
        "lastQuitAt": profile.last_quit_at,
        "skinUpdatedAt": profile.skin_updated_at,
        "online": profile.online,
    }


class StonePermsService(Service):
    api_version = 1

    def __init__(
        self,
        manager: StonePermsManager,
        contexts: EndstoneContextCalculator,
        on_user_change: Callable[[str], object] | None = None,
        *,
        editor: StonePermsEditorProtocol | None = None,
        on_editor_change: Callable[[], object] | None = None,
        display: StonePermsDisplay | None = None,
        configuration: StonePermsConfiguration | None = None,
    ) -> None:
        super().__init__()
        self._manager = manager
        self._contexts = contexts
        self._on_user_change = on_user_change
        self._editor = editor or StonePermsEditorProtocol(
            manager,
            product_version=VERSION,
        )
        self._on_editor_change = on_editor_change
        self._display = display
        self._configuration = configuration

    @property
    def editor_protocol_version(self) -> int:
        return PROTOCOL_VERSION

    def create_editor_session(
        self,
        *,
        actor: str,
        users: Iterable[str] = (),
        include_groups: bool = True,
        include_tracks: bool = True,
    ) -> dict[str, object]:
        return self._editor.create_session(
            actor,
            users=tuple(users),
            include_groups=include_groups,
            include_tracks=include_tracks,
        )

    def apply_editor_changes(
        self,
        payload: str | dict[str, object],
        *,
        actor: str,
    ) -> dict[str, object]:
        result = self._editor.apply_changes(actor, payload)
        if result["changed"] and self._on_editor_change is not None:
            self._on_editor_change()
        return result

    def get_web_directory(self) -> dict[str, object]:
        return {
            "revision": self._manager.repository.revision,
            "defaultGroup": self._manager.default_group,
            "groups": [
                {"name": group.name, "displayName": group.display_name, "weight": group.weight}
                for group in self._manager.list_groups()
            ],
            "tracks": [
                {"name": track.name, "groups": list(track.groups)}
                for track in self._manager.list_tracks()
            ],
            "users": [
                _serialize_web_profile_summary(profile)
                for profile in self._manager.list_player_profiles()
            ],
        }

    def get_web_player(self, identifier: str) -> dict[str, object]:
        user = self._manager.find_user(identifier)
        subject = SubjectRef.user(user.unique_id)
        profile = self._manager.get_player_profile(user.unique_id)
        return {
            "user": (
                _serialize_web_profile_summary(profile)
                if profile is not None
                else {"id": user.unique_id, "name": user.last_name, "xuid": user.xuid}
            ),
            "profile": _serialize_web_profile(profile) if profile is not None else None,
            "nodes": [_serialize_web_node(node) for node in self._manager.nodes_for(subject)],
            "effectiveGroups": list(self._manager.effective_groups(subject)),
            "primaryGroup": self._manager.primary_group(subject),
            "prefix": self._manager.resolve_prefix(subject).value,
            "suffix": self._manager.resolve_suffix(subject).value,
            "meta": self._manager.meta_map(subject),
            "tracks": {name: list(groups) for name, groups in self._manager.user_tracks(subject).items()},
        }

    def get_web_player_avatar(self, identifier: str) -> dict[str, object]:
        user = self._manager.find_user(identifier)
        profile = self._manager.get_player_profile(user.unique_id)
        png = render_player_face_png(profile) if profile is not None else None
        return {
            "name": profile.last_name if profile is not None else user.last_name,
            "xuid": profile.xuid if profile is not None else user.xuid,
            "skinHash": profile.skin_hash if profile is not None else None,
            "skinId": profile.skin_id if profile is not None else None,
            "mimeType": "image/png" if png is not None else None,
            "data": base64.b64encode(png).decode("ascii") if png is not None else None,
        }

    def create_web_group(
        self, name: str, display_name: str | None, weight: int, *, actor: str
    ) -> dict[str, object]:
        if not self._manager.create_group(
            name, display_name=display_name, weight=weight, actor=actor
        ):
            raise ValueError(f"Group {name!r} already exists")
        normalized = normalize_group_name(name)
        group = next(group for group in self._manager.list_groups() if group.name == normalized)
        return {"name": group.name, "displayName": group.display_name, "weight": group.weight}

    def set_web_group_weight(self, name: str, weight: int, *, actor: str) -> dict[str, object]:
        self._manager.set_group_weight(name, weight, actor=actor)
        normalized = normalize_group_name(name)
        group = next(group for group in self._manager.list_groups() if group.name == normalized)
        return {"name": group.name, "displayName": group.display_name, "weight": group.weight}

    def delete_web_group(self, name: str, *, actor: str) -> dict[str, object]:
        normalized = normalize_group_name(name)
        deleted = self._manager.delete_group(normalized, actor=actor)
        if deleted and self._on_editor_change is not None:
            self._on_editor_change()
        return {"name": normalized, "deleted": deleted}

    def create_web_track(self, name: str, *, actor: str) -> dict[str, object]:
        if not self._manager.create_track(name, actor=actor):
            raise ValueError(f"Track {name!r} already exists")
        return _serialize_web_track(self._manager.get_track(name))

    def rename_web_track(self, name: str, new_name: str, *, actor: str) -> dict[str, object]:
        return _serialize_web_track(self._manager.rename_track(name, new_name, actor=actor))

    def clone_web_track(self, name: str, clone_name: str, *, actor: str) -> dict[str, object]:
        return _serialize_web_track(self._manager.clone_track(name, clone_name, actor=actor))

    def delete_web_track(self, name: str, *, actor: str) -> dict[str, object]:
        return {"name": name, "deleted": self._manager.delete_track(name, actor=actor)}

    def move_web_player(
        self, identifier: str, track: str, direction: str, *, actor: str
    ) -> dict[str, object]:
        if direction == "promote":
            result = self.promote(identifier, track, actor=actor)
        elif direction == "demote":
            result = self.demote(identifier, track, actor=actor)
        else:
            raise ValueError("Track direction must be promote or demote")
        return {
            "action": result.action.value,
            "status": result.status.value,
            "track": result.track,
            "groupFrom": result.group_from,
            "groupTo": result.group_to,
            "changed": result.changed,
        }

    def get_web_audit(self, limit: int) -> dict[str, object]:
        return {"entries": list(self._manager.recent_audit(limit))}

    def get_web_display_settings(self) -> dict[str, object]:
        if self._display is None:
            raise RuntimeError("StonePerms display service is not available")
        return self._display.get_web_settings()

    def update_web_display_settings(
        self,
        *,
        chat_enabled: bool,
        chat_format: str,
        nametag_enabled: bool,
        nametag_format: str,
    ) -> dict[str, object]:
        if self._display is None:
            raise RuntimeError("StonePerms display service is not available")
        return self._display.update_settings(
            chat_enabled=chat_enabled,
            chat_format=chat_format,
            nametag_enabled=nametag_enabled,
            nametag_format=nametag_format,
        )

    def get_web_plugin_settings(self) -> dict[str, object]:
        if self._configuration is None:
            raise RuntimeError("StonePerms configuration service is not available")
        return self._configuration.get_web_settings()

    def update_web_plugin_settings(
        self,
        *,
        default_group: str,
        server_context: str,
        include_device_os_context: bool,
        include_locale_context: bool,
        expiry_check_seconds: int,
        catalog_refresh_seconds: int,
        debug: bool,
        actor: str,
    ) -> dict[str, object]:
        if self._configuration is None:
            raise RuntimeError("StonePerms configuration service is not available")
        return self._configuration.update_settings(
            default_group=default_group,
            server_context=server_context,
            include_device_os_context=include_device_os_context,
            include_locale_context=include_locale_context,
            expiry_check_seconds=expiry_check_seconds,
            catalog_refresh_seconds=catalog_refresh_seconds,
            debug=debug,
            actor=actor,
        )

    def check_permission(
        self,
        subject: SubjectLike,
        permission: str,
        contexts: ContextSet | None = None,
    ) -> PermissionDecision:
        reference, active = self._resolve_subject(subject, contexts)
        return self._manager.check_permission(reference, permission, active)

    def has_permission(
        self,
        subject: SubjectLike,
        permission: str,
        contexts: ContextSet | None = None,
    ) -> bool:
        return self.check_permission(subject, permission, contexts).value is True

    def get_groups(
        self, subject: SubjectLike, contexts: ContextSet | None = None
    ) -> tuple[str, ...]:
        reference, active = self._resolve_subject(subject, contexts)
        return self._manager.effective_groups(reference, active)

    def get_primary_group(self, subject: SubjectLike, contexts: ContextSet | None = None) -> str:
        reference, active = self._resolve_subject(subject, contexts)
        return self._manager.primary_group(reference, active)

    def get_prefix(self, subject: SubjectLike, contexts: ContextSet | None = None) -> str | None:
        return self.get_prefix_decision(subject, contexts).value

    def get_prefix_decision(
        self, subject: SubjectLike, contexts: ContextSet | None = None
    ) -> MetaDecision:
        reference, active = self._resolve_subject(subject, contexts)
        return self._manager.resolve_prefix(reference, active)

    def get_suffix(self, subject: SubjectLike, contexts: ContextSet | None = None) -> str | None:
        return self.get_suffix_decision(subject, contexts).value

    def get_suffix_decision(
        self, subject: SubjectLike, contexts: ContextSet | None = None
    ) -> MetaDecision:
        reference, active = self._resolve_subject(subject, contexts)
        return self._manager.resolve_suffix(reference, active)

    def get_meta(
        self,
        subject: SubjectLike,
        key: str,
        contexts: ContextSet | None = None,
    ) -> str | None:
        return self.get_meta_decision(subject, key, contexts).value

    def get_meta_decision(
        self,
        subject: SubjectLike,
        key: str,
        contexts: ContextSet | None = None,
    ) -> MetaDecision:
        reference, active = self._resolve_subject(subject, contexts)
        return self._manager.resolve_meta(reference, key, active)

    def get_meta_map(
        self,
        subject: SubjectLike,
        contexts: ContextSet | None = None,
    ) -> dict[str, str]:
        reference, active = self._resolve_subject(subject, contexts)
        return self._manager.meta_map(reference, active)

    def get_track(self, name: str) -> TrackRecord:
        return self._manager.get_track(name)

    def get_tracks(self) -> tuple[TrackRecord, ...]:
        return self._manager.list_tracks()

    def get_user_tracks(
        self,
        subject: SubjectLike,
        contexts: ContextSet | None = None,
    ) -> dict[str, tuple[str, ...]]:
        reference, _ = self._resolve_subject(subject, contexts or ContextSet())
        return self._manager.user_tracks(reference, contexts)

    def promote(
        self,
        subject: SubjectLike,
        track: str,
        *,
        actor: str,
        contexts: ContextSet | None = None,
        add_to_first: bool = True,
    ) -> TrackMoveResult:
        reference, active = self._resolve_subject(subject, contexts)
        result = self._manager.promote(
            reference,
            track,
            actor=actor,
            contexts=active,
            add_to_first=add_to_first,
        )
        self._notify_user_change(reference, result.changed)
        return result

    def demote(
        self,
        subject: SubjectLike,
        track: str,
        *,
        actor: str,
        contexts: ContextSet | None = None,
        remove_from_first: bool = True,
    ) -> TrackMoveResult:
        reference, active = self._resolve_subject(subject, contexts)
        result = self._manager.demote(
            reference,
            track,
            actor=actor,
            contexts=active,
            remove_from_first=remove_from_first,
        )
        self._notify_user_change(reference, result.changed)
        return result

    def register_context_provider(
        self,
        owner: str,
        key: str,
        provider: Callable[[Player], str | Iterable[str] | None],
    ) -> None:
        self._contexts.register_provider(owner, key, provider)

    def unregister_context_providers(self, owner: str) -> None:
        self._contexts.unregister_owner(owner)

    def _notify_user_change(self, subject: SubjectRef, changed: bool) -> None:
        if changed and self._on_user_change is not None:
            self._on_user_change(subject.identifier)

    def _resolve_subject(
        self, subject: SubjectLike, contexts: ContextSet | None
    ) -> tuple[SubjectRef, ContextSet]:
        if isinstance(subject, Player):
            return player_subject(subject), contexts or self._contexts.calculate(subject)
        if isinstance(subject, str):
            return self._manager.user_subject(subject), contexts or ContextSet()
        unique_id = getattr(subject, "unique_id", None)
        if unique_id is not None:
            return self._manager.user_subject(str(unique_id)), contexts or ContextSet()
        name = getattr(subject, "name", None)
        if name:
            return self._manager.user_subject(str(name)), contexts or ContextSet()
        raise LookupError("Placeholder subject has no known StonePerms identity")


def _serialize_web_node(node: Node) -> dict[str, object]:
    return {
        "type": node.type.value,
        "key": node.key,
        "value": node.value,
        "contexts": [{"key": key, "value": value} for key, value in node.contexts.pairs],
        "expiresAt": node.expires_at,
        "priority": node.priority,
    }


def _serialize_web_track(track: TrackRecord) -> dict[str, object]:
    return {"name": track.name, "groups": list(track.groups)}
