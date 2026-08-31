import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { stonePermsApi } from '@/services/api'
import { runtimeConfig } from '@/config/runtime'

export const useStonePermsStore = defineStore('stoneperms', () => {
  const user = ref(null)
  const servers = ref([])
  const health = ref(null)
  const publicConfig = ref({ registrationEnabled: false })
  const initialized = ref(false)
  const loading = ref(false)
  const error = ref('')
  const lastUpdated = ref(null)
  const selectedServerId = ref(readStorage('stoneperms:selected-server') || '')

  const authenticated = computed(() => Boolean(user.value))
  const registrationEnabled = computed(() => Boolean(publicConfig.value.registrationEnabled))
  const selectedServer = computed(
    () =>
      servers.value.find((server) => server.id === selectedServerId.value) ||
      servers.value[0] ||
      null,
  )
  const onlineServers = computed(() =>
    servers.value.filter((server) => server.status?.ready && !server.revokedAt),
  )

  function selectServer(id) {
    selectedServerId.value = id
    writeStorage('stoneperms:selected-server', id)
  }

  function canEdit(server = selectedServer.value) {
    return ['owner', 'admin', 'editor'].includes(server?.role)
  }

  function canOwn(server = selectedServer.value) {
    return server?.role === 'owner'
  }

  async function initialize() {
    if (initialized.value) return authenticated.value
    try {
      publicConfig.value = await stonePermsApi.publicConfig()
    } catch {
      publicConfig.value = { registrationEnabled: false }
    }
    try {
      const result = await stonePermsApi.session()
      user.value = result.user
      if (user.value) await refresh()
    } catch {
      user.value = null
    } finally {
      initialized.value = true
    }
    return authenticated.value
  }

  async function login(username, password) {
    const result = await stonePermsApi.login({ username, password })
    user.value = result.user
    initialized.value = true
    await refresh()
    return result
  }

  async function loginWithCode(code) {
    const result = await stonePermsApi.loginWithCode({ code })
    user.value = result.user
    initialized.value = true
    await refresh()
    return result
  }

  async function register(username, password) {
    const result = await stonePermsApi.register({ username, password })
    user.value = result.user
    initialized.value = true
    await refresh()
    return result
  }

  async function logout() {
    try {
      await stonePermsApi.logout()
    } finally {
      clearSession()
    }
  }

  function clearSession() {
    user.value = null
    servers.value = []
    health.value = null
    initialized.value = true
  }

  async function refresh({ quiet = false } = {}) {
    if (!quiet) loading.value = true
    error.value = ''
    try {
      const [healthResult, serversResult] = await Promise.all([
        stonePermsApi.health(),
        stonePermsApi.servers(),
      ])
      health.value = healthResult
      servers.value = serversResult.servers || []
      if (!servers.value.some((server) => server.id === selectedServerId.value) && servers.value[0])
        selectServer(servers.value[0].id)
      lastUpdated.value = new Date()
    } catch (cause) {
      error.value = cause.userMessage || cause.message
      throw cause
    } finally {
      loading.value = false
    }
  }

  return {
    user,
    servers,
    health,
    publicConfig,
    initialized,
    loading,
    error,
    lastUpdated,
    selectedServerId,
    selectedServer,
    onlineServers,
    authenticated,
    registrationEnabled,
    selectServer,
    canEdit,
    canOwn,
    initialize,
    login,
    loginWithCode,
    register,
    logout,
    clearSession,
    refresh,
    demoMode: runtimeConfig.demoMode,
  }
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
    window.localStorage.setItem(key, value)
  } catch {
    return
  }
}
