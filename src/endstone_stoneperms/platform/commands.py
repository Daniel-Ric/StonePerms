from __future__ import annotations

import shlex
import time
from collections.abc import Sequence

from endstone import Player
from endstone.command import CommandSender
from endstone.plugin import Plugin

from ..application.manager import StonePermsManager
from ..domain.duration import parse_duration
from ..domain.model import (
    ContextSet,
    MetaDecision,
    Node,
    NodeType,
    PermissionDecision,
    SubjectRef,
    SubjectType,
    TrackMoveAction,
    TrackMoveResult,
    TrackMoveStatus,
    TrackRecord,
)
from ..web_defaults import PUBLIC_API_URL, PUBLIC_DASHBOARD_URL
from .attachments import AttachmentManager
from .command_schema import HELP_SECTIONS
from .forms import StonePermsFormController
from .presentation import PREFIX, send_error
from .web import StonePermsWebConnector, WebLoginCode

_GROUP_SUBJECT_ACTIONS = {
    "info",
    "setweight",
    "permission",
    "parent",
    "meta",
    "prefix",
    "suffix",
}
_TRACK_SUBJECT_ACTIONS = {
    "info",
    "append",
    "insert",
    "remove",
    "clear",
    "rename",
    "clone",
}


class CommandFeedbackError(ValueError):
    def __init__(self, message: str, hint: str) -> None:
        super().__init__(message)
        self.hint = hint


class StonePermsCommandRouter:
    def __init__(
        self,
        plugin: Plugin,
        manager: StonePermsManager,
        attachments: AttachmentManager,
        forms: StonePermsFormController | None = None,
        web: StonePermsWebConnector | None = None,
    ) -> None:
        self._plugin = plugin
        self._manager = manager
        self._attachments = attachments
        self._forms = forms
        self._web = web

    def handle(self, sender: CommandSender, args: Sequence[object]) -> bool:
        tokens: list[str] = []
        try:
            tokens = _command_tokens(args)
            self._route(sender, tokens)
        except CommandFeedbackError as exc:
            send_error(sender, str(exc), exc.hint)
        except (KeyError, LookupError, ValueError) as exc:
            send_error(sender, _clean_exception(exc), _command_hint(tokens))
        except Exception as exc:
            self._plugin.logger.error(f"StonePerms command failed: {exc}")
            send_error(
                sender,
                "StonePerms could not complete that command.",
                "Nothing was changed. Check the server log for the matching error.",
            )
        return True

    def _route(self, sender: CommandSender, tokens: list[str]) -> None:
        if not tokens or tokens[0].casefold() == "help":
            section = tokens[1].casefold() if len(tokens) > 1 else None
            self._send_help(sender, section)
            return

        command = tokens[0].casefold()
        handler = {
            "group": self._handle_group,
            "user": self._handle_user,
            "track": self._handle_track,
            "log": self._handle_log,
            "web": self._handle_web,
        }.get(command)
        if handler is not None:
            handler(sender, tokens)
            return
        if command == "info":
            self._send_info(sender)
            return
        if command in {"form", "gui"}:
            self._open_form(sender, tokens)
            return
        raise CommandFeedbackError(
            f"Unknown command: {tokens[0]}",
            "Run /stoneperms help to see the available command sections.",
        )

    def _open_form(self, sender: CommandSender, tokens: list[str]) -> None:
        if len(tokens) != 1:
            raise CommandFeedbackError(
                "The form command does not take any arguments.",
                "Run /stoneperms form while you are in game.",
            )
        if not isinstance(sender, Player):
            raise CommandFeedbackError(
                "The admin form can only be opened in game.",
                "Join the server and run /stoneperms form from Bedrock chat.",
            )
        if self._forms is None:
            raise CommandFeedbackError(
                "The admin form is not available right now.",
                "Wait for StonePerms to finish starting, then try again.",
            )
        self._forms.open(sender)

    def _handle_web(self, sender: CommandSender, tokens: list[str]) -> None:
        web = self._web
        if web is None:
            raise CommandFeedbackError(
                "The web bridge is not available right now.",
                "Check that StonePerms finished starting before using web commands.",
            )

        action = tokens[1].casefold() if len(tokens) > 1 else "status"
        handler = {
            "status": self._show_web_status,
            "dashboard": self._show_dashboard,
            "login": self._create_web_login,
            "pair": self._pair_web,
            "unpair": self._unpair_web,
        }.get(action)
        if handler is None:
            raise CommandFeedbackError(
                f"Unknown web action: {action}",
                "Use /stoneperms web dashboard, login, status, pair, or unpair.",
            )
        handler(sender, tokens, web)

    @staticmethod
    def _show_web_status(
        sender: CommandSender,
        tokens: list[str],
        web: StonePermsWebConnector,
    ) -> None:
        if len(tokens) not in {1, 2}:
            raise CommandFeedbackError(
                "The status command does not take any extra arguments.",
                "Run /stoneperms web status.",
            )

        status = web.status
        state = "§aonline" if status.ready else "§fconnecting" if status.connected else "§coffline"
        sender.send_message(
            f"{PREFIX} §7Web bridge: {state} §8| §7enabled: §f{str(status.enabled).lower()} "
            f"§8| §7configured: §f{str(status.configured).lower()}"
        )
        if status.api_url:
            sender.send_message(f"{PREFIX} §7API: §f{status.api_url}")
        if status.server_id:
            sender.send_message(f"{PREFIX} §7Server ID: §f{status.server_id}")
        if status.last_error:
            send_error(
                sender,
                f"Last connection error: {status.last_error}",
                "Check the API address and run /stoneperms web status again.",
            )
        if not status.configured:
            dashboard_url = status.api_url or PUBLIC_DASHBOARD_URL
            sender.send_message(f"{PREFIX} §7Dashboard: §f{dashboard_url}")
            sender.send_message(
                f"{PREFIX} §7Create a one-time code with §f/stoneperms web login§7."
            )

    @staticmethod
    def _show_dashboard(
        sender: CommandSender,
        tokens: list[str],
        web: StonePermsWebConnector,
    ) -> None:
        if len(tokens) != 2:
            raise CommandFeedbackError(
                "The dashboard command does not take any extra arguments.",
                "Run /stoneperms web dashboard.",
            )
        status = web.status
        dashboard_url = status.api_url or PUBLIC_DASHBOARD_URL
        label = (
            "Public dashboard"
            if dashboard_url.rstrip("/").casefold() == PUBLIC_API_URL.rstrip("/").casefold()
            else "Dashboard"
        )
        sender.send_message(f"{PREFIX} §7{label}: §f{dashboard_url}")
        if status.configured:
            sender.send_message(
                f"{PREFIX} §7Get a one-time sign-in code with §f/stoneperms web login§7."
            )
        else:
            sender.send_message(
                f"{PREFIX} §7Run §f/stoneperms web login §7to sign in and connect this server."
            )

    @staticmethod
    def _create_web_login(
        sender: CommandSender,
        tokens: list[str],
        web: StonePermsWebConnector,
    ) -> None:
        if len(tokens) != 2:
            raise CommandFeedbackError(
                "The login command does not take any extra arguments.",
                "Run /stoneperms web login.",
            )
        sender.send_message(f"{PREFIX} §7Creating a one-time login code...")

        def created(login_code: WebLoginCode | None, error: Exception | None) -> None:
            if error is not None or login_code is None:
                send_error(
                    sender,
                    f"Could not create a login code: {error or 'empty API response'}",
                    "Check the web connection with /stoneperms web status and try again.",
                )
                return
            seconds = max(0, login_code.expires_at - int(time.time()))
            minutes = max(1, (seconds + 59) // 60)
            sender.send_message(f"{PREFIX} §7Dashboard: §f{login_code.dashboard_url}")
            if login_code.username:
                sender.send_message(f"{PREFIX} §7Account: §f{login_code.username}")
            compact_code = login_code.code.replace("-", "").replace(" ", "")
            formatted_code = "-".join(
                compact_code[index : index + 4] for index in range(0, len(compact_code), 4)
            )
            sender.send_message(f"{PREFIX} §7One-time code: §f{formatted_code}")
            if login_code.claimed_server:
                sender.send_message(
                    f"{PREFIX} §7Using this code also connects the server to your dashboard."
                )
            sender.send_message(
                f"{PREFIX} §8The code works once and expires in about {minutes} minutes."
            )

        web.create_login_code_async(created)

    @staticmethod
    def _pair_web(
        sender: CommandSender,
        tokens: list[str],
        web: StonePermsWebConnector,
    ) -> None:
        arguments = tokens[2:]
        explicit_url = bool(
            arguments and arguments[0].casefold().startswith(("http://", "https://"))
        )
        if explicit_url:
            valid = 2 <= len(arguments) <= 3
            api_url = arguments[0] if arguments else ""
            code = arguments[1] if len(arguments) > 1 else ""
            server_name = arguments[2] if len(arguments) > 2 else None
        else:
            valid = 1 <= len(arguments) <= 2
            api_url = web.status.api_url or PUBLIC_API_URL
            code = arguments[0] if arguments else ""
            server_name = arguments[1] if len(arguments) > 1 else None
        if not valid:
            raise CommandFeedbackError(
                "The pairing command is incomplete.",
                "Use /stoneperms web pair <code> [name], or add <api-url> first for self-hosting.",
            )
        self_hosted = (
            api_url.rstrip("/").casefold() != PUBLIC_API_URL.rstrip("/").casefold()
        )
        target = "your self-hosted API" if self_hosted else "the public StonePerms service"
        sender.send_message(f"{PREFIX} §7Connecting this server to {target}...")

        def paired(server_id: str | None, error: Exception | None) -> None:
            if error is not None:
                send_error(
                    sender,
                    f"Pairing failed: {error}",
                    "Create a fresh pairing code in the dashboard and check the API address.",
                )
                return
            sender.send_message(f"{PREFIX} §7Paired successfully as server §f{server_id}")

        web.pair_async(api_url, code, server_name, paired)

    @staticmethod
    def _unpair_web(
        sender: CommandSender,
        tokens: list[str],
        web: StonePermsWebConnector,
    ) -> None:
        if len(tokens) != 2:
            raise CommandFeedbackError(
                "The unpair command does not take any extra arguments.",
                "Run /stoneperms web unpair.",
            )
        sender.send_message(f"{PREFIX} §7Removing the StonePerms API connection...")

        def unpaired(revoked: bool | None, error: Exception | None) -> None:
            if error is not None:
                send_error(
                    sender,
                    f"Could not remove the API connection: {error}",
                    "The local credential is still present. Check the API and try again.",
                )
            elif revoked:
                sender.send_message(f"{PREFIX} §7Local and remote credentials were removed.")
            else:
                sender.send_message(
                    f"{PREFIX} §7Local credentials were removed. §8| §7The API was unreachable."
                )

        web.unpair_async(unpaired)

    def _handle_group(self, sender: CommandSender, tokens: list[str]) -> None:
        tokens = _normalize_subject_action(tokens, _GROUP_SUBJECT_ACTIONS)
        action = tokens[1].casefold() if len(tokens) > 1 else ""
        if action == "list" and len(tokens) == 2:
            groups = self._manager.list_groups()
            rendered = " §8| §f".join(f"{group.name} ({group.weight})" for group in groups)
            sender.send_message(f"{PREFIX} §7Groups: §f{rendered or 'none'}")
            return
        if action == "create" and len(tokens) in {3, 4}:
            self._create_group(sender, tokens)
            return
        if len(tokens) < 3:
            raise CommandFeedbackError(
                "That group command is incomplete.",
                "Use /stoneperms help group to see group commands and examples.",
            )

        subject = self._manager.group_subject(tokens[1])
        self._handle_group_action(sender, subject, tokens[2].casefold(), tokens[3:])

    def _create_group(self, sender: CommandSender, tokens: list[str]) -> None:
        group_name = tokens[2]
        weight = int(tokens[3]) if len(tokens) == 4 else 0
        if not self._manager.create_group(group_name, actor=sender.name, weight=weight):
            raise CommandFeedbackError(
                f"Group {group_name!r} already exists.",
                f"Use /stoneperms group info {group_name} to inspect it.",
            )
        sender.send_message(f"{PREFIX} §7Created group §f{group_name} §7with weight §f{weight}§7.")
        self._attachments.refresh_all()

    def _handle_group_action(
        self,
        sender: CommandSender,
        subject: SubjectRef,
        action: str,
        arguments: list[str],
    ) -> None:
        if action == "info":
            self._send_subject_info(sender, subject)
        elif action == "setweight" and arguments:
            self._manager.set_group_weight(subject.identifier, int(arguments[0]), actor=sender.name)
            sender.send_message(
                f"{PREFIX} §7Set group §f{subject.identifier} §7to weight §f{arguments[0]}§7."
            )
            self._attachments.refresh_all()
        elif action == "permission":
            self._handle_permission(sender, subject, arguments)
        elif action == "parent":
            self._handle_parent(sender, subject, arguments)
        elif action == "meta":
            self._handle_meta(sender, subject, arguments)
        elif action in {"prefix", "suffix"}:
            self._handle_affix(sender, subject, NodeType(action), arguments)
        else:
            raise CommandFeedbackError(
                f"Unknown group action: {action}",
                "Use /stoneperms help group to see the supported group actions.",
            )

    def _handle_user(self, sender: CommandSender, tokens: list[str]) -> None:
        if len(tokens) < 3:
            raise CommandFeedbackError(
                "That user command is incomplete.",
                "Use /stoneperms help user to see user commands and examples.",
            )
        subject = self._manager.user_subject(tokens[1])
        action = tokens[2].casefold()
        if action == "info":
            self._send_subject_info(sender, subject)
        elif action in {"check", "explain"} and len(tokens) >= 4:
            contexts = _parse_contexts(tokens[4:])
            decision = self._manager.check_permission(subject, tokens[3], contexts)
            self._send_decision(sender, decision)
        elif action == "permission":
            self._handle_permission(sender, subject, tokens[3:])
        elif action == "parent":
            self._handle_parent(sender, subject, tokens[3:])
        elif action == "meta":
            self._handle_meta(sender, subject, tokens[3:])
        elif action in {"prefix", "suffix"}:
            self._handle_affix(sender, subject, NodeType(action), tokens[3:])
        elif action in {"promote", "demote"}:
            self._handle_track_move(sender, subject, action, tokens[3:])
        elif action == "showtracks":
            self._handle_show_tracks(sender, subject, tokens[3:])
        else:
            raise CommandFeedbackError(
                f"Unknown user action: {action}",
                "Use /stoneperms help user to see the supported user actions.",
            )

    def _handle_track(self, sender: CommandSender, tokens: list[str]) -> None:
        tokens = _normalize_subject_action(tokens, _TRACK_SUBJECT_ACTIONS)
        action = tokens[1].casefold() if len(tokens) > 1 else ""
        if action == "list" and len(tokens) == 2:
            tracks = self._manager.list_tracks()
            rendered = " §8| §f".join(f"{track.name} ({len(track.groups)})" for track in tracks)
            sender.send_message(f"{PREFIX} §7Tracks: §f{rendered or 'none'}")
            return
        if action == "create" and len(tokens) == 3:
            name = tokens[2]
            if not self._manager.create_track(name, actor=sender.name):
                raise CommandFeedbackError(
                    f"Track {name!r} already exists.",
                    f"Use /stoneperms track info {name} to inspect its ladder.",
                )
            sender.send_message(f"{PREFIX} §7Created track §f{name}§7.")
            return
        if action == "delete" and len(tokens) == 3:
            track = self._manager.get_track(tokens[2])
            self._manager.delete_track(track.name, actor=sender.name)
            sender.send_message(f"{PREFIX} §7Deleted track §f{track.name}§7.")
            return
        if len(tokens) < 3:
            raise CommandFeedbackError(
                "That track command is incomplete.",
                "Use /stoneperms help track to see track commands and examples.",
            )

        track = self._manager.get_track(tokens[1])
        self._handle_track_action(sender, track, tokens[2].casefold(), tokens[3:])

    def _handle_track_action(
        self,
        sender: CommandSender,
        track: TrackRecord,
        action: str,
        arguments: list[str],
    ) -> None:
        if action == "info":
            ladder = " §8-> §f".join(track.groups) if track.groups else "empty"
            sender.send_message(
                f"{PREFIX} §7Track §f{track.name} §8| §7groups: §f{len(track.groups)}"
            )
            sender.send_message(f"{PREFIX} §f{ladder}")
        elif action == "append" and arguments:
            updated = self._manager.append_track_group(
                track.name, arguments[0], actor=sender.name
            )
            sender.send_message(
                f"{PREFIX} §7Added §f{arguments[0]} §7to the end of §f{updated.name}§7."
            )
        elif action == "insert" and len(arguments) >= 2:
            updated = self._manager.insert_track_group(
                track.name,
                arguments[0],
                int(arguments[1]),
                actor=sender.name,
            )
            sender.send_message(
                f"{PREFIX} §7Inserted §f{arguments[0]} §7at position §f{arguments[1]} §7in §f"
                f"{updated.name}§7."
            )
        elif action == "remove" and arguments:
            updated = self._manager.remove_track_group(
                track.name, arguments[0], actor=sender.name
            )
            sender.send_message(
                f"{PREFIX} §7Removed §f{arguments[0]} §7from §f{updated.name}§7."
            )
        elif action == "clear" and not arguments:
            self._manager.clear_track(track.name, actor=sender.name)
            sender.send_message(f"{PREFIX} §7Cleared every group from §f{track.name}§7.")
        elif action == "rename" and arguments:
            renamed = self._manager.rename_track(track.name, arguments[0], actor=sender.name)
            sender.send_message(
                f"{PREFIX} §7Renamed track §f{track.name} §7to §f{renamed.name}§7."
            )
        elif action == "clone" and arguments:
            clone = self._manager.clone_track(track.name, arguments[0], actor=sender.name)
            sender.send_message(
                f"{PREFIX} §7Cloned track §f{track.name} §7as §f{clone.name}§7."
            )
        else:
            raise CommandFeedbackError(
                f"Unknown track action: {action}",
                "Use /stoneperms help track to see the supported track actions.",
            )

    def _handle_track_move(
        self,
        sender: CommandSender,
        subject: SubjectRef,
        action: str,
        tokens: list[str],
    ) -> None:
        if not tokens:
            raise CommandFeedbackError(
                f"Choose a track before you {action} a player.",
                f"Usage: /stoneperms user <user> {action} <track> [context...].",
            )
        track_name = tokens[0]
        flag = "--dont-add-to-first" if action == "promote" else "--dont-remove-from-first"
        unknown_flags = [token for token in tokens[1:] if token.startswith("--") and token != flag]
        if unknown_flags:
            raise CommandFeedbackError(
                f"Unknown option: {unknown_flags[0]}",
                f"The only supported option for this command is {flag}.",
            )
        cross_boundary = flag not in tokens[1:]
        contexts = _parse_contexts([token for token in tokens[1:] if token != flag])
        if action == "promote":
            result = self._manager.promote(
                subject,
                track_name,
                actor=sender.name,
                contexts=contexts,
                add_to_first=cross_boundary,
            )
        else:
            result = self._manager.demote(
                subject,
                track_name,
                actor=sender.name,
                contexts=contexts,
                remove_from_first=cross_boundary,
            )
        self._send_track_move(sender, result)
        if result.changed:
            self._attachments.refresh_all()

    def _handle_show_tracks(
        self,
        sender: CommandSender,
        subject: SubjectRef,
        tokens: list[str],
    ) -> None:
        contexts = _parse_contexts(tokens) if tokens else None
        positions = self._manager.user_tracks(subject, contexts)
        if not positions:
            sender.send_message(f"{PREFIX} §7This player has no direct position on a track.")
            return
        rendered = ", ".join(
            f"{track}={'/'.join(groups)}" for track, groups in positions.items()
        )
        sender.send_message(f"{PREFIX} §7Track positions: §f{rendered}")

    @staticmethod
    def _send_track_move(sender: CommandSender, result: TrackMoveResult) -> None:
        if result.status is TrackMoveStatus.SUCCESS:
            verb = "Promoted" if result.action is TrackMoveAction.PROMOTE else "Demoted"
            sender.send_message(
                f"{PREFIX} §7{verb} on §f{result.track}§7: §f{result.group_from} §8-> §f"
                f"{result.group_to}§7."
            )
        elif result.status is TrackMoveStatus.ADDED_TO_FIRST_GROUP:
            sender.send_message(
                f"{PREFIX} §7Added the player to §f{result.group_to}§7, the first group on "
                f"§f{result.track}§7."
            )
        elif result.status is TrackMoveStatus.REMOVED_FROM_FIRST_GROUP:
            sender.send_message(
                f"{PREFIX} §7Removed the player from §f{result.group_from} §7on §f"
                f"{result.track}§7."
            )
        elif result.status is TrackMoveStatus.NOT_ON_TRACK:
            send_error(
                sender,
                f"The player is not on track {result.track}.",
                "Promote once to add the player to the first group of this track.",
            )
        elif result.status is TrackMoveStatus.END_OF_TRACK:
            send_error(
                sender,
                f"The player is already at the end of track {result.track}.",
                "Edit the track if another promotion step should be available.",
            )
        elif result.status is TrackMoveStatus.FIRST_GROUP_PROTECTED:
            send_error(
                sender,
                f"The player is at the first group of {result.track}; removal was disabled.",
                "Run demote again without --dont-remove-from-first to remove that group.",
            )
        else:
            send_error(
                sender,
                f"The player has more than one direct position on track {result.track}.",
                "Remove the extra track parent before promoting or demoting this player.",
            )

    def _handle_permission(
        self,
        sender: CommandSender,
        subject: SubjectRef,
        tokens: list[str],
    ) -> None:
        if len(tokens) < 2:
            raise CommandFeedbackError(
                "Choose a permission action and permission node.",
                "Use permission set, settemp, unset, or unsettemp.",
            )
        action = tokens[0].casefold()
        permission = tokens[1]
        if action == "set" and len(tokens) >= 3:
            value = _parse_bool(tokens[2])
            contexts = _parse_contexts(tokens[3:])
            self._manager.set_permission(
                subject, permission, value, actor=sender.name, contexts=contexts
            )
            expiry_text = ""
        elif action == "settemp" and len(tokens) >= 4:
            value = _parse_bool(tokens[2])
            duration = parse_duration(tokens[3])
            contexts = _parse_contexts(tokens[4:])
            self._manager.set_permission(
                subject,
                permission,
                value,
                actor=sender.name,
                contexts=contexts,
                expires_at=int(time.time()) + duration,
            )
            expiry_text = f" §7for §f{tokens[3]}"
        elif action in {"unset", "unsettemp"}:
            contexts = _parse_contexts(tokens[2:])
            removed = self._manager.unset_permission(
                subject,
                permission,
                actor=sender.name,
                contexts=contexts,
                temporary=action == "unsettemp",
            )
            sender.send_message(f"{PREFIX} §7Removed §f{removed} §7permission node(s).")
            self._attachments.refresh_all()
            return
        else:
            raise CommandFeedbackError(
                f"Unknown permission action: {action}",
                "Use permission set, settemp, unset, or unsettemp.",
            )

        sender.send_message(
            f"{PREFIX} §7Set §f{permission} §7to §f{str(value).lower()}{expiry_text}"
            f"{_render_contexts(contexts)}"
        )
        self._attachments.refresh_all()

    def _handle_parent(
        self,
        sender: CommandSender,
        subject: SubjectRef,
        tokens: list[str],
    ) -> None:
        if len(tokens) < 2:
            raise CommandFeedbackError(
                "Choose a parent action and group.",
                "Use parent add, addtemp, remove, or removetemp.",
            )
        action = tokens[0].casefold()
        parent = tokens[1]
        if action == "add":
            contexts = _parse_contexts(tokens[2:])
            self._manager.add_parent(subject, parent, actor=sender.name, contexts=contexts)
            expiry_text = ""
        elif action == "addtemp" and len(tokens) >= 3:
            duration = parse_duration(tokens[2])
            contexts = _parse_contexts(tokens[3:])
            self._manager.add_parent(
                subject,
                parent,
                actor=sender.name,
                contexts=contexts,
                expires_at=int(time.time()) + duration,
            )
            expiry_text = f" §7for §f{tokens[2]}"
        elif action in {"remove", "removetemp"}:
            contexts = _parse_contexts(tokens[2:])
            removed = self._manager.remove_parent(
                subject,
                parent,
                actor=sender.name,
                contexts=contexts,
                temporary=action == "removetemp",
            )
            sender.send_message(f"{PREFIX} §7Removed §f{removed} §7parent node(s).")
            self._attachments.refresh_all()
            return
        else:
            raise CommandFeedbackError(
                f"Unknown parent action: {action}",
                "Use parent add, addtemp, remove, or removetemp.",
            )

        sender.send_message(
            f"{PREFIX} §7Added parent §f{parent}{expiry_text}{_render_contexts(contexts)}"
        )
        self._attachments.refresh_all()

    def _handle_meta(
        self,
        sender: CommandSender,
        subject: SubjectRef,
        tokens: list[str],
    ) -> None:
        if not tokens:
            raise CommandFeedbackError(
                "Choose a metadata action.",
                "Use meta get, set, settemp, unset, or unsettemp.",
            )
        action = tokens[0].casefold()
        if action == "get" and len(tokens) >= 2:
            self._require_user_query(subject, "meta get")
            contexts = _parse_contexts(tokens[2:])
            self._send_meta_decision(
                sender,
                self._manager.resolve_meta(subject, tokens[1], contexts),
            )
            return
        if len(tokens) < 2:
            raise CommandFeedbackError(
                "Choose a metadata key.",
                "Example: /stoneperms user Steve meta get chat-color.",
            )
        key = tokens[1]
        if action == "set" and len(tokens) >= 3:
            value = tokens[2]
            contexts = _parse_contexts(tokens[3:])
            self._manager.set_meta(subject, key, value, actor=sender.name, contexts=contexts)
            expiry_text = ""
        elif action == "settemp" and len(tokens) >= 4:
            value = tokens[2]
            duration = parse_duration(tokens[3])
            contexts = _parse_contexts(tokens[4:])
            self._manager.set_meta(
                subject,
                key,
                value,
                actor=sender.name,
                contexts=contexts,
                expires_at=int(time.time()) + duration,
            )
            expiry_text = f" §7for §f{tokens[3]}"
        elif action in {"unset", "unsettemp"}:
            contexts = _parse_contexts(tokens[2:])
            removed = self._manager.unset_meta(
                subject,
                key,
                actor=sender.name,
                contexts=contexts,
                temporary=action == "unsettemp",
            )
            sender.send_message(f"{PREFIX} §7Removed §f{removed} §7metadata node(s).")
            return
        else:
            raise CommandFeedbackError(
                f"Unknown metadata action: {action}",
                "Use meta get, set, settemp, unset, or unsettemp.",
            )
        sender.send_message(
            f"{PREFIX} §7Set metadata §f{key} §7to §f{value}{expiry_text}"
            f"{_render_contexts(contexts)}"
        )

    def _handle_affix(
        self,
        sender: CommandSender,
        subject: SubjectRef,
        node_type: NodeType,
        tokens: list[str],
    ) -> None:
        if not tokens:
            raise CommandFeedbackError(
                f"Choose a {node_type.value} action.",
                f"Use {node_type.value} get, set, settemp, unset, or unsettemp.",
            )
        action = tokens[0].casefold()
        if action == "get":
            self._require_user_query(subject, f"{node_type.value} get")
            contexts = _parse_contexts(tokens[1:])
            decision = (
                self._manager.resolve_prefix(subject, contexts)
                if node_type is NodeType.PREFIX
                else self._manager.resolve_suffix(subject, contexts)
            )
            self._send_meta_decision(sender, decision)
            return
        if len(tokens) < 2:
            raise CommandFeedbackError(
                f"Choose a priority for this {node_type.value}.",
                f"Example: {node_type.value} set 100 \"[Member] \".",
            )
        priority = int(tokens[1])
        if action == "set" and len(tokens) >= 3:
            value = tokens[2]
            contexts = _parse_contexts(tokens[3:])
            expires_at = None
            expiry_text = ""
        elif action == "settemp" and len(tokens) >= 4:
            value = tokens[2]
            duration = parse_duration(tokens[3])
            contexts = _parse_contexts(tokens[4:])
            expires_at = int(time.time()) + duration
            expiry_text = f" §7for §f{tokens[3]}"
        elif action in {"unset", "unsettemp"}:
            contexts = _parse_contexts(tokens[2:])
            unsetter = (
                self._manager.unset_prefix
                if node_type is NodeType.PREFIX
                else self._manager.unset_suffix
            )
            removed = unsetter(
                subject,
                priority,
                actor=sender.name,
                contexts=contexts,
                temporary=action == "unsettemp",
            )
            sender.send_message(
                f"{PREFIX} §7Removed §f{removed} §7{node_type.value} node(s) at priority §f"
                f"{priority}§7."
            )
            return
        else:
            raise CommandFeedbackError(
                f"Unknown {node_type.value} action: {action}",
                f"Use {node_type.value} get, set, settemp, unset, or unsettemp.",
            )
        setter = (
            self._manager.set_prefix if node_type is NodeType.PREFIX else self._manager.set_suffix
        )
        setter(
            subject,
            value,
            priority,
            actor=sender.name,
            contexts=contexts,
            expires_at=expires_at,
        )
        sender.send_message(
            f"{PREFIX} §7Set {node_type.value} priority §f{priority} §7to §f{value}"
            f"{expiry_text}{_render_contexts(contexts)}"
        )

    @staticmethod
    def _require_user_query(subject: SubjectRef, action: str) -> None:
        if subject.type is not SubjectType.USER:
            raise CommandFeedbackError(
                f"{action} only works with a player.",
                "Use /stoneperms user <player> for resolved metadata queries.",
            )

    def _send_subject_info(self, sender: CommandSender, subject: SubjectRef) -> None:
        nodes = self._manager.nodes_for(subject)
        sender.send_message(
            f"{PREFIX} §7{subject.type.value.title()}: §f{subject.identifier} "
            f"§8| §7direct nodes: §f{len(nodes)}"
        )
        if subject.type.value == "user":
            groups = self._manager.effective_groups(subject)
            primary = self._manager.primary_group(subject)
            sender.send_message(
                f"{PREFIX} §7Primary group: §f{primary} §8| §7effective groups: §f"
                f"{', '.join(groups)}"
            )
            prefix = self._manager.resolve_prefix(subject).value or ""
            suffix = self._manager.resolve_suffix(subject).value or ""
            meta = self._manager.meta_map(subject)
            sender.send_message(
                f"{PREFIX} §7Prefix: §f{prefix or 'none'} §8| §7suffix: §f"
                f"{suffix or 'none'}"
            )
            if meta:
                rendered_meta = ", ".join(f"{key}={value}" for key, value in meta.items())
                sender.send_message(f"{PREFIX} §7Metadata: §f{rendered_meta}")
        for node in nodes[:10]:
            sender.send_message(f"{PREFIX} {_render_node(node)}")
        if len(nodes) > 10:
            sender.send_message(f"{PREFIX} §8... and {len(nodes) - 10} more")

    @staticmethod
    def _send_decision(sender: CommandSender, decision: PermissionDecision) -> None:
        if decision.selected is None:
            sender.send_message(
                f"{PREFIX} §fUNDEFINED §8| §f{decision.permission} §7uses the Endstone default."
            )
            return
        selected = decision.selected
        state = "§aALLOWED" if decision.value else "§cDENIED"
        source = f"{selected.origin.type.value}:{selected.origin.identifier}"
        sender.send_message(f"{PREFIX} {state} §8| §f{decision.permission}")
        sender.send_message(
            f"{PREFIX} §7Source: §f{source} §8| §7matched: §f{selected.node.key}"
        )
        sender.send_message(
            f"{PREFIX} §7Direct: §f{str(selected.direct).lower()} §8| §7distance: §f"
            f"{selected.inheritance_distance} §8| §7weight: §f{selected.group_weight}"
        )

    @staticmethod
    def _send_meta_decision(sender: CommandSender, decision: MetaDecision) -> None:
        label = decision.key if decision.type is NodeType.META else decision.type.value
        if decision.selected is None:
            sender.send_message(f"{PREFIX} §fUNDEFINED §8| §f{label}")
            return
        selected = decision.selected
        source = f"{selected.origin.type.value}:{selected.origin.identifier}"
        sender.send_message(f"{PREFIX} §7{decision.type.value.title()}: §f{decision.value}")
        sender.send_message(
            f"{PREFIX} §7Key: §f{decision.key} §8| §7priority: §f{selected.node.priority}"
        )
        sender.send_message(
            f"{PREFIX} §7Source: §f{source} §8| §7direct: §f"
            f"{str(selected.direct).lower()} §8| §7distance: §f{selected.inheritance_distance}"
        )

    def _handle_log(self, sender: CommandSender, tokens: list[str]) -> None:
        limit = int(tokens[1]) if len(tokens) > 1 else 10
        for entry in reversed(self._manager.recent_audit(limit)):
            subject = (
                f"{entry['subject_type']}:{entry['subject_id']}"
                if entry["subject_type"]
                else "system"
            )
            sender.send_message(
                f"{PREFIX} §8#{entry['id']} §7{entry['actor']} §f{entry['action']} §8-> §f{subject}"
            )

    def _send_info(self, sender: CommandSender) -> None:
        groups = self._manager.list_groups()
        sender.send_message(
            f"{PREFIX} §aOnline §8| §7groups: §f{len(groups)} §8| §7default group: §f"
            f"{self._manager.default_group}"
        )

    @staticmethod
    def _send_help(sender: CommandSender, section: str | None = None) -> None:
        selected = section or "overview"
        lines = HELP_SECTIONS.get(selected)
        if lines is None:
            raise CommandFeedbackError(
                f"Unknown help section: {selected}",
                "Choose group, user, track, nodes, web, or utility.",
            )
        title = "StonePerms Help" if selected == "overview" else f"StonePerms {selected.title()} Help"
        sender.send_message(f"§8---- §7{title} §8----")
        for command, description in lines:
            sender.send_message(f"{PREFIX} §f{command} §8- §7{description}")


def _command_tokens(args: Sequence[object]) -> list[str]:
    return [piece for value in args for piece in shlex.split(str(value))]


def _normalize_subject_action(tokens: list[str], actions: set[str]) -> list[str]:
    if len(tokens) >= 3 and tokens[1].casefold() in actions:
        return [tokens[0], tokens[2], tokens[1], *tokens[3:]]
    return tokens


def _clean_exception(exc: Exception) -> str:
    message = str(exc).strip()
    if isinstance(exc, KeyError):
        message = message.strip("'\"")
    if not message:
        return "The requested value could not be found."
    if message[-1] not in ".!?":
        message += "."
    return message


def _command_hint(tokens: Sequence[str]) -> str:
    if not tokens:
        return "Run /stoneperms help to see the available command sections."
    section = tokens[0].casefold()
    if section in {"group", "user", "track", "web"}:
        return f"Run /stoneperms help {section} for the matching syntax and examples."
    if section in {"form", "gui", "log", "info"}:
        return "Run /stoneperms help utility for the matching syntax and examples."
    return "Run /stoneperms help to see the available command sections."


def _parse_contexts(tokens: Sequence[str]) -> ContextSet:
    expanded = [piece for token in tokens for piece in str(token).split()]
    return ContextSet.parse(expanded)


def _parse_bool(value: object) -> bool:
    normalized = str(value).strip().casefold()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    raise ValueError(f"Use true or false, not {value!r}")


def _render_contexts(contexts: ContextSet) -> str:
    if not contexts.pairs:
        return ""
    return " §8| §7contexts: §f" + " ".join(f"{key}={value}" for key, value in contexts.pairs)


def _render_node(node: Node) -> str:
    temporary = f" §8| §7expires: §f{node.expires_at}" if node.expires_at is not None else ""
    contexts = " ".join(f"{key}={value}" for key, value in node.contexts.pairs)
    context_text = f" §8| §7contexts: §f{contexts}" if contexts else ""
    if node.type is NodeType.PERMISSION:
        state = "§a+" if node.permission_value else "§c-"
        return f"{state} §f{node.key} §8= §7{node.value}{context_text}{temporary}"
    if node.type is NodeType.META:
        return f"§fMeta §f{node.key} §8= §7{node.value}{context_text}{temporary}"
    if node.type in {NodeType.PREFIX, NodeType.SUFFIX}:
        return (
            f"§f{node.type.value.title()} §7priority: §f{node.priority} §8| §7value: §f{node.value}"
            f"{context_text}{temporary}"
        )
    return f"§f{node.type.value.title()} §f{node.key}{context_text}{temporary}"
