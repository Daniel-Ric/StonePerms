<p align="center">
  <img src="../dashboard/public/stoneperms-logo.png" alt="StonePerms logo" width="144">
</p>

<h1 align="center">StonePerms API</h1>

<p align="center">
  The API and live bridge between StonePerms servers and the web dashboard.
</p>

<p align="center">
  <img alt="StonePerms API 0.8.11" src="https://img.shields.io/badge/API-0.8.11-d8d58d?style=flat-square">
  <img alt="Node.js 22.13 or newer" src="https://img.shields.io/badge/Node.js-22.13%2B-68737a?style=flat-square&logo=node.js&logoColor=white">
  <img alt="TypeScript" src="https://img.shields.io/badge/TypeScript-7-68737a?style=flat-square&logo=typescript&logoColor=white">
  <a href="../LICENSE"><img alt="MIT license" src="https://img.shields.io/badge/License-MIT-68737a?style=flat-square"></a>
</p>

<p align="center">
  <a href="#first-start-with-nodejs">Node.js setup</a> ·
  <a href="#first-start-with-docker-compose">Docker setup</a> ·
  <a href="#pair-a-server">Pairing</a> ·
  <a href="#api-surface-in-v1">Routes</a> ·
  <a href="../README.md">Main project</a>
</p>

The API can be deployed independently from the Endstone plugin. It stores web accounts, sessions,
server memberships, pairing credentials, and its own audit log. Groups, nodes, tracks, and the
permission audit stay in the plugin database; the API never reads or writes `stoneperms.db`.
Production deployments also serve the compiled Vue dashboard from the same HTTPS origin.

## Features

- web accounts with server-specific `owner`, `admin`, `editor`, and `viewer` roles
- optional public account registration, disabled by default for self-hosted installations
- one-time server pairing, short-lived login codes, and an outbound authenticated plugin connection
- browser sessions with CSRF protection and a separate API audit log
- proxied permission, player, group, track, display, and plugin-setting operations
- locally rendered player heads with controlled external fallbacks for unsupported skin data
- OpenAPI documentation at `/docs` and a multi-stage Docker image for self-hosting

## Requirements

- Node.js 22.13 or newer (Node.js 24 LTS is recommended)
- HTTPS at the reverse proxy for every non-local deployment
- A persistent directory for the API SQLite database

## First start with Node.js

Build the dashboard first, copy `.env.example` to `.env`, replace the bootstrap password, then run:

```text
cd ../dashboard
npm ci
npm run build
cd ../api
npm ci
npm run build
npm start
```

Open `http://127.0.0.1:3210` for the dashboard. Interactive OpenAPI documentation remains available
at `/docs`. Remove the two bootstrap variables after the first successful start; they are never
used again while the database already contains a user.

For development, use `npm run dev`. Run `npm run typecheck` and `npm run build` before a release.

## First start with Docker Compose

Create `api/.env` with at least:

```text
STONEPERMS_BOOTSTRAP_PASSWORD=a-long-unique-password
STONEPERMS_PUBLIC_URL=https://permissions.example.com
STONEPERMS_ALLOWED_ORIGINS=https://permissions.example.com
STONEPERMS_COOKIE_SECURE=true
STONEPERMS_TRUST_PROXY=true
```

Then run `docker compose up -d --build` inside `api/`. The multi-stage image builds both dashboard
and API. The compose file publishes only to localhost; place Caddy, nginx, Traefik, or another TLS
reverse proxy in front of it.

For the public service at `stoneperms.spindexgfx.com`, start with `.env.public.example`. Replace the
bootstrap password before the first start. Public registration is enabled only in that production
example and remains off in the regular self-hosted configuration.

## Pair a server

Sign in to the dashboard, open **Servers**, choose **Pair a server**, and run the displayed command
from the Endstone console. For scripts, the following PowerShell example logs in, preserves the
session cookie, and creates a one-time pairing code:

```powershell
$login = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:3210/v1/auth/login `
  -ContentType application/json -Body '{"username":"admin","password":"your-password"}' `
  -SessionVariable StonePermsSession
$pairing = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:3210/v1/pairing-codes `
  -WebSession $StonePermsSession -Headers @{"X-CSRF-Token"=$login.csrfToken} `
  -ContentType application/json -Body '{}'
$pairing
```

Within ten minutes, run this from the Endstone console:

```text
stoneperms web pair http://127.0.0.1:3210 ABCD-EFGH-JKLM-NPQR "My Server"
stoneperms web status
```

Use an `https://` API URL when the server is on another host. `stoneperms web unpair` revokes the
credential at the API when reachable and always removes the local copy.

The public service does not require an API address in the command:

```text
stoneperms web pair ABCD-EFGH-JKLM-NPQR "My Server"
```

## Security model

- Passwords use `scrypt`; opaque session, CSRF, pairing, and server tokens come from a CSPRNG.
- Only SHA-256 digests of opaque credentials are stored in the API database.
- Browser mutations require a strict SameSite cookie and matching cookie/header CSRF token.
- Server tokens are sent only as `Authorization: Bearer` credentials during the outbound plugin
  connection. Tokens never appear in URLs or logs.
- Pairing codes are single-use, expire after ten minutes by default, and are rate-limited.
- Server roles are `owner`, `admin`, `editor`, and `viewer`. The system owner can create local
  accounts. Public self-registration is available only when explicitly enabled. Only a server owner
  can change memberships or revoke its plugin credential.
- Request bodies and WebSocket messages are limited to 1 MiB. Plugin calls use fixed timeouts.
- Standard player heads are rendered server-side from the skin captured by Endstone. Character
  Creator skins do not expose their geometry through Endstone, so the API resolves their XUID and
  converted texture through GeyserMC, downloads that PNG from the official Minecraft texture CDN,
  and renders the face plus hat layer itself. The fixed `STONEPERMS_AVATAR_PROVIDER_URL` (MC Heads
  by default) remains the final fallback. Provider URLs and identifiers are never controlled by
  browser input. Set the variable to `off` to disable all external lookups and use local faces only.
  With external lookups enabled, a player's gamertag or XUID is disclosed to GeyserMC and, only if
  needed, to the configured fallback provider when an avatar is requested.

Back up the API database and the plugin database separately. Protect the Endstone plugin data
directory because `config.toml` contains the server credential required for automatic reconnects.

## API surface in v1

| Area              | Routes                                                                          |
| ----------------- | ------------------------------------------------------------------------------- |
| Health            | `GET /health`, `GET /ready`, `GET /v1/public-config`                            |
| Authentication    | registration, password or one-time-code login, logout, and current-user routes  |
| Local users       | `GET /v1/users`, `POST /v1/users`                                               |
| Pairing           | pairing, plugin credentials, and owner login-code issuance                      |
| Plugin transport  | `GET /v1/plugin/connect` (WebSocket), `DELETE /v1/plugin/credential`            |
| Servers           | `GET /v1/servers`, `GET /v1/servers/:serverId`, credential revocation           |
| Memberships       | owner-only create/update and delete routes below each server                    |
| Directory         | groups, tracks, known players, player profiles, inspection, and proxied avatars |
| Display           | `GET` and owner/admin `PUT /v1/servers/:serverId/display`                       |
| Plugin settings   | `GET` and owner/admin `PUT /v1/servers/:serverId/settings`                      |
| Groups and tracks | group create/weight, track create/rename/clone/delete, promote/demote           |
| Editor            | read-only or writable snapshot sessions and atomically applied changesets       |
| Audit             | `GET /v1/audit` for the API and per-server plugin permission audit              |

The Vue dashboard consumes only these browser routes. It never knows the plugin server token and
never connects to the plugin WebSocket endpoint.

## Project links

- [StonePerms plugin](../README.md)
- [Dashboard development](../dashboard/README.md)
- [MIT license](../LICENSE)
