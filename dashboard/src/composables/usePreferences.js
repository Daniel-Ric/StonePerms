import { computed, readonly, ref } from 'vue'
import { runtimeConfig } from '@/config/runtime'

export const THEME_OPTIONS = Object.freeze(['system', 'dark', 'light'])
export const REFRESH_INTERVAL_OPTIONS = Object.freeze([0, 15_000, 30_000, 60_000])

const STORAGE_KEYS = Object.freeze({
  theme: 'stoneperms:theme',
  refreshInterval: 'stoneperms:refresh-interval',
  sidebarCondensed: 'stoneperms:sidebar-condensed',
  reduceMotion: 'stoneperms:reduce-motion',
})

function readStorage(key) {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

function writeStorage(key, value) {
  try {
    window.localStorage.setItem(key, String(value))
  } catch {
    return
  }
}

export function normalizeTheme(value) {
  return THEME_OPTIONS.includes(value) ? value : 'system'
}

export function normalizeRefreshInterval(value, fallback = runtimeConfig.pollIntervalMs) {
  if (value === null || value === undefined || value === '') return fallback
  const parsed = Number(value)
  return REFRESH_INTERVAL_OPTIONS.includes(parsed) ? parsed : fallback
}

const theme = ref(normalizeTheme(readStorage(STORAGE_KEYS.theme)))
const refreshIntervalMs = ref(
  normalizeRefreshInterval(readStorage(STORAGE_KEYS.refreshInterval), runtimeConfig.pollIntervalMs),
)
const sidebarCondensed = ref(readStorage(STORAGE_KEYS.sidebarCondensed) === 'true')
const reduceMotion = ref(readStorage(STORAGE_KEYS.reduceMotion) === 'true')
const systemTheme = ref('dark')
const systemReducedMotion = ref(false)
const resolvedTheme = computed(() => (theme.value === 'system' ? systemTheme.value : theme.value))
const effectiveReducedMotion = computed(() => reduceMotion.value || systemReducedMotion.value)

let initialised = false
let colourSchemeQuery
let reducedMotionQuery

function syncDocumentPreferences() {
  const root = document.documentElement
  root.dataset.theme = resolvedTheme.value
  root.dataset.motion = effectiveReducedMotion.value ? 'reduced' : 'full'
  root.style.colorScheme = resolvedTheme.value
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute('content', resolvedTheme.value === 'light' ? '#f3f1e7' : '#0d1216')
  window.dispatchEvent(
    new CustomEvent('stoneperms:preferences-changed', {
      detail: {
        theme: resolvedTheme.value,
        reducedMotion: effectiveReducedMotion.value,
      },
    }),
  )
}

function updateSystemTheme(event) {
  systemTheme.value = event.matches ? 'dark' : 'light'
  if (theme.value === 'system') syncDocumentPreferences()
}

function updateSystemMotion(event) {
  systemReducedMotion.value = event.matches
  syncDocumentPreferences()
}

export function initialisePreferences() {
  if (initialised) return
  initialised = true
  colourSchemeQuery = window.matchMedia('(prefers-color-scheme: dark)')
  reducedMotionQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
  systemTheme.value = colourSchemeQuery.matches ? 'dark' : 'light'
  systemReducedMotion.value = reducedMotionQuery.matches
  colourSchemeQuery.addEventListener('change', updateSystemTheme)
  reducedMotionQuery.addEventListener('change', updateSystemMotion)
  syncDocumentPreferences()
}

export function usePreferences() {
  initialisePreferences()

  function setTheme(value) {
    theme.value = normalizeTheme(value)
    writeStorage(STORAGE_KEYS.theme, theme.value)
    syncDocumentPreferences()
  }

  function setRefreshInterval(value) {
    refreshIntervalMs.value = normalizeRefreshInterval(value)
    writeStorage(STORAGE_KEYS.refreshInterval, refreshIntervalMs.value)
  }

  function setSidebarCondensed(value) {
    sidebarCondensed.value = Boolean(value)
    writeStorage(STORAGE_KEYS.sidebarCondensed, sidebarCondensed.value)
  }

  function setReduceMotion(value) {
    reduceMotion.value = Boolean(value)
    writeStorage(STORAGE_KEYS.reduceMotion, reduceMotion.value)
    syncDocumentPreferences()
  }

  return {
    theme: readonly(theme),
    resolvedTheme: readonly(resolvedTheme),
    refreshIntervalMs: readonly(refreshIntervalMs),
    sidebarCondensed: readonly(sidebarCondensed),
    reduceMotion: readonly(reduceMotion),
    effectiveReducedMotion: readonly(effectiveReducedMotion),
    setTheme,
    setRefreshInterval,
    setSidebarCondensed,
    setReduceMotion,
  }
}
