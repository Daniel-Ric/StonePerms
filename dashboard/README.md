<p align="center">
  <img src="public/stoneperms-logo.png" alt="StonePerms logo" width="144">
</p>

<h1 align="center">StonePerms Dashboard</h1>

<p align="center">
  Web administration and permission editing for connected StonePerms servers.
</p>

<p align="center">
  <img alt="StonePerms dashboard 0.8.11" src="https://img.shields.io/badge/Dashboard-0.8.11-d8d58d?style=flat-square">
  <img alt="Vue 3" src="https://img.shields.io/badge/Vue-3-68737a?style=flat-square&logo=vuedotjs&logoColor=white">
  <img alt="Vite 8" src="https://img.shields.io/badge/Vite-8-68737a?style=flat-square&logo=vite&logoColor=white">
  <a href="../LICENSE"><img alt="MIT license" src="https://img.shields.io/badge/License-MIT-68737a?style=flat-square"></a>
</p>

<p align="center">
  <a href="#features">Features</a> ·
  <a href="#development">Development</a> ·
  <a href="#production-build">Production build</a> ·
  <a href="../api/README.md">API setup</a> ·
  <a href="../README.md">Main project</a>
</p>

The dashboard is a Vue 3 app built with custom CSS, Pinia, Vue Router, Axios, GSAP, and Apache
ECharts. Production files are served by the Node.js API from the same origin. The browser uses its
own authenticated session and never receives the plugin credential or opens the plugin connection.

## Features

- overview and activity chart for connected servers
- player profiles with locally rendered Minecraft faces
- group, track, chat, nametag, and server-setting management
- permission editor with server-side validation and revision checks
- API and permission audit views
- web-user and per-server team-role administration
- custom selects and date/time controls throughout the editor
- dark, light, and system themes with reduced-motion and compact-navigation settings

## Development

Use Node.js 22.13 or newer (Node.js 24 LTS is recommended), start the API on port `3210`, then run:

```text
npm ci
npm run dev
```

Vite proxies `/v1`, `/health`, and `/ready` to the local API. When using the Vite origin directly,
add `http://127.0.0.1:5173` to `STONEPERMS_ALLOWED_ORIGINS`. To explore every screen without a live
plugin, copy `.env.example` to `.env.local` and set `VITE_DEMO_MODE=true`.

## Production build

```text
npm run lint
npm run format:check
npm run build
```

The build output is written to `dist/`. During an API production build it is copied into the API
image and served from the same origin. The UI is English. Layouts cover desktop, tablet, and compact
mobile widths; animations follow `prefers-reduced-motion`.

## Data ownership

- Web accounts, sessions, memberships, pairing credentials, and API audit belong to Node.js.
- Permission groups, nodes, users, tracks, resolution, and the permission audit belong to the
  Endstone plugin.
- Editor writes are full replacement changesets and commit atomically only when the original
  plugin revision still matches.
- Viewer roles may create read-only snapshots, but cannot apply changes.

## Project links

- [StonePerms plugin](../README.md)
- [API and self-hosting](../api/README.md)
- [MIT license](../LICENSE)
