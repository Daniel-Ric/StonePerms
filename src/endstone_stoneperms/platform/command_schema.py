from __future__ import annotations

from collections.abc import Iterable

HELP_SECTIONS: dict[str, tuple[tuple[str, str], ...]] = {
    "overview": (
        ("/stoneperms help group", "Create groups, inspect them, and change their weight."),
        ("/stoneperms help user", "Inspect players, check permissions, and move track positions."),
        ("/stoneperms help track", "Build and maintain promotion ladders."),
        ("/stoneperms help nodes", "Manage permissions, parents, metadata, prefixes, and suffixes."),
        ("/stoneperms help web", "Check or change the dashboard connection."),
        ("/stoneperms help utility", "Open forms, read the audit log, or view plugin status."),
    ),
    "group": (
        ("/stoneperms group list", "Lists every group with its weight."),
        ("/stoneperms group create <group> [weight]", "Creates a group; weight defaults to 0."),
        ("/stoneperms group info <group>", "Shows direct nodes and inheritance for a group."),
        ("/stoneperms group setweight <group> <weight>", "Changes group selection priority."),
        ("/stoneperms group permission <group> ...", "Adds or removes permission nodes."),
        ("/stoneperms group parent <group> ...", "Adds or removes inherited groups."),
        ("/stoneperms group meta|prefix|suffix <group> ...", "Manages display metadata."),
    ),
    "user": (
        ("/stoneperms user <player> info", "Shows groups, metadata, and direct nodes."),
        (
            "/stoneperms user <player> check <permission> [context...]",
            "Shows the resolved result and source.",
        ),
        ("/stoneperms user <player> permission ...", "Adds or removes direct permission nodes."),
        ("/stoneperms user <player> parent ...", "Adds or removes direct group inheritance."),
        ("/stoneperms user <player> meta|prefix|suffix ...", "Reads or changes resolved metadata."),
        ("/stoneperms user <player> promote|demote <track>", "Moves the player along a track."),
        ("/stoneperms user <player> showtracks [context...]", "Lists direct track positions."),
    ),
    "track": (
        ("/stoneperms track list", "Lists tracks and their number of groups."),
        ("/stoneperms track create <track>", "Creates an empty promotion track."),
        ("/stoneperms track delete <track>", "Deletes a track without deleting its groups."),
        ("/stoneperms track info <track>", "Shows the complete promotion order."),
        ("/stoneperms track append <track> <group>", "Adds a group to the end."),
        ("/stoneperms track insert <track> <group> <position>", "Inserts a group at a one-based position."),
        ("/stoneperms track remove|clear|rename|clone <track> ...", "Maintains an existing track."),
    ),
    "nodes": (
        ("permission set <node> <true|false> [context...]", "Sets a permanent permission value."),
        ("permission settemp <node> <true|false> <duration> [context...]", "Sets an expiring permission."),
        ("permission unset|unsettemp <node> [context...]", "Removes matching permission nodes."),
        ("parent add|addtemp <group> [duration] [context...]", "Adds permanent or temporary inheritance."),
        ("parent remove|removetemp <group> [context...]", "Removes matching parent nodes."),
        ("meta get|set|settemp|unset|unsettemp ...", "Reads or changes a metadata key."),
        ("prefix|suffix get|set|settemp|unset|unsettemp ...", "Reads or changes a prioritized affix."),
    ),
    "web": (
        ("/stoneperms web dashboard", "Shows the dashboard configured for this server."),
        ("/stoneperms web login", "Creates a one-time sign-in code and connects a new server."),
        ("/stoneperms web status", "Shows connection state, API address, and server ID."),
        (
            "/stoneperms web pair <code> [name]",
            "Pairs with the configured dashboard; the public service is the default.",
        ),
        (
            "/stoneperms web pair <api-url> <code> [name]",
            "Pairs with a specific self-hosted StonePerms API.",
        ),
        ("/stoneperms web unpair", "Revokes the connection and removes the local credential."),
    ),
    "utility": (
        ("/stoneperms info", "Shows plugin state, group count, and default group."),
        ("/stoneperms log [limit]", "Shows recent permission changes from the local audit log."),
        ("/stoneperms form", "Opens the native Bedrock administration interface."),
        ("/stoneperms help [section]", "Opens this help or a specific command section."),
    ),
}

GROUP_ACTIONS = (
    "list",
    "create",
    "info",
    "setweight",
    "permission",
    "parent",
    "meta",
    "prefix",
    "suffix",
)
TRACK_ACTIONS = (
    "list",
    "create",
    "delete",
    "info",
    "append",
    "insert",
    "remove",
    "clear",
    "rename",
    "clone",
)
USER_ACTIONS = (
    "info",
    "check",
    "explain",
    "permission",
    "parent",
    "meta",
    "prefix",
    "suffix",
    "promote",
    "demote",
    "showtracks",
)


class _UsageBuilder:
    def __init__(self) -> None:
        self._enum_index = 0
        self.usages: list[str] = []

    def choice(
        self,
        *values: str,
        parameter: str,
        optional: bool = False,
    ) -> str:
        self._enum_index += 1
        enum_type = f"StonePermsChoice{self._enum_index:03d}"
        choices = "|".join(values)
        opening, closing = ("[", "]") if optional else ("<", ">")
        return f"({choices}){opening}{parameter}: {enum_type}{closing}"

    def add(self, *parameters: str) -> None:
        suffix = f" {' '.join(parameters)}" if parameters else ""
        self.usages.append(f"/stoneperms{suffix}")


def build_command_usages(
    *,
    group_names: Iterable[str] = (),
    track_names: Iterable[str] = (),
) -> tuple[str, ...]:
    groups = _merge_choices(GROUP_ACTIONS, group_names)
    tracks = _merge_choices(TRACK_ACTIONS, track_names)
    builder = _UsageBuilder()

    builder.add()
    builder.add(
        builder.choice("help", parameter="root"),
        builder.choice(*HELP_SECTIONS, parameter="section", optional=True),
    )
    builder.add(builder.choice("info", "form", "gui", parameter="root"))
    builder.add(builder.choice("log", parameter="root"), "[limit: int]")
    builder.add(
        builder.choice("web", parameter="root"),
        builder.choice(
            "dashboard", "login", "status", "pair", "unpair", parameter="action", optional=True
        ),
        "[arguments: message]",
    )
    builder.add(
        builder.choice("group", parameter="root"),
        builder.choice(*groups, parameter="action_or_group"),
        "[arguments: message]",
    )
    builder.add(
        builder.choice("user", parameter="root"),
        "<player: player>",
        builder.choice(*USER_ACTIONS, parameter="action"),
        "[arguments: message]",
    )
    builder.add(
        builder.choice("track", parameter="root"),
        builder.choice(*tracks, parameter="action_or_track"),
        "[arguments: message]",
    )
    return tuple(builder.usages)


def _merge_choices(actions: Iterable[str], names: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in (*tuple(actions), *sorted((str(name) for name in names), key=str.casefold)):
        normalized = value.strip().casefold()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return tuple(result)


COMMAND_USAGES = build_command_usages()
