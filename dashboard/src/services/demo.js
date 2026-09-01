const now = Math.floor(Date.now() / 1000)
const serverId = 'b9f15baf-5b68-4cb8-bd78-78ad5e589f55'
const secondServerId = '7d82c610-a332-4ac3-8d04-85048bf20a66'

const state = {
  user: { id: 'demo-owner', username: 'demo', systemRole: 'owner' },
  users: [
    {
      id: 'demo-owner',
      username: 'demo',
      systemRole: 'owner',
      createdAt: now - 864000,
      disabledAt: null,
    },
    {
      id: 'demo-editor',
      username: 'buildteam',
      systemRole: 'user',
      createdAt: now - 604800,
      disabledAt: null,
    },
  ],
  servers: [
    {
      id: serverId,
      instanceId: '4e2b74cb-41ca-4b7c-ad93-7def73bccd14',
      name: 'Survival Network',
      pluginVersion: '0.8.12',
      protocolVersion: 1,
      createdAt: now - 1209600,
      lastSeenAt: now - 3,
      revokedAt: null,
      role: 'owner',
      status: { online: true, ready: true, connectedAt: now - 20342 },
    },
    {
      id: secondServerId,
      instanceId: 'd989d008-4d26-4501-a97d-ab9b262183f7',
      name: 'Creative Lab',
      pluginVersion: '0.8.12',
      protocolVersion: 1,
      createdAt: now - 432000,
      lastSeenAt: now - 14,
      revokedAt: null,
      role: 'admin',
      status: { online: true, ready: true, connectedAt: now - 7601 },
    },
    {
      id: '7d0b96dc-c85c-4494-b0a1-3e1309cdb668',
      instanceId: '792d14cc-0774-44db-9e3c-f9576f038a94',
      name: 'Event Realm',
      pluginVersion: '0.5.0',
      protocolVersion: 1,
      createdAt: now - 2592000,
      lastSeenAt: now - 3600,
      revokedAt: null,
      role: 'viewer',
      status: { online: false, ready: false, connectedAt: null },
    },
  ],
  audit: [
    {
      id: 18,
      actorUserId: 'demo-owner',
      actorUsername: 'demo',
      serverId,
      action: 'editor.changes.apply',
      target: null,
      outcome: 'success',
      createdAt: now - 180,
    },
    {
      id: 17,
      actorUserId: 'demo-owner',
      actorUsername: 'demo',
      serverId,
      action: 'editor.session.create',
      target: null,
      outcome: 'success',
      createdAt: now - 242,
    },
    {
      id: 16,
      actorUserId: 'demo-owner',
      actorUsername: 'demo',
      serverId: secondServerId,
      action: 'membership.set',
      target: 'buildteam:editor',
      outcome: 'success',
      createdAt: now - 4000,
    },
    {
      id: 15,
      actorUserId: null,
      actorUsername: null,
      serverId,
      action: 'plugin.pair',
      target: 'Survival Network',
      outcome: 'success',
      createdAt: now - 1209600,
    },
  ],
}

let demoDisplaySettings = {
  chat: {
    enabled: false,
    format: '{prefix}§f{name}{suffix} §8» §f{message}',
    placeholders: ['prefix', 'name', 'suffix', 'message'],
  },
  nametag: {
    enabled: false,
    format: '{prefix}§f{name}{suffix}',
    placeholders: ['prefix', 'name', 'suffix'],
  },
}

let demoPluginSettings = {
  configured: {
    defaultGroup: 'default',
    serverContext: 'survival',
    includeDeviceOsContext: false,
    includeLocaleContext: false,
    expiryCheckSeconds: 1,
    catalogRefreshSeconds: 5,
    debug: false,
  },
  active: {
    defaultGroup: 'default',
    serverContext: 'survival',
    includeDeviceOsContext: false,
    includeLocaleContext: false,
    expiryCheckSeconds: 1,
    catalogRefreshSeconds: 5,
    debug: false,
  },
  restartRequired: [],
  limits: {
    expiryCheckSeconds: { minimum: 1, maximum: 60 },
    catalogRefreshSeconds: { minimum: 1, maximum: 300 },
  },
}

const node = (type, key, value, priority = 0, contexts = [], expiresAt = null) => ({
  type,
  key,
  value,
  contexts,
  expiresAt,
  priority,
})

function editorSession(users = []) {
  const userSubjects = users.map((identifier) => ({
    type: 'user',
    id: identifier.includes('-') ? identifier : `demo-${identifier.toLowerCase()}`,
    name: identifier.includes('-') ? 'Demo Player' : identifier,
    xuid: '2535420012345678',
    nodes: [node('parent', 'member', 'true'), node('meta', 'chat-color', 'gold')],
  }))
  return {
    schema: 'stoneperms.editor/session',
    version: 1,
    sessionId: `demo-session-${crypto.randomUUID()}`,
    baseRevision: 42,
    createdAt: now,
    expiresAt: now + 900,
    scope: { users, groups: true, tracks: true },
    metadata: {
      product: 'StonePerms',
      productVersion: '0.8.12',
      defaultGroup: 'default',
      groups: [
        { name: 'default', displayName: 'Default', weight: 0 },
        { name: 'member', displayName: 'Member', weight: 10 },
        { name: 'vip', displayName: 'VIP', weight: 50 },
        { name: 'moderator', displayName: 'Moderator', weight: 100 },
        { name: 'administrator', displayName: 'Administrator', weight: 200 },
      ],
    },
    subjects: [
      {
        type: 'group',
        id: 'default',
        displayName: 'Default',
        weight: 0,
        nodes: [node('permission', 'minecraft.command.help', 'true')],
      },
      {
        type: 'group',
        id: 'member',
        displayName: 'Member',
        weight: 10,
        nodes: [node('parent', 'default', 'true'), node('prefix', 'prefix', '[Member] ', 10)],
      },
      {
        type: 'group',
        id: 'vip',
        displayName: 'VIP',
        weight: 50,
        nodes: [
          node('parent', 'member', 'true'),
          node('permission', 'essentials.fly', 'true'),
          node('prefix', 'prefix', '[VIP] ', 50),
        ],
      },
      {
        type: 'group',
        id: 'moderator',
        displayName: 'Moderator',
        weight: 100,
        nodes: [
          node('parent', 'member', 'true'),
          node('permission', 'minecraft.command.kick', 'true'),
          node('permission', 'minecraft.command.ban', 'false', 0, [
            { key: 'server', value: 'survival' },
          ]),
          node('prefix', 'prefix', '[Mod] ', 100),
        ],
      },
      {
        type: 'group',
        id: 'administrator',
        displayName: 'Administrator',
        weight: 200,
        nodes: [
          node('parent', 'moderator', 'true'),
          node('permission', '*', 'true'),
          node('prefix', 'prefix', '[Admin] ', 200),
        ],
      },
      ...userSubjects,
    ],
    tracks: [
      { name: 'staff', groups: ['member', 'moderator', 'administrator'] },
      { name: 'donor', groups: ['member', 'vip'] },
    ],
    knownPermissions: [
      '*',
      'essentials.fly',
      'minecraft.command.ban',
      'minecraft.command.help',
      'minecraft.command.kick',
      'stoneperms.command.admin',
    ],
    potentialContexts: [
      { key: 'server', values: ['global', 'survival', 'creative'] },
      { key: 'world', values: ['overworld', 'nether', 'the_end'] },
      { key: 'gamemode', values: ['survival', 'creative', 'adventure'] },
    ],
  }
}

const pause = (value) =>
  new Promise((resolve) => window.setTimeout(() => resolve(structuredClone(value)), 120))

const demoDirectory = () => {
  const snapshot = editorSession([])
  return {
    revision: snapshot.baseRevision,
    defaultGroup: snapshot.metadata.defaultGroup,
    groups: snapshot.metadata.groups,
    tracks: snapshot.tracks,
    users: [
      {
        id: 'a72a4c5d-9e54-4b62-984a-2b8decb63239',
        name: 'Alex',
        xuid: '2535420012345678',
        online: true,
        lastSeenAt: now - 12,
        deviceOs: 'Windows',
        gameVersion: '1.21.100',
        skinHash: 'demo-alex',
      },
      {
        id: '370e3ba6-f1de-42c4-8dd6-75bb3dd60784',
        name: 'BuilderBee',
        xuid: '2535420098765432',
        online: false,
        lastSeenAt: now - 8640,
        deviceOs: 'Android',
        gameVersion: '1.21.100',
        skinHash: 'demo-builder',
      },
    ],
  }
}

const demoPlayer = (identifier) => ({
  user: {
    id: identifier.includes('-') ? identifier : 'a72a4c5d-9e54-4b62-984a-2b8decb63239',
    name: identifier.includes('-') ? 'Alex' : identifier,
    xuid: '2535420012345678',
    online: true,
    lastSeenAt: now - 12,
    deviceOs: 'Windows',
    gameVersion: '1.21.100',
    skinHash: 'demo-alex',
  },
  profile: {
    locale: 'de_DE',
    deviceOs: 'Windows',
    gameVersion: '1.21.100',
    gameMode: 'survival',
    pingMs: 34,
    totalExp: 2840,
    expLevel: 27,
    skinId: 'demo.standard.alex',
    skinHash: 'demo-alex',
    skinWidth: 64,
    skinHeight: 64,
    capeId: null,
    firstSeenAt: now - 864000,
    lastSeenAt: now - 12,
    lastJoinedAt: now - 3600,
    lastQuitAt: now - 7200,
    skinUpdatedAt: now - 43200,
    online: true,
  },
  nodes: [
    node('parent', 'member', 'true'),
    node('meta', 'chat-color', 'gold'),
    node('permission', 'essentials.home', 'true'),
  ],
  effectiveGroups: ['default', 'member'],
  primaryGroup: 'member',
  prefix: '[Member] ',
  suffix: null,
  meta: { 'chat-color': 'gold' },
  tracks: { staff: ['member'] },
})

export const demoApi = {
  health: () => pause({ status: 'ok' }),
  publicConfig: () => pause({ registrationEnabled: false }),
  session: () => pause({ user: state.user }),
  me: () => pause({ user: state.user }),
  login: () => pause({ user: state.user, csrfToken: 'demo', expiresAt: now + 43200 }),
  logout: () => pause(null),
  servers: () => pause({ servers: state.servers }),
  server: (id) =>
    pause({
      server: state.servers.find((item) => item.id === id),
      memberships: [
        { userId: 'demo-owner', username: 'demo', role: 'owner' },
        { userId: 'demo-editor', username: 'buildteam', role: 'editor' },
      ],
    }),
  directory: () => pause(demoDirectory()),
  displaySettings: () => pause(demoDisplaySettings),
  updateDisplaySettings: (_id, payload) => {
    demoDisplaySettings = {
      chat: {
        enabled: payload.chatEnabled,
        format: payload.chatFormat,
        placeholders: ['prefix', 'name', 'suffix', 'message'],
      },
      nametag: {
        enabled: payload.nametagEnabled,
        format: payload.nametagFormat,
        placeholders: ['prefix', 'name', 'suffix'],
      },
    }
    return pause(demoDisplaySettings)
  },
  pluginSettings: () => pause(demoPluginSettings),
  updatePluginSettings: (_id, payload) => {
    const restartRequired = ['defaultGroup', 'expiryCheckSeconds', 'catalogRefreshSeconds'].filter(
      (key) => payload[key] !== demoPluginSettings.active[key],
    )
    demoPluginSettings = {
      ...demoPluginSettings,
      configured: { ...payload },
      active: {
        ...demoPluginSettings.active,
        serverContext: payload.serverContext,
        includeDeviceOsContext: payload.includeDeviceOsContext,
        includeLocaleContext: payload.includeLocaleContext,
        debug: payload.debug,
      },
      restartRequired,
    }
    return pause(demoPluginSettings)
  },
  player: (_id, identifier) => pause(demoPlayer(identifier)),
  playerAvatarUrl: () => '/stoneperms-logo.png',
  createGroup: (_id, payload) =>
    pause({
      name: payload.name,
      displayName: payload.displayName || payload.name,
      weight: payload.weight,
    }),
  setGroupWeight: (_id, name, weight) => pause({ name, displayName: name, weight }),
  deleteGroup: () => pause(null),
  createTrack: (_id, name) => pause({ name, groups: [] }),
  renameTrack: (_id, _name, newName) => pause({ name: newName, groups: [] }),
  cloneTrack: (_id, _name, cloneName) => pause({ name: cloneName, groups: ['member', 'vip'] }),
  deleteTrack: () => pause(null),
  movePlayer: (_id, _identifier, track, direction) =>
    pause({
      action: direction,
      status: 'success',
      track,
      groupFrom: 'member',
      groupTo: direction === 'promote' ? 'moderator' : null,
      changed: true,
    }),
  pluginAudit: (_id, limit = 50) =>
    pause({
      entries: state.audit.slice(0, limit).map((entry) => ({
        id: entry.id,
        created_at: entry.createdAt,
        actor: entry.actorUsername || 'plugin',
        action: entry.action,
        subject_type: null,
        subject_id: null,
        details: {},
      })),
    }),
  createPairingCode: () => pause({ code: 'DEMO-STON-PERM-2026', expiresAt: now + 600 }),
  revokeServer: () => pause(null),
  deleteServer: (id) => {
    state.servers = state.servers.filter((server) => server.id !== id)
    return pause(null)
  },
  legacyServers: () => pause({ servers: [] }),
  recoverLegacyServer: () => pause(null),
  users: () => pause({ users: state.users }),
  createUser: (payload) =>
    pause({
      user: {
        id: crypto.randomUUID(),
        username: payload.username,
        systemRole: 'user',
        createdAt: now,
        disabledAt: null,
      },
    }),
  setMembership: (_server, userId, role) => pause({ userId, role }),
  grantMembership: (_server, payload) =>
    pause({ userId: 'demo-invited', username: payload.username, role: payload.role }),
  removeMembership: () => pause(null),
  audit: ({ limit = 50 } = {}) => pause({ entries: state.audit.slice(0, limit) }),
  createEditorSession: (_server, payload) => pause(editorSession(payload.users || [])),
  applyEditorChanges: (_server, payload) =>
    pause({
      schema: 'stoneperms.editor/result',
      version: 1,
      sessionId: payload.sessionId,
      baseRevision: payload.baseRevision,
      revision: payload.baseRevision + 1,
      changed: true,
      changedSubjects: payload.subjects.length,
      changedTracks: payload.tracks.length,
      nodesAdded: 2,
      nodesRemoved: 1,
    }),
}
