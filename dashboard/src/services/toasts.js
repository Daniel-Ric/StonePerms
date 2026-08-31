import { reactive, readonly } from 'vue'

const state = reactive({ items: [] })
let sequence = 0

function dismiss(id) {
  const index = state.items.findIndex((item) => item.id === id)
  if (index >= 0) state.items.splice(index, 1)
}

function show(message, options = {}) {
  const text = String(message || '').trim()
  if (!text) return null
  const type = options.type || 'info'
  const duplicate = state.items.find((item) => item.message === text && item.type === type)
  if (duplicate) return duplicate.id
  const id = ++sequence
  state.items.push({
    id,
    type,
    title:
      options.title ||
      { success: 'Completed', error: 'Action failed', warning: 'Attention', info: 'StonePerms' }[
        type
      ],
    message: text,
  })
  while (state.items.length > 4) dismiss(state.items[0].id)
  if (options.duration !== 0)
    window.setTimeout(() => dismiss(id), options.duration ?? (type === 'error' ? 7000 : 4200))
  return id
}

export const toasts = {
  state: readonly(state),
  dismiss,
  show,
  success: (message, options = {}) => show(message, { ...options, type: 'success' }),
  error: (message, options = {}) => show(message, { ...options, type: 'error' }),
  warning: (message, options = {}) => show(message, { ...options, type: 'warning' }),
  info: (message, options = {}) => show(message, { ...options, type: 'info' }),
}
