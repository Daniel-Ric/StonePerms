export const NODE_TYPES = ['permission', 'parent', 'prefix', 'suffix', 'meta']

export function clone(value) {
  return JSON.parse(JSON.stringify(value))
}

export function stable(value) {
  if (Array.isArray(value)) return `[${value.map(stable).join(',')}]`
  if (value && typeof value === 'object')
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${stable(value[key])}`)
      .join(',')}}`
  return JSON.stringify(value)
}

export function changedSubjects(session, baseline) {
  return session.subjects
    .filter(
      (subject, index) => stable(subject.nodes) !== stable(baseline.subjects[index]?.nodes || []),
    )
    .map(({ type, id, nodes }) => ({ type, id, nodes: clone(nodes) }))
}

export function changedTracks(session, baseline) {
  return session.tracks
    .filter((track, index) => stable(track.groups) !== stable(baseline.tracks[index]?.groups || []))
    .map(({ name, groups }) => ({ name, groups: [...groups] }))
}

export function nodeSlot(node) {
  const contexts = [...node.contexts]
    .map(({ key, value }) => `${key}=${value}`)
    .sort()
    .join('&')
  return [node.type, node.key, contexts, node.expiresAt ?? '', node.priority].join('|')
}

export function nodeTitle(node) {
  if (node.type === 'permission') return node.key
  if (node.type === 'parent') return `inherits ${node.key}`
  if (node.type === 'meta') return `${node.key} = ${node.value}`
  return `${node.type} · ${node.value}`
}

export function blankNode(type = 'permission') {
  return {
    type,
    key: type === 'prefix' || type === 'suffix' ? type : '',
    value: type === 'permission' || type === 'parent' ? 'true' : '',
    contexts: [],
    expiresAt: null,
    priority: 0,
  }
}

export function normalizeNode(input) {
  const type = String(input.type)
  const contexts = (input.contexts || [])
    .map(({ key, value }) => ({
      key: String(key).trim().toLowerCase(),
      value: String(value).trim().toLowerCase(),
    }))
    .filter(({ key, value }) => key && value)
    .sort(
      (left, right) => left.key.localeCompare(right.key) || left.value.localeCompare(right.value),
    )
  const node = {
    type,
    key: type === 'prefix' || type === 'suffix' ? type : String(input.key).trim().toLowerCase(),
    value:
      type === 'permission'
        ? String(input.value).toLowerCase()
        : type === 'parent'
          ? 'true'
          : String(input.value),
    contexts,
    expiresAt: input.expiresAt ? Number(input.expiresAt) : null,
    priority: type === 'prefix' || type === 'suffix' ? Number(input.priority || 0) : 0,
  }
  if (!node.key) throw new Error('A node key is required.')
  if (!node.value) throw new Error('A node value is required.')
  if (new Set(contexts.map(({ key, value }) => `${key}\u0000${value}`)).size !== contexts.length)
    throw new Error('Duplicate context pairs are not allowed.')
  return node
}

export function expiryInput(timestamp) {
  if (!timestamp) return ''
  const date = new Date(timestamp * 1000)
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
}

export function expiryTimestamp(value) {
  if (!value) return null
  const timestamp = Math.floor(new Date(value).getTime() / 1000)
  if (!Number.isFinite(timestamp) || timestamp <= Date.now() / 1000)
    throw new Error('Expiry must be in the future.')
  return timestamp
}
