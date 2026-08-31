import http from './http'
import { demoApi } from './demo'
import { runtimeConfig } from '@/config/runtime'

const request = async (method, url, options = {}) => {
  const response = await http.request({ method, url, ...options })
  return response.data
}

const endpoint = (path) => `${runtimeConfig.apiBaseUrl.replace(/\/$/, '')}${path}`

const liveApi = {
  health: () => request('get', '/health'),
  publicConfig: () => request('get', '/v1/public-config'),
  session: () => request('get', '/v1/session'),
  me: () => request('get', '/v1/me'),
  login: (payload) => request('post', '/v1/auth/login', { data: payload }),
  loginWithCode: (payload) => request('post', '/v1/auth/code', { data: payload }),
  register: (payload) => request('post', '/v1/auth/register', { data: payload }),
  logout: () => request('post', '/v1/auth/logout'),
  servers: () => request('get', '/v1/servers'),
  server: (id) => request('get', `/v1/servers/${id}`),
  directory: (id) => request('get', `/v1/servers/${id}/directory`),
  displaySettings: (id) => request('get', `/v1/servers/${id}/display`),
  updateDisplaySettings: (id, payload) =>
    request('put', `/v1/servers/${id}/display`, { data: payload }),
  pluginSettings: (id) => request('get', `/v1/servers/${id}/settings`),
  updatePluginSettings: (id, payload) =>
    request('put', `/v1/servers/${id}/settings`, { data: payload }),
  player: (id, identifier) =>
    request('get', `/v1/servers/${id}/players/${encodeURIComponent(identifier)}`),
  playerAvatarUrl: (id, player) => {
    const query = new URLSearchParams({ renderer: '3' })
    if (player.skinHash) query.set('skin', player.skinHash)
    return endpoint(`/v1/servers/${id}/players/${encodeURIComponent(player.id)}/avatar?${query}`)
  },
  createGroup: (id, payload) => request('post', `/v1/servers/${id}/groups`, { data: payload }),
  setGroupWeight: (id, name, weight) =>
    request('patch', `/v1/servers/${id}/groups/${encodeURIComponent(name)}`, { data: { weight } }),
  createTrack: (id, name) => request('post', `/v1/servers/${id}/tracks`, { data: { name } }),
  renameTrack: (id, name, newName) =>
    request('post', `/v1/servers/${id}/tracks/${encodeURIComponent(name)}/rename`, {
      data: { newName },
    }),
  cloneTrack: (id, name, cloneName) =>
    request('post', `/v1/servers/${id}/tracks/${encodeURIComponent(name)}/clone`, {
      data: { cloneName },
    }),
  deleteTrack: (id, name) =>
    request('delete', `/v1/servers/${id}/tracks/${encodeURIComponent(name)}`),
  movePlayer: (id, identifier, track, direction) =>
    request(
      'post',
      `/v1/servers/${id}/players/${encodeURIComponent(identifier)}/tracks/${encodeURIComponent(track)}/${direction}`,
    ),
  pluginAudit: (id, limit = 50) =>
    request('get', `/v1/servers/${id}/plugin-audit`, { params: { limit } }),
  createPairingCode: () => request('post', '/v1/pairing-codes'),
  revokeServer: (id) => request('delete', `/v1/servers/${id}/credential`),
  users: () => request('get', '/v1/users'),
  createUser: (payload) => request('post', '/v1/users', { data: payload }),
  setMembership: (serverId, userId, role) =>
    request('put', `/v1/servers/${serverId}/memberships/${userId}`, { data: { role } }),
  grantMembership: (serverId, payload) =>
    request('post', `/v1/servers/${serverId}/memberships`, { data: payload }),
  removeMembership: (serverId, userId) =>
    request('delete', `/v1/servers/${serverId}/memberships/${userId}`),
  audit: ({ serverId, limit = 50 } = {}) =>
    request('get', '/v1/audit', { params: { ...(serverId ? { serverId } : {}), limit } }),
  createEditorSession: (serverId, payload) =>
    request('post', `/v1/servers/${serverId}/editor/sessions`, { data: payload }),
  applyEditorChanges: (serverId, payload) =>
    request('post', `/v1/servers/${serverId}/editor/changes`, { data: payload }),
}

export const stonePermsApi = runtimeConfig.demoMode ? demoApi : liveApi
