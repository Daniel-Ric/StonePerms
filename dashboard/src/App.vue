<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import { gsap } from 'gsap'
import AppIcon from '@/components/AppIcon.vue'
import CustomSelect from '@/components/CustomSelect.vue'
import OperatorAvatar from '@/components/OperatorAvatar.vue'
import ToastViewport from '@/components/ToastViewport.vue'
import { usePreferences } from '@/composables/usePreferences'
import { titleCase } from '@/lib/format'
import { useStonePermsStore } from '@/stores/stoneperms'

const route = useRoute()
const router = useRouter()
const store = useStonePermsStore()
const preferences = usePreferences()
const mobileMenu = ref(false)
const profileOpen = ref(false)
const profileMenu = ref(null)
const { effectiveReducedMotion, refreshIntervalMs, sidebarCondensed } = preferences
const page = ref(null)
let poller
let stopRefreshIntervalWatch
let refreshInFlight = null

const globalNavigation = [
  { label: 'Overview', to: '/', icon: 'overview' },
  { label: 'Servers', to: '/servers', icon: 'server' },
  { label: 'Web users', to: '/users', icon: 'users', owner: true },
  { label: 'API audit', to: '/audit', icon: 'audit' },
  { label: 'Settings', to: '/settings', icon: 'settings' },
]
const serverNavigation = [
  { label: 'Server home', suffix: '', icon: 'overview' },
  { label: 'Editor', suffix: '/editor', icon: 'editor' },
  { label: 'Players', suffix: '/players', icon: 'users' },
  { label: 'Groups', suffix: '/groups', icon: 'group' },
  { label: 'Tracks', suffix: '/tracks', icon: 'track' },
  { label: 'Chat & nametags', suffix: '/display', icon: 'display' },
  { label: 'Audit', suffix: '/audit', icon: 'audit' },
  { label: 'Team access', suffix: '/team', icon: 'shield', owner: true },
]
const shellVisible = computed(() => route.name !== 'login')
const selectedServer = computed(() => store.selectedServer)
const serverOptions = computed(() =>
  store.servers.map((server) => ({
    value: server.id,
    label: server.name,
    description: `${server.status?.ready ? 'Connected' : 'Offline'} · ${titleCase(server.role)} access`,
    status: server.status?.ready ? 'online' : 'offline',
  })),
)
const accountRole = computed(() => titleCase(store.user?.systemRole) || 'Account')
const visibleGlobalNavigation = computed(() =>
  globalNavigation.filter((item) => !item.owner || store.user?.systemRole === 'owner'),
)
const visibleServerNavigation = computed(() =>
  serverNavigation.filter((item) => !item.owner || store.canOwn()),
)

function switchServer(id) {
  store.selectServer(id)
  if (route.meta.server) {
    const tail = route.path.replace(/^\/servers\/[^/]+/, '')
    router.push(`/servers/${id}${tail}`)
  }
}

async function refresh() {
  if (!store.authenticated || document.visibilityState !== 'visible') return
  if (refreshInFlight) return refreshInFlight
  refreshInFlight = store.refresh({ quiet: true })
  try {
    await refreshInFlight
  } catch {
    return
  } finally {
    refreshInFlight = null
  }
}

async function logout() {
  profileOpen.value = false
  await store.logout()
  router.push('/login')
}

function toggleSidebar() {
  preferences.setSidebarCondensed(!sidebarCondensed.value)
}

function configureRefreshPoller(interval) {
  window.clearInterval(poller)
  poller = interval > 0 ? window.setInterval(refresh, interval) : undefined
}

function closeProfile(event) {
  if (profileOpen.value && !profileMenu.value?.contains(event.target)) profileOpen.value = false
}

function closeProfileOnEscape(event) {
  if (event.key === 'Escape') profileOpen.value = false
}

function unauthorised() {
  if (route.name === 'login') return
  profileOpen.value = false
  store.clearSession()
  void router.push('/login')
}

onMounted(() => {
  window.addEventListener('stoneperms:unauthorised', unauthorised)
  window.addEventListener('focus', refresh)
  window.addEventListener('online', refresh)
  document.addEventListener('visibilitychange', refresh)
  document.addEventListener('pointerdown', closeProfile)
  document.addEventListener('keydown', closeProfileOnEscape)
  stopRefreshIntervalWatch = watch(refreshIntervalMs, configureRefreshPoller, { immediate: true })
})

onBeforeUnmount(() => {
  window.removeEventListener('stoneperms:unauthorised', unauthorised)
  window.removeEventListener('focus', refresh)
  window.removeEventListener('online', refresh)
  document.removeEventListener('visibilitychange', refresh)
  document.removeEventListener('pointerdown', closeProfile)
  document.removeEventListener('keydown', closeProfileOnEscape)
  stopRefreshIntervalWatch?.()
  window.clearInterval(poller)
})

watch(
  () => route.fullPath,
  async () => {
    mobileMenu.value = false
    profileOpen.value = false
    await nextTick()
    if (page.value && !effectiveReducedMotion.value) {
      gsap.fromTo(
        page.value,
        { opacity: 0, y: 8 },
        { opacity: 1, y: 0, duration: 0.32, ease: 'power2.out', clearProps: 'all' },
      )
    }
  },
)
</script>

<template>
  <ToastViewport />
  <RouterView v-if="!shellVisible" />
  <div v-else :class="['app-shell', sidebarCondensed && 'is-sidebar-condensed']">
    <button
      v-if="mobileMenu"
      class="mobile-scrim"
      type="button"
      aria-label="Close navigation"
      @click="mobileMenu = false"
    ></button>
    <aside :class="['sidebar', mobileMenu && 'is-open']">
      <div class="sidebar-head">
        <RouterLink class="brand-block" to="/" title="StonePerms overview">
          <img src="/stoneperms-logo.png" alt="" />
          <div><strong>STONEPERMS</strong><span>PERMISSIONS</span></div>
        </RouterLink>
        <button
          class="sidebar-condense-button"
          type="button"
          :aria-label="sidebarCondensed ? 'Expand navigation' : 'Condense navigation'"
          :title="sidebarCondensed ? 'Expand navigation' : 'Condense navigation'"
          @click="toggleSidebar"
        >
          <AppIcon name="sidebar" />
        </button>
      </div>
      <nav class="primary-nav" aria-label="Primary navigation">
        <span class="nav-section-label">Dashboard</span>
        <RouterLink
          v-for="item in visibleGlobalNavigation"
          :key="item.to"
          :to="item.to"
          :title="sidebarCondensed ? item.label : undefined"
          ><AppIcon :name="item.icon" /><span>{{ item.label }}</span></RouterLink
        >
        <template v-if="selectedServer">
          <span class="nav-section-label server-label">Selected server</span>
          <RouterLink
            v-for="item in visibleServerNavigation"
            :key="item.suffix"
            :to="`/servers/${selectedServer.id}${item.suffix}`"
            :title="sidebarCondensed ? item.label : undefined"
            ><AppIcon :name="item.icon" /><span>{{ item.label }}</span></RouterLink
          >
        </template>
      </nav>
      <div v-if="store.demoMode" class="sidebar-footer">
        <div class="demo-flag">DEMO DATA</div>
      </div>
    </aside>
    <section class="workspace">
      <header class="topbar">
        <div class="topbar-title">
          <button
            class="icon-button mobile-menu-button"
            type="button"
            aria-label="Open navigation"
            @click="mobileMenu = true"
          >
            <AppIcon name="menu" />
          </button>
        </div>
        <div class="topbar-actions">
          <div v-if="store.servers.length" class="server-switcher">
            <span>SERVER</span>
            <CustomSelect
              :model-value="selectedServer?.id"
              :options="serverOptions"
              aria-label="Select server"
              compact
              @update:model-value="switchServer"
            />
          </div>
          <div ref="profileMenu" class="operator-menu">
            <button
              class="operator-chip"
              type="button"
              aria-haspopup="menu"
              :aria-expanded="profileOpen"
              @click="profileOpen = !profileOpen"
            >
              <OperatorAvatar
                :name="store.user?.username"
                :seed="store.user?.id || store.user?.username"
                :size="30"
              />
              <div>
                <strong>{{ store.user?.username }}</strong
                ><small>{{ accountRole }}</small>
              </div>
              <AppIcon class="operator-chevron" name="chevron" :size="14" />
            </button>
            <div v-if="profileOpen" class="operator-dropdown" role="menu">
              <div class="operator-dropdown__identity">
                <OperatorAvatar
                  :name="store.user?.username"
                  :seed="store.user?.id || store.user?.username"
                  :size="42"
                />
                <span>
                  <small>Signed in</small>
                  <strong>{{ store.user?.username }}</strong>
                  <em>{{ accountRole }} account</em>
                </span>
              </div>
              <RouterLink to="/settings" role="menuitem"
                ><AppIcon name="settings" /><span
                  ><strong>Settings</strong><small>Preferences and server settings</small></span
                ></RouterLink
              >
              <button type="button" role="menuitem" @click="logout">
                <AppIcon name="logout" /><span
                  ><strong>Sign out</strong><small>End this session</small></span
                >
              </button>
            </div>
          </div>
        </div>
      </header>
      <div v-if="store.error" class="global-alert"><AppIcon name="warning" />{{ store.error }}</div>
      <main ref="page" class="page-content"><RouterView /></main>
    </section>
  </div>
</template>
