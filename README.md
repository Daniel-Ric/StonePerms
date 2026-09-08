<p align="center">
  <img src="dashboard/public/stoneperms-logo.png" alt="StonePerms logo" width="168">
</p>

<h1 align="center">StonePerms</h1>

<p align="center">
  Permissions, groups, tracks, chat formatting, and a web editor for Endstone servers.
</p>

<p align="center">
  <img alt="StonePerms 0.8.12" src="https://img.shields.io/badge/StonePerms-0.8.12-d8d58d?style=flat-square">
  <a href="https://endstone.dev/"><img alt="Endstone 0.11" src="https://img.shields.io/badge/Endstone-0.11-d8d58d?style=flat-square"></a>
  <img alt="Python 3.11 or newer" src="https://img.shields.io/badge/Python-3.11%2B-68737a?style=flat-square&logo=python&logoColor=white">
  <a href="LICENSE"><img alt="MIT license" src="https://img.shields.io/badge/License-MIT-68737a?style=flat-square"></a>
</p>

<p align="center">
  <a href="#features">Features</a> ·
  <a href="#first-setup">Setup</a> ·
  <a href="#commands">Commands</a> ·
  <a href="https://stoneperms.spindexgfx.com">Public dashboard</a> ·
  <a href="api/README.md">Self-hosting</a> ·
  <a href="dashboard/README.md">Dashboard</a>
</p>

StonePerms stores and resolves permissions for [Endstone](https://endstone.dev/). It applies the
result through Endstone's native `PermissionAttachment` API, so permission checks continue to work
when the web stack is offline. The optional Node.js API forwards dashboard requests to the plugin;
it never opens the plugin database itself.

## Features

- **Permission data** — users, groups, recursive inheritance, positive and negative nodes,
  temporary assignments, weighted conflict resolution, and persistent audit history.
- **Storage** — SQLite by default, or optional MySQL with shared permissions, groups, tracks,
  metadata, prefixes, and suffixes across servers and a separate user table for each server.
- **Contexts** — built-in `server`, `world`, `dimension`, and `gamemode` values plus context
  providers registered by other Endstone plugins.
- **Display data** — inherited metadata, multiple weighted prefixes and suffixes, PAPI placeholders,
  and optional chat and nametag formatting.
- **Administration** — commands, native Bedrock Forms, tracks with promote/demote operations, and
  permission explanations with `/stoneperms user ... check`.
- **Web management** — a public or self-hosted Node.js API and Vue dashboard with accounts, server roles,
  pairing, player profiles, groups, tracks, editor sessions, settings, and audit pages.
- **Player profiles** — UUID, XUID, and last-name lookups together with stored skin fingerprints,
  local vanilla-face rendering, and a Character Creator fallback.

Exact permission nodes, terminal wildcards such as `namespace.*`, and the global `*` node are
supported. Changes are recalculated after joins, context changes, plugin loads, mutations, and
temporary-node expiry.

## Requirements

- Python 3.11 or newer
- Endstone 0.11.x
- Optional: [Endstone PAPI](https://github.com/EndstoneMC/papi) for placeholders
- `websocket-client` (installed automatically with the Python package) when the web bridge is used
- Node.js 22.13+ or Docker only when self-hosting the optional API

## Building from source

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m ruff check src
python -m build
```

Copy the built wheel from `dist/` into the Endstone server's `plugins/` directory. The default
database is created as `plugins/stoneperms/stoneperms.db` when the plugin is first enabled.
If wheels are copied directly instead of installing the package with `pip`, ensure
`websocket-client>=1.8,<2` is installed in Endstone's Python environment before enabling `[web]`.
See the [self-hosting guide](api/README.md) and [dashboard development guide](dashboard/README.md)
for the optional web stack.

The public dashboard is available at `https://stoneperms.spindexgfx.com`. Create a pairing code
there and run `/stoneperms web pair <code> [server-name]`. Self-hosted installations keep using
`/stoneperms web pair <api-url> <code> [server-name]`.

## First setup

On startup, StonePerms reports its active storage, display integrations, dashboard pairing, groups,
and tracks. It also flags server settings that can weaken player identity, grant administration to
every new player, block enabled chat formatting, or prevent custom-skin portraits. StonePerms does
not require changes to the default `endstone.toml`. The `[startup]` section in `config.toml` controls
the detailed summary and the `server.properties` checks.

StonePerms management commands default to Endstone operators. From the console:

```text
stoneperms group create moderator 100
stoneperms group permission moderator set example.command.kick true
stoneperms user Steve parent add moderator
stoneperms user Steve check example.command.kick
```

Users must have joined at least once before they can be addressed by their last known name. UUID is
the canonical identity; XUID and name are lookup aliases.

## Commands

The root command is `/stoneperms`; aliases are `/sp` and `/perms`.

<details>
<summary>Show the complete command reference</summary>

<br>

```text
/stoneperms help
/stoneperms info
/stoneperms log [limit]
/stoneperms form
/stoneperms web dashboard
/stoneperms web status
/stoneperms web pair <pairing-code> [server-name]
/stoneperms web pair <api-url> <pairing-code> [server-name]
/stoneperms web login
/stoneperms web unpair

/stoneperms track list
/stoneperms track create <track>
/stoneperms track delete <track>
/stoneperms track info <track>
/stoneperms track append <track> <group>
/stoneperms track insert <track> <group> <position>
/stoneperms track remove <track> <group>
/stoneperms track clear <track>
/stoneperms track rename <track> <new-track>
/stoneperms track clone <track> <new-track>

/stoneperms group list
/stoneperms group create <group> [weight]
/stoneperms group info <group>
/stoneperms group setweight <group> <weight>
/stoneperms group permission <group> set <node> <true|false> [key=value ...]
/stoneperms group permission <group> settemp <node> <true|false> <duration> [key=value ...]
/stoneperms group permission <group> unset <node> [key=value ...]
/stoneperms group permission <group> unsettemp <node> [key=value ...]
/stoneperms group parent <group> add <parent> [key=value ...]
/stoneperms group parent <group> addtemp <parent> <duration> [key=value ...]
/stoneperms group parent <group> remove <parent> [key=value ...]
/stoneperms group parent <group> removetemp <parent> [key=value ...]
/stoneperms group meta <group> set <key> <value> [key=value ...]
/stoneperms group meta <group> settemp <key> <value> <duration> [key=value ...]
/stoneperms group meta <group> unset <key> [key=value ...]
/stoneperms group meta <group> unsettemp <key> [key=value ...]
/stoneperms group prefix <group> set <priority> <value> [key=value ...]
/stoneperms group prefix <group> settemp <priority> <value> <duration> [key=value ...]
/stoneperms group prefix <group> unset <priority> [key=value ...]
/stoneperms group prefix <group> unsettemp <priority> [key=value ...]
/stoneperms group suffix <group> set <priority> <value> [key=value ...]
/stoneperms group suffix <group> settemp <priority> <value> <duration> [key=value ...]
/stoneperms group suffix <group> unset <priority> [key=value ...]
/stoneperms group suffix <group> unsettemp <priority> [key=value ...]

/stoneperms user <name|uuid|xuid> info
/stoneperms user <name|uuid|xuid> check <node> [key=value ...]
/stoneperms user <name|uuid|xuid> permission set <node> <true|false> [key=value ...]
/stoneperms user <name|uuid|xuid> permission settemp <node> <true|false> <duration> [key=value ...]
/stoneperms user <name|uuid|xuid> permission unset <node> [key=value ...]
/stoneperms user <name|uuid|xuid> permission unsettemp <node> [key=value ...]
/stoneperms user <name|uuid|xuid> parent add <parent> [key=value ...]
/stoneperms user <name|uuid|xuid> parent addtemp <parent> <duration> [key=value ...]
/stoneperms user <name|uuid|xuid> parent remove <parent> [key=value ...]
/stoneperms user <name|uuid|xuid> parent removetemp <parent> [key=value ...]
/stoneperms user <name|uuid|xuid> meta get <key> [key=value ...]
/stoneperms user <name|uuid|xuid> meta set <key> <value> [key=value ...]
/stoneperms user <name|uuid|xuid> meta settemp <key> <value> <duration> [key=value ...]
/stoneperms user <name|uuid|xuid> meta unset <key> [key=value ...]
/stoneperms user <name|uuid|xuid> meta unsettemp <key> [key=value ...]
/stoneperms user <name|uuid|xuid> prefix get [key=value ...]
/stoneperms user <name|uuid|xuid> prefix set <priority> <value> [key=value ...]
/stoneperms user <name|uuid|xuid> prefix settemp <priority> <value> <duration> [key=value ...]
/stoneperms user <name|uuid|xuid> prefix unset <priority> [key=value ...]
/stoneperms user <name|uuid|xuid> prefix unsettemp <priority> [key=value ...]
/stoneperms user <name|uuid|xuid> suffix get [key=value ...]
/stoneperms user <name|uuid|xuid> suffix set <priority> <value> [key=value ...]
/stoneperms user <name|uuid|xuid> suffix settemp <priority> <value> <duration> [key=value ...]
/stoneperms user <name|uuid|xuid> suffix unset <priority> [key=value ...]
/stoneperms user <name|uuid|xuid> suffix unsettemp <priority> [key=value ...]
/stoneperms user <name|uuid|xuid> promote <track> [--dont-add-to-first] [key=value ...]
/stoneperms user <name|uuid|xuid> demote <track> [--dont-remove-from-first] [key=value ...]
/stoneperms user <name|uuid|xuid> showtracks [key=value ...]
```

Durations can be combined, for example `30m`, `2h30m`, `7d`, or `1mo2d`.
Quote prefix, suffix, and meta values that contain spaces, for example
`/stoneperms group prefix vip set 100 "[VIP] "`.

</details>

## Service API

Other Python plugins can load `stoneperms.permissions.v1` from Endstone's `ServiceManager`:

```python
service = server.service_manager.load("stoneperms.permissions.v1")
if service is not None and service.has_permission(player, "example.feature.use"):
    ...

primary = service.get_primary_group(player)
groups = service.get_groups(player)
decision = service.check_permission(player, "example.feature.use")
prefix = service.get_prefix(player)
suffix = service.get_suffix(player)
chat_color = service.get_meta(player, "chat-color")
metadata = service.get_meta_map(player)
tracks = service.get_tracks()
positions = service.get_user_tracks(player)

result = service.promote(player, "staff", actor="MyPlugin")
result = service.demote(player, "staff", actor="MyPlugin")

session = service.create_editor_session(actor="admin:stable-id", users=("Steve",))
result = service.apply_editor_changes(changeset, actor="admin:stable-id")
```

Minigame and region plugins can contribute dynamic contexts:

```python
service.register_context_provider(
    "my-minigame",
    "arena",
    lambda player: current_arena_name(player),
)
```

The provider should be unregistered when the owning plugin is disabled:

```python
service.unregister_context_providers("my-minigame")
```

## PAPI placeholders

When the official Endstone PAPI plugin is installed, StonePerms registers the `stoneperms`
expansion automatically. It also registers when PAPI is enabled after StonePerms and unregisters
cleanly during shutdown.

```text
{stoneperms:prefix}
{stoneperms:suffix}
{stoneperms:primary_group}
{stoneperms:groups}
{stoneperms:meta.chat-color}
{stoneperms:track.current.staff}
{stoneperms:track.next.staff}
{stoneperms:track.previous.staff}
{stoneperms:track.has.staff}
```

Prefix, suffix, and metadata placeholders return an empty string when no value applies. Unknown
placeholders are left unresolved by returning `None`. Current PAPI builds use the colon syntax
shown above. The compatibility adapter also supports PAPI 0.0.1, whose parser uses
`{stoneperms|prefix}`.

## Chat and nametags

StonePerms can optionally display its resolved prefix and suffix in player chat and above online
players. Both formatters are disabled by default so an existing chat or nametag plugin keeps full
control. Owners and admins can configure them from **Chat & nametags** below the selected server in
the dashboard.

The dashboard **Settings** page exposes the safe plugin configuration for the selected server: the
default group, built-in server context, optional device and locale contexts, cleanup and permission
catalog intervals, and debug logging. Runtime-safe changes apply immediately. Values that affect
startup wiring are saved by the plugin and marked as requiring a server restart.

The chat template supports `{prefix}`, `{name}`, `{suffix}`, and `{message}`. The nametag template
supports the same metadata placeholders without `{message}`. Minecraft `§` color and style codes
can be used directly. Chat formatting changes only `PlayerChatEvent.format`; it does not cancel or
rebroadcast the event. Disabling nametags restores the value that was present before StonePerms
started formatting that player.

## Tracks

A track is an ordered promotion ladder, for example
`default → helper → moderator → administrator`. Defining a track does not grant groups and never
changes inheritance by itself. Promote and demote only replace a user's direct parent assignment
with exactly the requested contexts. Temporary parent expiry is preserved while moving.

Promoting a user who has no position adds the first group unless `--dont-add-to-first` is supplied.
Demoting from the first group removes that assignment unless `--dont-remove-from-first` is supplied.
The action is rejected if the user has multiple direct positions on the same track.

## Bedrock Forms and editor protocol

In-game administrators can open the native UI with `/stoneperms form`. The Vue dashboard uses the
same manager operations through editor protocol v1 and the authenticated web connection. The plugin
validates and applies every change and keeps working when the API or dashboard is offline.

## MySQL and multiple servers

Existing installations continue using SQLite with the same configuration, database schema,
commands, and permission behavior. MySQL is opt-in and requires MySQL 8.0 or newer. Install the
optional driver in Endstone's Python environment:

```sh
python -m pip install "endstone-stoneperms[mysql]"
```

When copying the plugin wheel directly, install `PyMySQL[rsa]>=1.1.1,<2` in that environment.
Create a dedicated database and a database account with permissions to create tables and read,
insert, update, and delete rows. Configure every participating server to use the same database:

```toml
[storage]
backend = "mysql"
database = "stoneperms.db"
server_id = "test1"
sync_ticks = 20

[storage.mysql]
host = "127.0.0.1"
port = 3306
database = "stoneperms"
username = "stoneperms"
password = "replace-me"
connect_timeout = 5
read_timeout = 10
ssl_ca = ""

[contexts]
server = "test1"
```

On the second server use `storage.server_id = "test2"` and `contexts.server = "test2"`.
`storage.server_id` must be unique and stable for each server. It selects a dedicated
`users_<hash>` table; `storage_servers` records the mapping. Player names, profiles, skins,
online status, and gameplay observations stay local to that server. Shared user permission
nodes use the player's UUID, so all servers must use consistent player identities.
`contexts.server` determines which server-scoped nodes apply and can be changed independently.

Groups, tracks, permission nodes, metadata, prefixes, suffixes, and the audit log are shared.
Nodes without contexts apply everywhere. Use the existing context syntax to restrict any node:

```text
/stoneperms user Steve permission set fly.use true
/stoneperms user Steve permission set kill.use true server=test1
/stoneperms user Steve parent add moderator server=test1
/stoneperms group prefix moderator set 100 "[Moderator]"
/stoneperms user Steve suffix set 100 "[Test2]" server=test2
```

Here `fly.use` applies on both servers, while `kill.use` and the moderator membership apply
only on `test1`. The moderator prefix is stored once and inherited wherever that group applies.
`server=global` is a literal context value; omit the context to make a node global.

Database revisions propagate changes to online players, including their name tags, every
`storage.sync_ticks` (20 ticks by default). Webeditor batches check the shared revision inside
their transaction and reject stale edits. Failed synchronization is retried on the next poll.
Storage connection settings and `storage.server_id` require a restart. Set `ssl_ca` to a trusted
CA certificate file to enable TLS with certificate and hostname verification, using the
[PyMySQL connection options](https://pymysql.readthedocs.io/en/latest/modules/connections.html).

Switching backends does not copy or delete data. The original SQLite file remains intact;
switching back to SQLite reopens it. Provision shared MySQL data before switching an existing
production server. MySQL needs database connectivity; StonePerms never silently falls back to
an independent SQLite database when that connection fails.

The MySQL integration tests use `STONEPERMS_TEST_MYSQL_HOST`, optional
`STONEPERMS_TEST_MYSQL_PORT`, `STONEPERMS_TEST_MYSQL_USER`, and
`STONEPERMS_TEST_MYSQL_PASSWORD`. They create and remove uniquely named test databases, so use
a test account with database creation privileges. Run `python -m unittest discover -s tests -v`.
Without these environment variables, the SQLite tests run and MySQL integration tests are skipped.

## Offline operation and data ownership

StonePerms does not require a website. The default SQLite backend also works without a network
connection; MySQL requires access to the configured database. Permission data lives in the selected
database. The resolver applies defined values to one native Endstone attachment per online
player and omits undefined permissions so Endstone's registered default remains effective.

## Project layout

| Path         | Purpose                                             |
| ------------ | --------------------------------------------------- |
| `src/`       | Python package and Endstone plugin                  |
| `api/`       | TypeScript API, live plugin bridge, and Docker deployment |
| `dashboard/` | Vue dashboard and permission editor                 |

The plugin owns permission data and remains usable by itself. The API owns web accounts, sessions,
memberships, and pairing credentials. Production dashboard files are served by the API from the
same origin.

## License

StonePerms is available under the [MIT license](LICENSE). LuckPerms is not bundled or required.
