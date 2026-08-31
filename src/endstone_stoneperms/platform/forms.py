from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from typing import Any

from endstone import Player
from endstone.form import ActionForm, Dropdown, MessageForm, ModalForm, TextInput, Toggle
from endstone.plugin import Plugin

from ..application.manager import StonePermsManager
from ..domain.duration import parse_duration
from ..domain.model import (
    ContextSet,
    Node,
    NodeType,
    SubjectRef,
    SubjectType,
    TrackMoveAction,
    TrackMoveResult,
    TrackMoveStatus,
)
from .attachments import AttachmentManager
from .presentation import PREFIX as FORM_PREFIX
from .presentation import send_error

ADMIN_PERMISSION = "stoneperms.command.admin"
PAGE_SIZE = 15
NODE_PAGE_SIZE = 10


class StonePermsFormController:
    def __init__(
        self,
        plugin: Plugin,
        manager: StonePermsManager,
        attachments: AttachmentManager,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._plugin = plugin
        self._manager = manager
        self._attachments = attachments
        self._clock = clock
        self._enabled = True

    def close(self) -> None:
        self._enabled = False

    def open(self, player: Player) -> None:
        self._run(player, lambda: self._open_main(player))

    def _run(self, player: Player, callback: Callable[[], None]) -> None:
        try:
            if not self._enabled:
                raise ValueError("StonePerms is currently disabled")
            if not player.has_permission(ADMIN_PERMISSION):
                raise PermissionError(f"Missing permission {ADMIN_PERMISSION}")
            callback()
        except PermissionError as exc:
            send_error(
                player,
                _form_error_message(exc),
                f"Ask an operator for the {ADMIN_PERMISSION} permission.",
            )
        except (KeyError, LookupError, ValueError) as exc:
            send_error(
                player,
                _form_error_message(exc),
                "Review the selected values and try again.",
            )
        except Exception as exc:
            self._plugin.logger.error(f"StonePerms form callback failed: {exc}")
            send_error(
                player,
                "StonePerms could not complete that form action.",
                "Nothing was changed. Check the server log for the matching error.",
            )

    def _open_main(self, player: Player) -> None:
        groups = self._manager.list_groups()
        tracks = self._manager.list_tracks()
        form = ActionForm(
            title="§l§fStonePerms",
            content=(
                "§7Native permissions administration\n\n"
                f"§7Groups: §f{len(groups)}\n"
                f"§7Tracks: §f{len(tracks)}\n"
                f"§7Default group: §f{self._manager.default_group}"
            ),
        )
        form.add_button(
            "§fUsers\n§7Inspect and edit a player",
            on_click=lambda current: self._run(current, lambda: self._open_users(current)),
        )
        form.add_button(
            "§fGroups\n§7Weights, nodes and inheritance",
            on_click=lambda current: self._run(current, lambda: self._open_groups(current, 0)),
        )
        form.add_button(
            "§fTracks\n§7Promotion ladders",
            on_click=lambda current: self._run(current, lambda: self._open_tracks(current, 0)),
        )
        form.add_button(
            "§fAudit log\n§7Recent server-side changes",
            on_click=lambda current: self._run(current, lambda: self._open_audit(current)),
        )
        form.add_button("§8Close")
        player.send_form(form)

    def _open_users(self, player: Player) -> None:
        form = ActionForm(
            title="§l§fStonePerms §8- §fUsers",
            content=(
                "§7Choose an online player or find a previously seen player by name, UUID, or XUID."
            ),
        )
        form.add_button(
            "§aFind user...\n§7Name, UUID, or XUID",
            on_click=lambda current: self._run(current, lambda: self._open_user_lookup(current)),
        )
        online_players = sorted(
            tuple(self._plugin.server.online_players), key=lambda candidate: candidate.name.casefold()
        )
        for candidate in online_players:
            identifier = str(candidate.unique_id)
            label = candidate.name
            form.add_button(
                f"§f{label}\n§8Online",
                on_click=lambda current, user_id=identifier: self._run(
                    current, lambda: self._open_user(current, user_id)
                ),
            )
        form.add_button(
            "§8Back",
            on_click=lambda current: self._run(current, lambda: self._open_main(current)),
        )
        player.send_form(form)

    def _open_user_lookup(self, player: Player) -> None:
        form = ModalForm(
            title="StonePerms - Find user",
            controls=[
                TextInput(
                    label="Player name, UUID, or XUID",
                    placeholder="Steve",
                )
            ],
            submit_button="Open user",
            on_submit=lambda current, response: self._run(
                current, lambda: self._submit_user_lookup(current, response)
            ),
        )
        player.send_form(form)

    def _submit_user_lookup(self, player: Player, response: object) -> None:
        values = _decode_response(response, 1)
        identifier = _text(values[0], "User identifier", max_length=128)
        self._open_user(player, identifier)

    def _open_user(self, player: Player, identifier: str) -> None:
        user = self._manager.find_user(identifier)
        subject = SubjectRef.user(user.unique_id)
        groups = self._manager.effective_groups(subject)
        tracks = self._manager.user_tracks(subject)
        prefix = self._manager.resolve_prefix(subject).value or "<none>"
        suffix = self._manager.resolve_suffix(subject).value or "<none>"
        metadata = self._manager.meta_map(subject)
        track_text = ", ".join(
            f"{name}={'/'.join(positions)}" for name, positions in tracks.items()
        ) or "<none>"
        meta_text = ", ".join(f"{key}={value}" for key, value in metadata.items()) or "<none>"
        content = (
            f"§7UUID: §f{user.unique_id}\n"
            f"§7Primary: §f{self._manager.primary_group(subject)}\n"
            f"§7Groups: §f{', '.join(groups)}\n"
            f"§7Tracks: §f{track_text}\n"
            f"§7Prefix: §r{prefix}\n"
            f"§7Suffix: §r{suffix}\n"
            f"§7Meta: §f{meta_text}\n"
            f"§7Direct nodes: §f{len(self._manager.nodes_for(subject))}"
        )
        form = ActionForm(title=f"§l§fUser §8- §f{user.last_name}", content=content)
        self._add_subject_editor_buttons(form, subject)
        form.add_button(
            "§8Back to users",
            on_click=lambda current: self._run(current, lambda: self._open_users(current)),
        )
        player.send_form(form)

    def _open_groups(self, player: Player, page: int) -> None:
        groups = self._manager.list_groups()
        page, start, end, pages = _page_window(len(groups), page, PAGE_SIZE)
        form = ActionForm(
            title="§l§fStonePerms §8- §fGroups",
            content=f"§7Page {page + 1}/{pages} - {len(groups)} group(s)",
        )
        form.add_button(
            "§aCreate group...",
            on_click=lambda current: self._run(current, lambda: self._open_group_create(current)),
        )
        for group in groups[start:end]:
            form.add_button(
                f"§f{group.name}\n§7Weight {group.weight}",
                on_click=lambda current, name=group.name: self._run(
                    current, lambda: self._open_group(current, name)
                ),
            )
        self._add_page_buttons(form, page, pages, self._open_groups)
        form.add_button(
            "§8Back",
            on_click=lambda current: self._run(current, lambda: self._open_main(current)),
        )
        player.send_form(form)

    def _open_group_create(self, player: Player) -> None:
        form = ModalForm(
            title="StonePerms - Create group",
            controls=[
                TextInput(label="Group name", placeholder="moderator"),
                TextInput(label="Weight", placeholder="100", default_value="0"),
            ],
            submit_button="Create group",
            on_submit=lambda current, response: self._run(
                current, lambda: self._submit_group_create(current, response)
            ),
        )
        player.send_form(form)

    def _submit_group_create(self, player: Player, response: object) -> None:
        values = _decode_response(response, 2)
        name = _text(values[0], "Group name", max_length=64)
        weight = _integer(values[1], "Weight")
        if not self._manager.create_group(name, actor=player.name, weight=weight):
            raise ValueError(f"Group {name!r} already exists")
        self._attachments.refresh_all()
        player.send_message(f"{FORM_PREFIX} §7Created group §f{name} §7with weight §f{weight}§7.")
        self._open_group(player, name)

    def _open_group(self, player: Player, name: str) -> None:
        group = next(
            (candidate for candidate in self._manager.list_groups() if candidate.name == name), None
        )
        if group is None:
            raise ValueError(f"Unknown group {name!r}")
        subject = self._manager.group_subject(group.name)
        nodes = self._manager.nodes_for(subject)
        parents = [node.key for node in nodes if node.type is NodeType.PARENT]
        content = (
            f"§7Display name: §f{group.display_name}\n"
            f"§7Weight: §f{group.weight}\n"
            f"§7Parents: §f{', '.join(parents) or '<none>'}\n"
            f"§7Direct nodes: §f{len(nodes)}"
        )
        form = ActionForm(title=f"§l§fGroup §8- §f{group.name}", content=content)
        form.add_button(
            "§fSet weight...",
            on_click=lambda current, group_name=group.name: self._run(
                current, lambda: self._open_group_weight(current, group_name)
            ),
        )
        self._add_subject_editor_buttons(form, subject)
        form.add_button(
            "§8Back to groups",
            on_click=lambda current: self._run(current, lambda: self._open_groups(current, 0)),
        )
        player.send_form(form)

    def _open_group_weight(self, player: Player, name: str) -> None:
        group = next(
            (candidate for candidate in self._manager.list_groups() if candidate.name == name), None
        )
        if group is None:
            raise ValueError(f"Unknown group {name!r}")
        form = ModalForm(
            title=f"StonePerms - {group.name} weight",
            controls=[TextInput(label="Weight", default_value=str(group.weight))],
            submit_button="Save weight",
            on_submit=lambda current, response, group_name=group.name: self._run(
                current, lambda: self._submit_group_weight(current, group_name, response)
            ),
        )
        player.send_form(form)

    def _submit_group_weight(self, player: Player, name: str, response: object) -> None:
        values = _decode_response(response, 1)
        weight = _integer(values[0], "Weight")
        self._manager.set_group_weight(name, weight, actor=player.name)
        self._attachments.refresh_all()
        player.send_message(f"{FORM_PREFIX} §7Set §f{name} §7to weight §f{weight}§7.")
        self._open_group(player, name)

    def _add_subject_editor_buttons(self, form: ActionForm, subject: SubjectRef) -> None:
        form.add_button(
            "§aPermission node...",
            on_click=lambda current: self._run(
                current, lambda: self._open_permission_editor(current, subject)
            ),
        )
        form.add_button(
            "§fParent group...",
            on_click=lambda current: self._run(
                current, lambda: self._open_parent_editor(current, subject)
            ),
        )
        form.add_button(
            "§fMetadata...",
            on_click=lambda current: self._run(
                current, lambda: self._open_meta_editor(current, subject)
            ),
        )
        form.add_button(
            "§fPrefix...",
            on_click=lambda current: self._run(
                current, lambda: self._open_affix_editor(current, subject, NodeType.PREFIX)
            ),
        )
        form.add_button(
            "§fSuffix...",
            on_click=lambda current: self._run(
                current, lambda: self._open_affix_editor(current, subject, NodeType.SUFFIX)
            ),
        )
        if subject.type is SubjectType.USER:
            form.add_button(
                "§fPromote / demote...",
                on_click=lambda current: self._run(
                    current, lambda: self._open_user_track_editor(current, subject)
                ),
            )
        form.add_button(
            "§7Direct nodes",
            on_click=lambda current: self._run(
                current, lambda: self._open_nodes(current, subject, 0)
            ),
        )

    def _open_permission_editor(self, player: Player, subject: SubjectRef) -> None:
        actions = ("Set permanent", "Set temporary", "Unset permanent", "Unset temporary")
        form = ModalForm(
            title=f"StonePerms - {_subject_label(self._manager, subject)} permission",
            controls=[
                Dropdown(label="Action", options=list(actions), default_index=0),
                TextInput(label="Permission node", placeholder="example.command.use"),
                Toggle(label="Permission value (enabled = true)", default_value=True),
                TextInput(label="Duration (temporary only)", placeholder="30m"),
                TextInput(label="Contexts (optional key=value pairs)", placeholder="server=lobby"),
            ],
            submit_button="Apply change",
            on_submit=lambda current, response: self._run(
                current,
                lambda: self._submit_permission_editor(current, subject, actions, response),
            ),
        )
        player.send_form(form)

    def _submit_permission_editor(
        self,
        player: Player,
        subject: SubjectRef,
        actions: Sequence[str],
        response: object,
    ) -> None:
        values = _decode_response(response, 5)
        action = _choice(values[0], actions, "Permission action")
        permission = _text(values[1], "Permission node", max_length=255)
        value = _boolean(values[2], "Permission value")
        contexts = _contexts(values[4])
        if action in {"Set permanent", "Set temporary"}:
            expires_at = (
                self._expiry(values[3]) if action == "Set temporary" else None
            )
            self._manager.set_permission(
                subject,
                permission,
                value,
                actor=player.name,
                contexts=contexts,
                expires_at=expires_at,
            )
            message = f"Set {permission} to {str(value).lower()}"
        else:
            removed = self._manager.unset_permission(
                subject,
                permission,
                actor=player.name,
                contexts=contexts,
                temporary=action == "Unset temporary",
            )
            message = f"Removed {removed} permission node(s)"
        self._attachments.refresh_all()
        player.send_message(f"{FORM_PREFIX} §a{message}")
        self._open_subject(player, subject)

    def _open_parent_editor(self, player: Player, subject: SubjectRef) -> None:
        groups = tuple(group.name for group in self._manager.list_groups())
        if not groups:
            raise ValueError("No groups are available")
        actions = ("Add permanent", "Add temporary", "Remove permanent", "Remove temporary")
        form = ModalForm(
            title=f"StonePerms - {_subject_label(self._manager, subject)} parent",
            controls=[
                Dropdown(label="Action", options=list(actions), default_index=0),
                Dropdown(label="Parent group", options=list(groups), default_index=0),
                TextInput(label="Duration (temporary only)", placeholder="30m"),
                TextInput(label="Contexts (optional key=value pairs)", placeholder="server=lobby"),
            ],
            submit_button="Apply change",
            on_submit=lambda current, response: self._run(
                current,
                lambda: self._submit_parent_editor(current, subject, actions, groups, response),
            ),
        )
        player.send_form(form)

    def _submit_parent_editor(
        self,
        player: Player,
        subject: SubjectRef,
        actions: Sequence[str],
        groups: Sequence[str],
        response: object,
    ) -> None:
        values = _decode_response(response, 4)
        action = _choice(values[0], actions, "Parent action")
        parent = _choice(values[1], groups, "Parent group")
        contexts = _contexts(values[3])
        if action in {"Add permanent", "Add temporary"}:
            expires_at = self._expiry(values[2]) if action == "Add temporary" else None
            self._manager.add_parent(
                subject,
                parent,
                actor=player.name,
                contexts=contexts,
                expires_at=expires_at,
            )
            message = f"Added parent {parent}"
        else:
            removed = self._manager.remove_parent(
                subject,
                parent,
                actor=player.name,
                contexts=contexts,
                temporary=action == "Remove temporary",
            )
            message = f"Removed {removed} parent node(s)"
        self._attachments.refresh_all()
        player.send_message(f"{FORM_PREFIX} §a{message}")
        self._open_subject(player, subject)

    def _open_meta_editor(self, player: Player, subject: SubjectRef) -> None:
        actions = ("Set permanent", "Set temporary", "Unset permanent", "Unset temporary")
        form = ModalForm(
            title=f"StonePerms - {_subject_label(self._manager, subject)} metadata",
            controls=[
                Dropdown(label="Action", options=list(actions), default_index=0),
                TextInput(label="Metadata key", placeholder="display-name"),
                TextInput(label="Metadata value", placeholder="Example value"),
                TextInput(label="Duration (temporary only)", placeholder="30m"),
                TextInput(label="Contexts (optional key=value pairs)", placeholder="server=lobby"),
            ],
            submit_button="Apply change",
            on_submit=lambda current, response: self._run(
                current, lambda: self._submit_meta_editor(current, subject, actions, response)
            ),
        )
        player.send_form(form)

    def _submit_meta_editor(
        self,
        player: Player,
        subject: SubjectRef,
        actions: Sequence[str],
        response: object,
    ) -> None:
        values = _decode_response(response, 5)
        action = _choice(values[0], actions, "Metadata action")
        key = _text(values[1], "Metadata key", max_length=64)
        contexts = _contexts(values[4])
        if action in {"Set permanent", "Set temporary"}:
            value = _text(values[2], "Metadata value", max_length=256, strip=False)
            expires_at = self._expiry(values[3]) if action == "Set temporary" else None
            self._manager.set_meta(
                subject,
                key,
                value,
                actor=player.name,
                contexts=contexts,
                expires_at=expires_at,
            )
            message = f"Set metadata {key}"
        else:
            removed = self._manager.unset_meta(
                subject,
                key,
                actor=player.name,
                contexts=contexts,
                temporary=action == "Unset temporary",
            )
            message = f"Removed {removed} metadata node(s)"
        player.send_message(f"{FORM_PREFIX} §a{message}")
        self._open_subject(player, subject)

    def _open_affix_editor(
        self,
        player: Player,
        subject: SubjectRef,
        node_type: NodeType,
    ) -> None:
        actions = ("Set permanent", "Set temporary", "Unset permanent", "Unset temporary")
        form = ModalForm(
            title=(
                f"StonePerms - {_subject_label(self._manager, subject)} {node_type.value}"
            ),
            controls=[
                Dropdown(label="Action", options=list(actions), default_index=0),
                TextInput(label="Priority", placeholder="100", default_value="100"),
                TextInput(label=f"{node_type.value.title()} value", placeholder="§6[VIP] §r"),
                TextInput(label="Duration (temporary only)", placeholder="30m"),
                TextInput(label="Contexts (optional key=value pairs)", placeholder="server=lobby"),
            ],
            submit_button="Apply change",
            on_submit=lambda current, response: self._run(
                current,
                lambda: self._submit_affix_editor(
                    current, subject, node_type, actions, response
                ),
            ),
        )
        player.send_form(form)

    def _submit_affix_editor(
        self,
        player: Player,
        subject: SubjectRef,
        node_type: NodeType,
        actions: Sequence[str],
        response: object,
    ) -> None:
        values = _decode_response(response, 5)
        action = _choice(values[0], actions, f"{node_type.value.title()} action")
        priority = _integer(values[1], "Priority")
        contexts = _contexts(values[4])
        setter = self._manager.set_prefix if node_type is NodeType.PREFIX else self._manager.set_suffix
        unsetter = (
            self._manager.unset_prefix if node_type is NodeType.PREFIX else self._manager.unset_suffix
        )
        if action in {"Set permanent", "Set temporary"}:
            value = _text(
                values[2], f"{node_type.value.title()} value", max_length=256, strip=False
            )
            expires_at = self._expiry(values[3]) if action == "Set temporary" else None
            setter(
                subject,
                value,
                priority,
                actor=player.name,
                contexts=contexts,
                expires_at=expires_at,
            )
            message = f"Set {node_type.value} at priority {priority}"
        else:
            removed = unsetter(
                subject,
                priority,
                actor=player.name,
                contexts=contexts,
                temporary=action == "Unset temporary",
            )
            message = f"Removed {removed} {node_type.value} node(s)"
        player.send_message(f"{FORM_PREFIX} §a{message}")
        self._open_subject(player, subject)

    def _open_user_track_editor(self, player: Player, subject: SubjectRef) -> None:
        tracks = tuple(track.name for track in self._manager.list_tracks())
        if not tracks:
            raise ValueError("No tracks are available")
        actions = ("Promote", "Demote")
        form = ModalForm(
            title=f"StonePerms - {_subject_label(self._manager, subject)} track",
            controls=[
                Dropdown(label="Action", options=list(actions), default_index=0),
                Dropdown(label="Track", options=list(tracks), default_index=0),
                Toggle(label="Allow add/remove at the track boundary", default_value=True),
                TextInput(label="Contexts (optional key=value pairs)", placeholder="server=lobby"),
            ],
            submit_button="Apply movement",
            on_submit=lambda current, response: self._run(
                current,
                lambda: self._submit_user_track_editor(
                    current, subject, actions, tracks, response
                ),
            ),
        )
        player.send_form(form)

    def _submit_user_track_editor(
        self,
        player: Player,
        subject: SubjectRef,
        actions: Sequence[str],
        tracks: Sequence[str],
        response: object,
    ) -> None:
        values = _decode_response(response, 4)
        action = _choice(values[0], actions, "Track action")
        track = _choice(values[1], tracks, "Track")
        cross_boundary = _boolean(values[2], "Boundary option")
        contexts = _contexts(values[3])
        if action == "Promote":
            result = self._manager.promote(
                subject,
                track,
                actor=player.name,
                contexts=contexts,
                add_to_first=cross_boundary,
            )
        else:
            result = self._manager.demote(
                subject,
                track,
                actor=player.name,
                contexts=contexts,
                remove_from_first=cross_boundary,
            )
        _send_track_result(player, result)
        if result.changed:
            self._attachments.refresh_all()
        self._open_subject(player, subject)

    def _open_nodes(self, player: Player, subject: SubjectRef, page: int) -> None:
        nodes = self._manager.nodes_for(subject)
        page, start, end, pages = _page_window(len(nodes), page, NODE_PAGE_SIZE)
        rendered = "\n".join(_render_node(node, int(self._clock())) for node in nodes[start:end])
        form = ActionForm(
            title=f"§l§fNodes §8- §f{_subject_label(self._manager, subject)}",
            content=(
                f"§7Page {page + 1}/{pages} - {len(nodes)} direct node(s)\n\n"
                f"{rendered or '§8No direct nodes'}"
            ),
        )
        self._add_page_buttons(
            form,
            page,
            pages,
            lambda current, target_page: self._open_nodes(current, subject, target_page),
        )
        form.add_button(
            "§8Back",
            on_click=lambda current: self._run(
                current, lambda: self._open_subject(current, subject)
            ),
        )
        player.send_form(form)

    def _open_subject(self, player: Player, subject: SubjectRef) -> None:
        if subject.type is SubjectType.USER:
            self._open_user(player, subject.identifier)
        else:
            self._open_group(player, subject.identifier)

    def _open_tracks(self, player: Player, page: int) -> None:
        tracks = self._manager.list_tracks()
        page, start, end, pages = _page_window(len(tracks), page, PAGE_SIZE)
        form = ActionForm(
            title="§l§fStonePerms §8- §fTracks",
            content=f"§7Page {page + 1}/{pages} - {len(tracks)} track(s)",
        )
        form.add_button(
            "§aCreate track...",
            on_click=lambda current: self._run(current, lambda: self._open_track_create(current)),
        )
        for track in tracks[start:end]:
            form.add_button(
                f"§f{track.name}\n§7{len(track.groups)} group(s)",
                on_click=lambda current, name=track.name: self._run(
                    current, lambda: self._open_track(current, name)
                ),
            )
        self._add_page_buttons(form, page, pages, self._open_tracks)
        form.add_button(
            "§8Back",
            on_click=lambda current: self._run(current, lambda: self._open_main(current)),
        )
        player.send_form(form)

    def _open_track_create(self, player: Player) -> None:
        form = ModalForm(
            title="StonePerms - Create track",
            controls=[TextInput(label="Track name", placeholder="staff")],
            submit_button="Create track",
            on_submit=lambda current, response: self._run(
                current, lambda: self._submit_track_create(current, response)
            ),
        )
        player.send_form(form)

    def _submit_track_create(self, player: Player, response: object) -> None:
        values = _decode_response(response, 1)
        name = _text(values[0], "Track name", max_length=64)
        if not self._manager.create_track(name, actor=player.name):
            raise ValueError(f"Track {name!r} already exists")
        player.send_message(f"{FORM_PREFIX} §7Created track §f{name}§7.")
        self._open_track(player, name)

    def _open_track(self, player: Player, name: str) -> None:
        track = self._manager.get_track(name)
        ladder = " §8-> §f".join(track.groups) if track.groups else "§8empty"
        form = ActionForm(
            title=f"§l§fTrack §8- §f{track.name}",
            content=f"§7{len(track.groups)} group(s)\n\n§f{ladder}",
        )
        form.add_button(
            "§aAppend group...",
            on_click=lambda current, track_name=track.name: self._run(
                current, lambda: self._open_track_append(current, track_name)
            ),
        )
        form.add_button(
            "§aInsert group...",
            on_click=lambda current, track_name=track.name: self._run(
                current, lambda: self._open_track_insert(current, track_name)
            ),
        )
        form.add_button(
            "§fRemove group...",
            on_click=lambda current, track_name=track.name: self._run(
                current, lambda: self._open_track_remove(current, track_name)
            ),
        )
        form.add_button(
            "§fRename...",
            on_click=lambda current, track_name=track.name: self._run(
                current, lambda: self._open_track_text_action(current, track_name, "rename")
            ),
        )
        form.add_button(
            "§fClone...",
            on_click=lambda current, track_name=track.name: self._run(
                current, lambda: self._open_track_text_action(current, track_name, "clone")
            ),
        )
        form.add_button(
            "§cClear track...",
            on_click=lambda current, track_name=track.name: self._run(
                current,
                lambda: self._confirm_track_action(current, track_name, "clear"),
            ),
        )
        form.add_button(
            "§cDelete track...",
            on_click=lambda current, track_name=track.name: self._run(
                current,
                lambda: self._confirm_track_action(current, track_name, "delete"),
            ),
        )
        form.add_button(
            "§8Back to tracks",
            on_click=lambda current: self._run(current, lambda: self._open_tracks(current, 0)),
        )
        player.send_form(form)

    def _available_track_groups(self, track_name: str) -> tuple[str, ...]:
        track = self._manager.get_track(track_name)
        return tuple(
            group.name for group in self._manager.list_groups() if group.name not in track.groups
        )

    def _open_track_append(self, player: Player, track_name: str) -> None:
        groups = self._available_track_groups(track_name)
        if not groups:
            raise ValueError("Every group is already on this track")
        form = ModalForm(
            title=f"StonePerms - Append to {track_name}",
            controls=[Dropdown(label="Group", options=list(groups), default_index=0)],
            submit_button="Append group",
            on_submit=lambda current, response: self._run(
                current,
                lambda: self._submit_track_append(current, track_name, groups, response),
            ),
        )
        player.send_form(form)

    def _submit_track_append(
        self,
        player: Player,
        track_name: str,
        groups: Sequence[str],
        response: object,
    ) -> None:
        values = _decode_response(response, 1)
        group = _choice(values[0], groups, "Group")
        self._manager.append_track_group(track_name, group, actor=player.name)
        player.send_message(f"{FORM_PREFIX} §7Added §f{group} §7to the end of §f{track_name}§7.")
        self._open_track(player, track_name)

    def _open_track_insert(self, player: Player, track_name: str) -> None:
        track = self._manager.get_track(track_name)
        groups = self._available_track_groups(track.name)
        if not groups:
            raise ValueError("Every group is already on this track")
        positions = tuple(
            f"{index + 1} - before {group}" for index, group in enumerate(track.groups)
        ) + (f"{len(track.groups) + 1} - end",)
        form = ModalForm(
            title=f"StonePerms - Insert into {track.name}",
            controls=[
                Dropdown(label="Group", options=list(groups), default_index=0),
                Dropdown(label="Position", options=list(positions), default_index=0),
            ],
            submit_button="Insert group",
            on_submit=lambda current, response: self._run(
                current,
                lambda: self._submit_track_insert(
                    current, track.name, groups, positions, response
                ),
            ),
        )
        player.send_form(form)

    def _submit_track_insert(
        self,
        player: Player,
        track_name: str,
        groups: Sequence[str],
        positions: Sequence[str],
        response: object,
    ) -> None:
        values = _decode_response(response, 2)
        group = _choice(values[0], groups, "Group")
        position = _choice_index(values[1], len(positions), "Track position") + 1
        self._manager.insert_track_group(track_name, group, position, actor=player.name)
        player.send_message(
            f"{FORM_PREFIX} §7Inserted §f{group} §7at position §f{position} §7in §f"
            f"{track_name}§7."
        )
        self._open_track(player, track_name)

    def _open_track_remove(self, player: Player, track_name: str) -> None:
        track = self._manager.get_track(track_name)
        if not track.groups:
            raise ValueError("This track has no groups to remove")
        form = ModalForm(
            title=f"StonePerms - Remove from {track.name}",
            controls=[
                Dropdown(label="Group", options=list(track.groups), default_index=0)
            ],
            submit_button="Remove group",
            on_submit=lambda current, response: self._run(
                current,
                lambda: self._submit_track_remove(
                    current, track.name, track.groups, response
                ),
            ),
        )
        player.send_form(form)

    def _submit_track_remove(
        self,
        player: Player,
        track_name: str,
        groups: Sequence[str],
        response: object,
    ) -> None:
        values = _decode_response(response, 1)
        group = _choice(values[0], groups, "Group")
        self._manager.remove_track_group(track_name, group, actor=player.name)
        player.send_message(f"{FORM_PREFIX} §7Removed §f{group} §7from §f{track_name}§7.")
        self._open_track(player, track_name)

    def _open_track_text_action(self, player: Player, track_name: str, action: str) -> None:
        self._manager.get_track(track_name)
        if action not in {"rename", "clone"}:
            raise ValueError(f"Unsupported track action {action!r}")
        form = ModalForm(
            title=f"StonePerms - {action.title()} {track_name}",
            controls=[TextInput(label="New track name", placeholder=f"{track_name}-copy")],
            submit_button=action.title(),
            on_submit=lambda current, response: self._run(
                current,
                lambda: self._submit_track_text_action(
                    current, track_name, action, response
                ),
            ),
        )
        player.send_form(form)

    def _submit_track_text_action(
        self,
        player: Player,
        track_name: str,
        action: str,
        response: object,
    ) -> None:
        values = _decode_response(response, 1)
        new_name = _text(values[0], "New track name", max_length=64)
        if action == "rename":
            updated = self._manager.rename_track(track_name, new_name, actor=player.name)
            message = f"Renamed {track_name} to {updated.name}"
        else:
            updated = self._manager.clone_track(track_name, new_name, actor=player.name)
            message = f"Cloned {track_name} to {updated.name}"
        player.send_message(f"{FORM_PREFIX} §a{message}")
        self._open_track(player, updated.name)

    def _confirm_track_action(self, player: Player, track_name: str, action: str) -> None:
        track = self._manager.get_track(track_name)
        if action not in {"clear", "delete"}:
            raise ValueError(f"Unsupported track action {action!r}")
        form = MessageForm(
            title=f"StonePerms - Confirm {action}",
            content=(
                f"§cAre you sure you want to {action} track §f{track.name}§c?\n\n"
                "§7This changes only the track definition. Existing user parent nodes are not removed."
            ),
            button1=f"§cConfirm {action}",
            button2="§7Cancel",
            on_submit=lambda current, choice: self._run(
                current,
                lambda: self._submit_confirm_track_action(
                    current, track.name, action, choice
                ),
            ),
        )
        player.send_form(form)

    def _submit_confirm_track_action(
        self,
        player: Player,
        track_name: str,
        action: str,
        choice: int,
    ) -> None:
        if choice != 0:
            self._open_track(player, track_name)
            return
        if action == "clear":
            self._manager.clear_track(track_name, actor=player.name)
            player.send_message(f"{FORM_PREFIX} §7Cleared every group from §f{track_name}§7.")
            self._open_track(player, track_name)
        else:
            self._manager.delete_track(track_name, actor=player.name)
            player.send_message(f"{FORM_PREFIX} §7Deleted track §f{track_name}§7.")
            self._open_tracks(player, 0)

    def _open_audit(self, player: Player) -> None:
        entries = self._manager.recent_audit(20)
        lines: list[str] = []
        for entry in entries:
            subject = (
                f"{entry['subject_type']}:{entry['subject_id']}"
                if entry["subject_type"]
                else "system"
            )
            lines.append(
                f"§8#{entry['id']} §7{entry['actor']} §f{entry['action']} §8-> §7{subject}"
            )
        form = ActionForm(
            title="§l§fStonePerms §8- §fAudit",
            content="\n".join(lines) if lines else "§8No audit entries",
        )
        form.add_button(
            "§fRefresh",
            on_click=lambda current: self._run(current, lambda: self._open_audit(current)),
        )
        form.add_button(
            "§8Back",
            on_click=lambda current: self._run(current, lambda: self._open_main(current)),
        )
        player.send_form(form)

    def _add_page_buttons(
        self,
        form: ActionForm,
        page: int,
        pages: int,
        opener: Callable[[Player, int], None],
    ) -> None:
        if page > 0:
            form.add_button(
                "§7<- Previous page",
                on_click=lambda current: self._run(
                    current, lambda: opener(current, page - 1)
                ),
            )
        if page + 1 < pages:
            form.add_button(
                "§7Next page ->",
                on_click=lambda current: self._run(
                    current, lambda: opener(current, page + 1)
                ),
            )

    def _expiry(self, value: object) -> int:
        duration = _text(value, "Duration", max_length=32)
        return int(self._clock()) + parse_duration(duration)


def _decode_response(response: object, expected_length: int) -> list[Any]:
    if isinstance(response, str):
        try:
            decoded = json.loads(response)
        except json.JSONDecodeError as exc:
            raise ValueError("The Bedrock form returned invalid JSON") from exc
    elif isinstance(response, (list, tuple)):
        decoded = list(response)
    else:
        raise ValueError("The Bedrock form returned an unsupported response")
    if not isinstance(decoded, list) or len(decoded) != expected_length:
        raise ValueError(
            f"The Bedrock form returned {len(decoded) if isinstance(decoded, list) else 0} "
            f"value(s); expected {expected_length}"
        )
    return decoded


def _text(
    value: object,
    label: str,
    *,
    max_length: int,
    strip: bool = True,
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text")
    result = value.strip() if strip else value
    if not result.strip():
        raise ValueError(f"{label} is required")
    if len(result) > max_length:
        raise ValueError(f"{label} may contain at most {max_length} characters")
    return result


def _integer(value: object, label: str) -> int:
    text = _text(value, label, max_length=16)
    try:
        return int(text)
    except ValueError as exc:
        raise ValueError(f"{label} must be a whole number") from exc


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be true or false")
    return value


def _choice_index(value: object, size: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} selection is invalid")
    index = int(value)
    if index != value or index < 0 or index >= size:
        raise ValueError(f"{label} selection is out of range")
    return index


def _choice(value: object, options: Sequence[str], label: str) -> str:
    return options[_choice_index(value, len(options), label)]


def _contexts(value: object) -> ContextSet:
    if not isinstance(value, str):
        raise ValueError("Contexts must be text")
    if len(value) > 512:
        raise ValueError("Contexts may contain at most 512 characters")
    return ContextSet.parse(value.split())


def _page_window(total: int, page: int, page_size: int) -> tuple[int, int, int, int]:
    pages = max(1, (total + page_size - 1) // page_size)
    current = min(max(int(page), 0), pages - 1)
    start = current * page_size
    return current, start, min(start + page_size, total), pages


def _form_error_message(exc: Exception) -> str:
    message = str(exc).strip()
    if isinstance(exc, KeyError):
        message = message.strip("'\"")
    if not message:
        return "The requested value could not be found."
    if message[-1] not in ".!?":
        message += "."
    return message


def _subject_label(manager: StonePermsManager, subject: SubjectRef) -> str:
    if subject.type is SubjectType.USER:
        return manager.find_user(subject.identifier).last_name
    return subject.identifier


def _render_node(node: Node, now: int) -> str:
    context = " ".join(f"{key}={value}" for key, value in node.contexts.pairs)
    context_text = f" §8[{context}]" if context else ""
    expiry = ""
    if node.expires_at is not None:
        expiry = f" §8({max(0, node.expires_at - now)}s left)"
    if node.type is NodeType.PERMISSION:
        color = "§a+" if node.permission_value else "§c-"
        value = f"={node.value}"
    elif node.type is NodeType.PARENT:
        color = "§fparent"
        value = ""
    elif node.type is NodeType.META:
        color = "§fmeta"
        value = f"={node.value}"
    else:
        color = f"§f{node.type.value}"
        value = f"({node.priority})={node.value}"
    return f"{color} §f{node.key}§7{value}{context_text}{expiry}"


def _send_track_result(player: Player, result: TrackMoveResult) -> None:
    if result.status is TrackMoveStatus.SUCCESS:
        verb = "Promoted" if result.action is TrackMoveAction.PROMOTE else "Demoted"
        player.send_message(
            f"{FORM_PREFIX} §7{verb} on §f{result.track}§7: §f{result.group_from} §8-> §f"
            f"{result.group_to}§7."
        )
    elif result.status is TrackMoveStatus.ADDED_TO_FIRST_GROUP:
        player.send_message(
            f"{FORM_PREFIX} §7Added the player to §f{result.group_to}§7, the first group on "
            f"§f{result.track}§7."
        )
    elif result.status is TrackMoveStatus.REMOVED_FROM_FIRST_GROUP:
        player.send_message(
            f"{FORM_PREFIX} §7Removed the player from §f{result.group_from} §7on §f"
            f"{result.track}§7."
        )
    elif result.status is TrackMoveStatus.NOT_ON_TRACK:
        send_error(
            player,
            f"The player is not on track {result.track}.",
            "Promote once to add the player to the first group of this track.",
        )
    elif result.status is TrackMoveStatus.END_OF_TRACK:
        send_error(
            player,
            f"The player is already at the end of track {result.track}.",
            "Edit the track if another promotion step should be available.",
        )
    elif result.status is TrackMoveStatus.FIRST_GROUP_PROTECTED:
        send_error(
            player,
            f"The player is at the first group of {result.track}; removal was disabled.",
            "Allow removal from the first group before demoting again.",
        )
    else:
        send_error(
            player,
            f"The player has more than one direct position on track {result.track}.",
            "Remove the extra track parent before promoting or demoting this player.",
        )
