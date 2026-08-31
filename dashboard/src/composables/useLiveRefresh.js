import { onBeforeUnmount, onMounted, watch } from 'vue'
import { useStonePermsStore } from '@/stores/stoneperms'

export function useLiveRefresh(refresh) {
  const store = useStonePermsStore()
  let stopWatching
  let inFlight = null
  let queued = false

  async function run() {
    if (document.visibilityState !== 'visible') return
    if (inFlight) {
      queued = true
      return inFlight
    }

    inFlight = (async () => {
      do {
        queued = false
        try {
          await refresh()
        } catch {
          if (!queued) return
        }
      } while (queued)
    })()

    try {
      await inFlight
    } finally {
      inFlight = null
    }
  }

  onMounted(() => {
    stopWatching = watch(
      () => store.lastUpdated,
      () => void run(),
    )
  })
  onBeforeUnmount(() => stopWatching?.())

  return run
}
