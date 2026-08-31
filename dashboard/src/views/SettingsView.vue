<script setup>
import { computed, reactive, ref, watch } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import CustomSelect from '@/components/CustomSelect.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { usePreferences } from '@/composables/usePreferences'
import { runtimeConfig } from '@/config/runtime'
import { stonePermsApi } from '@/services/api'
import { toasts } from '@/services/toasts'
import { useStonePermsStore } from '@/stores/stoneperms'

const store = useStonePermsStore()
const preferences = usePreferences()
const dashboardOrigin = window.location.origin
const origin = computed(() => runtimeConfig.apiBaseUrl || dashboardOrigin)
const loadingServer = ref(false)
const savingServer = ref(false)
const serverSettings = ref(null)
const baseline = ref('')
const form = reactive({
  defaultGroup: '',
  serverContext: '',
  includeDeviceOsContext: false,
  includeLocaleContext: false,
  expiryCheckSeconds: 1,
  catalogRefreshSeconds: 5,
  debug: false,
})

const selectedServer = computed(() => store.selectedServer)
const serverId = computed(() => selectedServer.value?.id || '')
const canManageServer = computed(() => ['owner', 'admin'].includes(selectedServer.value?.role))
const serialized = computed(() => JSON.stringify({ ...form }))
const dirty = computed(() => serialized.value !== baseline.value)
const predictedRestart = computed(() => {
  const active = serverSettings.value?.active
  if (!active) return []
  return ['defaultGroup', 'expiryCheckSeconds', 'catalogRefreshSeconds'].filter(
    (key) => form[key] !== active[key],
  )
})
const formErrors = computed(() => {
  const errors = []
  if (!/^[a-z0-9_-]{1,64}$/i.test(form.defaultGroup))
    errors.push('Default group may contain letters, numbers, underscores, and hyphens.')
  if (!/^[a-z0-9_.-]{1,64}$/i.test(form.serverContext))
    errors.push('Server context may contain letters, numbers, dots, underscores, and hyphens.')
  if (form.expiryCheckSeconds < 1 || form.expiryCheckSeconds > 60)
    errors.push('Expiry checks must run every 1 to 60 seconds.')
  if (form.catalogRefreshSeconds < 1 || form.catalogRefreshSeconds > 300)
    errors.push('Permission discovery must run every 1 to 300 seconds.')
  return errors
})

const themeOptions = [
  { value: 'system', label: 'System', description: 'Follow this device', icon: 'monitor' },
  { value: 'dark', label: 'Dark', description: 'Low-light interface', icon: 'moon' },
  { value: 'light', label: 'Light', description: 'Bright interface', icon: 'sun' },
]

const refreshOptions = [
  { value: 15_000, label: 'Every 15 seconds', description: 'Fastest updates' },
  { value: 30_000, label: 'Every 30 seconds', description: 'Recommended' },
  { value: 60_000, label: 'Every minute', description: 'Less background traffic' },
  { value: 0, label: 'Off', description: 'Refresh on focus and navigation only' },
]

function applyServerSettings(result) {
  serverSettings.value = result
  Object.assign(form, result.configured)
  baseline.value = JSON.stringify({ ...form })
}

async function loadServerSettings() {
  if (!serverId.value) {
    serverSettings.value = null
    baseline.value = ''
    return
  }
  loadingServer.value = true
  try {
    applyServerSettings(await stonePermsApi.pluginSettings(serverId.value))
  } catch (cause) {
    serverSettings.value = null
    toasts.error(cause.userMessage || cause.message)
  } finally {
    loadingServer.value = false
  }
}

async function saveServerSettings() {
  if (!canManageServer.value || !dirty.value || formErrors.value.length) return
  savingServer.value = true
  try {
    const result = await stonePermsApi.updatePluginSettings(serverId.value, {
      ...form,
      expiryCheckSeconds: Number(form.expiryCheckSeconds),
      catalogRefreshSeconds: Number(form.catalogRefreshSeconds),
    })
    applyServerSettings(result)
    if (result.restartRequired.length)
      toasts.warning('Saved. Restart this server to apply the marked settings.')
    else toasts.success('Server settings saved.')
  } catch (cause) {
    toasts.error(cause.userMessage || cause.message)
  } finally {
    savingServer.value = false
  }
}

function resetServerSettings() {
  if (serverSettings.value) Object.assign(form, serverSettings.value.configured)
}

function scrollToSection(id) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

watch(serverId, () => void loadServerSettings(), { immediate: true })
</script>

<template>
  <header class="page-heading settings-page-heading">
    <h1>Settings</h1>
    <StatusBadge
      v-if="selectedServer"
      :state="selectedServer.status?.ready ? 'online' : 'offline'"
      :label="
        selectedServer.status?.ready
          ? `${selectedServer.name} online`
          : `${selectedServer.name} offline`
      "
    />
  </header>

  <div class="settings-workspace">
    <aside class="settings-local-nav" aria-label="Settings sections">
      <strong>Settings</strong>
      <button type="button" @click="scrollToSection('personal-settings')">
        <AppIcon name="monitor" />Personal
      </button>
      <button type="button" @click="scrollToSection('server-settings')">
        <AppIcon name="server" />Selected server
      </button>
      <button type="button" @click="scrollToSection('system-settings')">
        <AppIcon name="shield" />System
      </button>
      <small
        >Personal choices stay in this browser. Server settings are stored by the plugin.</small
      >
    </aside>

    <main class="settings-content">
      <section id="personal-settings" class="settings-section">
        <header class="settings-section-heading">
          <div>
            <span>THIS BROWSER</span>
            <h3>Dashboard</h3>
          </div>
          <small>Saved on this device</small>
        </header>

        <div class="settings-card-grid">
          <article class="settings-card settings-theme-card">
            <header>
              <div>
                <h4>Colour theme</h4>
                <p>Choose a fixed theme or follow your device.</p>
              </div>
              <span>{{ preferences.resolvedTheme.value }}</span>
            </header>
            <div class="theme-choice-grid" role="group" aria-label="Colour theme">
              <button
                v-for="option in themeOptions"
                :key="option.value"
                type="button"
                :class="['theme-choice', preferences.theme.value === option.value && 'is-selected']"
                :aria-pressed="preferences.theme.value === option.value"
                @click="preferences.setTheme(option.value)"
              >
                <span :class="['theme-preview', `is-${option.value}`]" aria-hidden="true"
                  ><i></i><i></i><i></i
                ></span>
                <span class="theme-choice-copy"
                  ><AppIcon :name="option.icon" :size="16" /><span
                    ><strong>{{ option.label }}</strong
                    ><small>{{ option.description }}</small></span
                  ></span
                >
                <AppIcon
                  v-if="preferences.theme.value === option.value"
                  class="theme-choice-check"
                  name="check"
                  :size="15"
                />
              </button>
            </div>
          </article>

          <article class="settings-card">
            <header>
              <div>
                <h4>Behaviour</h4>
                <p>Navigation and background updates.</p>
              </div>
            </header>
            <div class="setting-list">
              <div class="setting-row is-select">
                <span
                  ><strong>Live updates</strong
                  ><small>How often fresh server data is requested.</small></span
                >
                <CustomSelect
                  :model-value="preferences.refreshIntervalMs.value"
                  :options="refreshOptions"
                  aria-label="Live update interval"
                  @update:model-value="preferences.setRefreshInterval"
                />
              </div>
              <div class="setting-row">
                <span
                  ><strong>Condensed navigation</strong
                  ><small>Use icon-only navigation on larger screens.</small></span
                >
                <button
                  class="setting-switch"
                  type="button"
                  role="switch"
                  :aria-checked="preferences.sidebarCondensed.value"
                  aria-label="Condensed navigation"
                  @click="preferences.setSidebarCondensed(!preferences.sidebarCondensed.value)"
                >
                  <i></i>
                </button>
              </div>
              <div class="setting-row">
                <span
                  ><strong>Reduce motion</strong
                  ><small>Disable page and chart animations.</small></span
                >
                <button
                  class="setting-switch"
                  type="button"
                  role="switch"
                  :aria-checked="preferences.reduceMotion.value"
                  aria-label="Reduce motion"
                  @click="preferences.setReduceMotion(!preferences.reduceMotion.value)"
                >
                  <i></i>
                </button>
              </div>
            </div>
          </article>
        </div>
      </section>

      <section id="server-settings" class="settings-section">
        <header class="settings-section-heading">
          <div>
            <span>SELECTED SERVER</span>
            <h3>{{ selectedServer?.name || 'No server selected' }}</h3>
          </div>
          <div class="settings-heading-meta">
            <span v-if="predictedRestart.length" class="restart-label"
              ><AppIcon name="refresh" :size="13" />Restart needed</span
            >
            <small v-if="selectedServer">{{ selectedServer.role }}</small>
          </div>
        </header>

        <LoadingBlock v-if="loadingServer" :rows="6" />
        <div v-else-if="!selectedServer" class="settings-empty">
          Pair or select a server before changing plugin settings.
        </div>
        <div v-else-if="!serverSettings" class="settings-empty">
          The plugin must be online to read its settings.
        </div>
        <template v-else>
          <p v-if="!canManageServer" class="settings-access-note">
            <AppIcon name="lock" />You can inspect these values, but only server owners and admins
            can change them.
          </p>
          <div class="settings-card-grid server-settings-grid">
            <article class="settings-card">
              <header>
                <div>
                  <h4>Permission defaults</h4>
                  <p>Base group and server context used during resolution.</p>
                </div>
              </header>
              <div class="settings-form-list">
                <label class="settings-field">
                  <span
                    ><strong>Default group</strong
                    ><small>Every player inherits this group.</small></span
                  >
                  <span class="settings-control-with-tag"
                    ><input
                      v-model.trim="form.defaultGroup"
                      maxlength="64"
                      spellcheck="false"
                      :readonly="!canManageServer"
                    /><em>RESTART</em></span
                  >
                </label>
                <label class="settings-field">
                  <span
                    ><strong>Server context</strong
                    ><small>Value exposed as the built-in <code>server</code> context.</small></span
                  >
                  <input
                    v-model.trim="form.serverContext"
                    maxlength="64"
                    spellcheck="false"
                    :readonly="!canManageServer"
                  />
                </label>
              </div>
            </article>

            <article class="settings-card">
              <header>
                <div>
                  <h4>Player contexts</h4>
                  <p>Optional client data available to contextual nodes.</p>
                </div>
              </header>
              <div class="setting-list">
                <div class="setting-row">
                  <span
                    ><strong>Device operating system</strong
                    ><small>Add <code>device_os</code> to active player contexts.</small></span
                  >
                  <button
                    class="setting-switch"
                    type="button"
                    role="switch"
                    :disabled="!canManageServer"
                    :aria-checked="form.includeDeviceOsContext"
                    aria-label="Device operating system context"
                    @click="form.includeDeviceOsContext = !form.includeDeviceOsContext"
                  >
                    <i></i>
                  </button>
                </div>
                <div class="setting-row">
                  <span
                    ><strong>Client locale</strong
                    ><small>Add <code>locale</code> to active player contexts.</small></span
                  >
                  <button
                    class="setting-switch"
                    type="button"
                    role="switch"
                    :disabled="!canManageServer"
                    :aria-checked="form.includeLocaleContext"
                    aria-label="Client locale context"
                    @click="form.includeLocaleContext = !form.includeLocaleContext"
                  >
                    <i></i>
                  </button>
                </div>
              </div>
              <p class="settings-privacy-note">
                <AppIcon name="shield" :size="15" />Only enable client contexts when permission
                rules actually use them.
              </p>
            </article>

            <article class="settings-card">
              <header>
                <div>
                  <h4>Maintenance</h4>
                  <p>Cleanup and permission discovery intervals.</p>
                </div>
              </header>
              <div class="settings-form-list">
                <label class="settings-field">
                  <span
                    ><strong>Temporary node cleanup</strong
                    ><small>Interval in seconds for expired nodes.</small></span
                  >
                  <span class="settings-control-with-tag"
                    ><input
                      v-model.number="form.expiryCheckSeconds"
                      type="number"
                      min="1"
                      max="60"
                      :readonly="!canManageServer"
                    /><em>RESTART</em></span
                  >
                </label>
                <label class="settings-field">
                  <span
                    ><strong>Permission discovery</strong
                    ><small>Interval in seconds for the Endstone permission catalog.</small></span
                  >
                  <span class="settings-control-with-tag"
                    ><input
                      v-model.number="form.catalogRefreshSeconds"
                      type="number"
                      min="1"
                      max="300"
                      :readonly="!canManageServer"
                    /><em>RESTART</em></span
                  >
                </label>
              </div>
            </article>

            <article class="settings-card">
              <header>
                <div>
                  <h4>Diagnostics</h4>
                  <p>Extra detail for troubleshooting the plugin.</p>
                </div>
              </header>
              <div class="setting-list">
                <div class="setting-row">
                  <span
                    ><strong>Debug logging</strong
                    ><small>Log additional cleanup information to the server console.</small></span
                  >
                  <button
                    class="setting-switch"
                    type="button"
                    role="switch"
                    :disabled="!canManageServer"
                    :aria-checked="form.debug"
                    aria-label="Debug logging"
                    @click="form.debug = !form.debug"
                  >
                    <i></i>
                  </button>
                </div>
              </div>
              <div class="settings-related-links">
                <RouterLink :to="`/servers/${serverId}/display`"
                  ><AppIcon name="display" /><span
                    ><strong>Chat and nametags</strong
                    ><small>Formats, prefixes, and suffixes</small></span
                  ><AppIcon name="arrow"
                /></RouterLink>
                <RouterLink :to="`/servers/${serverId}/audit`"
                  ><AppIcon name="audit" /><span
                    ><strong>Plugin audit</strong
                    ><small>Review permission and settings changes</small></span
                  ><AppIcon name="arrow"
                /></RouterLink>
              </div>
            </article>
          </div>

          <div class="settings-save-bar">
            <div>
              <strong>{{
                dirty ? 'Unsaved server changes' : 'Server settings are up to date'
              }}</strong>
              <small v-if="formErrors.length">{{ formErrors[0] }}</small>
              <small v-else-if="predictedRestart.length"
                >A server restart will be required for {{ predictedRestart.length }} setting{{
                  predictedRestart.length === 1 ? '' : 's'
                }}.</small
              >
              <small v-else>Runtime settings are applied as soon as they are saved.</small>
            </div>
            <button
              class="button ghost"
              type="button"
              :disabled="!dirty || savingServer"
              @click="resetServerSettings"
            >
              Reset
            </button>
            <button
              class="button primary"
              type="button"
              :disabled="!canManageServer || !dirty || savingServer || formErrors.length"
              @click="saveServerSettings"
            >
              <AppIcon name="check" />{{ savingServer ? 'Saving…' : 'Save server settings' }}
            </button>
          </div>
        </template>
      </section>

      <section id="system-settings" class="settings-section">
        <header class="settings-section-heading">
          <div>
            <span>INSTALLATION</span>
            <h3>System</h3>
          </div>
          <StatusBadge
            :state="store.health?.status === 'ok' ? 'online' : 'offline'"
            :label="store.health?.status === 'ok' ? 'API online' : 'API unavailable'"
          />
        </header>
        <article class="settings-card settings-system-card">
          <section aria-labelledby="runtime-details-heading">
            <h4 id="runtime-details-heading">Runtime</h4>
            <div class="detail-list">
              <div>
                <span>Dashboard origin</span><code>{{ dashboardOrigin }}</code>
              </div>
              <div>
                <span>API base URL</span><code>{{ origin }}</code>
              </div>
              <div>
                <span>Data source</span
                ><strong>{{ store.demoMode ? 'Demonstration data' : 'Live API' }}</strong>
              </div>
            </div>
          </section>
          <section aria-labelledby="security-details-heading">
            <h4 id="security-details-heading">Security</h4>
            <div class="security-list compact">
              <p>
                <AppIcon name="lock" /><span
                  ><strong>Protected session</strong
                  ><small>HTTP-only authentication with CSRF protection.</small></span
                >
              </p>
              <p>
                <AppIcon name="shield" /><span
                  ><strong>Server-owned settings</strong
                  ><small>The plugin validates and saves every server setting.</small></span
                >
              </p>
              <p>
                <AppIcon name="audit" /><span
                  ><strong>Audited changes</strong
                  ><small>Settings changes are recorded in API and plugin audit logs.</small></span
                >
              </p>
            </div>
          </section>
        </article>
      </section>
    </main>
  </div>
</template>
