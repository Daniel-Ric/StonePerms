const number = (value, fallback) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback
}

export const runtimeConfig = Object.freeze({
  appName: 'StonePerms Control',
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL || '/',
  demoMode: String(import.meta.env.VITE_DEMO_MODE || '').toLowerCase() === 'true',
  pollIntervalMs: number(import.meta.env.VITE_POLL_INTERVAL_MS, 15_000),
  locale: 'en-GB',
})
