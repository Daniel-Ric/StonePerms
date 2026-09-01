export function formatDate(value, options = {}) {
  if (value === null || value === undefined) return '—'
  const date =
    value instanceof Date ? value : new Date(typeof value === 'number' ? value * 1000 : value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('en-GB', {
    dateStyle: 'medium',
    timeStyle: 'short',
    ...options,
  }).format(date)
}

export function relativeTime(value) {
  if (!value) return 'Never'
  const seconds = Math.round((Number(value) * 1000 - Date.now()) / 1000)
  const formatter = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })
  if (Math.abs(seconds) < 60) return formatter.format(seconds, 'second')
  if (Math.abs(seconds) < 3600) return formatter.format(Math.round(seconds / 60), 'minute')
  if (Math.abs(seconds) < 86400) return formatter.format(Math.round(seconds / 3600), 'hour')
  return formatter.format(Math.round(seconds / 86400), 'day')
}

export function shortId(value, length = 8) {
  const text = String(value || '')
  return text.length > length ? `${text.slice(0, length)}…` : text || '—'
}

export function titleCase(value) {
  return String(value || '')
    .replace(/[._-]+/g, ' ')
    .replace(/\b\w/g, (character) => character.toUpperCase())
}

const AUDIT_ACTION_LABELS = {
  'auth.login': 'Signed in',
  'auth.logout': 'Signed out',
  'editor.changes.apply': 'Applied editor changes',
  'editor.session.create': 'Opened editor session',
  'group.create': 'Created group',
  'group.delete': 'Deleted group',
  'group.weight.set': 'Changed group weight',
  'membership.remove': 'Removed server access',
  'membership.set': 'Changed server access',
  'pairing.create': 'Created pairing code',
  'plugin.pair': 'Paired server',
  'plugin.settings.update': 'Changed plugin settings',
  'plugin.unpair': 'Unpaired server',
  'server.revoke': 'Revoked server connection',
  'server.delete': 'Deleted server from dashboard',
  'server.legacy.recover': 'Recovered legacy server ownership',
  'auth.code.legacy.upgrade': 'Upgraded legacy account',
  'track.clone': 'Cloned track',
  'track.create': 'Created track',
  'track.delete': 'Deleted track',
  'track.rename': 'Renamed track',
  'user.create': 'Created web user',
}

export function auditActionLabel(value) {
  const action = String(value || '')
  return AUDIT_ACTION_LABELS[action] || titleCase(action)
}
