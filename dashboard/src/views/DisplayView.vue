<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import { useLiveRefresh } from '@/composables/useLiveRefresh'
import { stonePermsApi } from '@/services/api'
import { toasts } from '@/services/toasts'
import { useStonePermsStore } from '@/stores/stoneperms'

const route = useRoute()
const store = useStonePermsStore()
const loading = ref(true)
const saving = ref(false)
const baseline = ref('')
const form = reactive({
  chatEnabled: false,
  chatFormat: '',
  nametagEnabled: false,
  nametagFormat: '',
})

const serverId = computed(() => String(route.params.serverId))
const canManage = computed(() => ['owner', 'admin'].includes(store.selectedServer?.role))
const serialized = computed(() => JSON.stringify(form))
const dirty = computed(() => serialized.value !== baseline.value)
const errors = computed(() => {
  const result = []
  if (!form.chatFormat.includes('{name}') || !form.chatFormat.includes('{message}'))
    result.push('Chat format needs {name} and {message}.')
  if (!form.nametagFormat.includes('{name}')) result.push('Nametag format needs {name}.')
  if (form.chatFormat.length > 256 || form.nametagFormat.length > 256)
    result.push('Formats can contain at most 256 characters.')
  return result
})
const chatPreview = computed(() =>
  preview(form.chatFormat, {
    prefix: 'Admin ',
    name: 'Alex',
    suffix: ' ★',
    message: 'Hello from the server',
  }),
)
const nametagPreview = computed(() =>
  preview(form.nametagFormat, { prefix: 'Admin ', name: 'Alex', suffix: ' ★' }),
)

async function load({ quiet = false } = {}) {
  if (quiet && dirty.value) return
  if (!quiet) loading.value = true
  try {
    const settings = await stonePermsApi.displaySettings(serverId.value)
    form.chatEnabled = Boolean(settings.chat.enabled)
    form.chatFormat = settings.chat.format
    form.nametagEnabled = Boolean(settings.nametag.enabled)
    form.nametagFormat = settings.nametag.format
    baseline.value = serialized.value
  } catch (cause) {
    if (!quiet) toasts.error(cause.userMessage || cause.message)
  } finally {
    if (!quiet) loading.value = false
  }
}

async function save() {
  if (!canManage.value || errors.value.length) return
  saving.value = true
  try {
    const settings = await stonePermsApi.updateDisplaySettings(serverId.value, { ...form })
    form.chatEnabled = Boolean(settings.chat.enabled)
    form.chatFormat = settings.chat.format
    form.nametagEnabled = Boolean(settings.nametag.enabled)
    form.nametagFormat = settings.nametag.format
    baseline.value = serialized.value
    toasts.success('Display settings saved.')
  } catch (cause) {
    toasts.error(cause.userMessage || cause.message)
  } finally {
    saving.value = false
  }
}

function preview(template, values) {
  let output = template
  for (const [key, value] of Object.entries(values)) output = output.replaceAll(`{${key}}`, value)
  return output.replace(/§[0-9a-fk-or]/gi, '')
}

onMounted(load)
watch(serverId, () => void load())
useLiveRefresh(() => load({ quiet: true }))
</script>

<template>
  <header class="page-heading">
    <h1>Chat and nametags</h1>
    <div class="page-actions">
      <button
        class="button primary"
        type="button"
        :disabled="!canManage || !dirty || saving || errors.length"
        @click="save"
      >
        <AppIcon name="check" />{{ saving ? 'Saving…' : 'Save settings' }}
      </button>
    </div>
  </header>

  <LoadingBlock v-if="loading" :rows="6" />
  <template v-else>
    <p v-if="!canManage" class="display-notice">
      <AppIcon name="lock" />Only server owners and admins can change live display settings.
    </p>
    <section class="panel-grid display-settings-grid">
      <article class="panel span-6 display-setting-card">
        <header class="panel-header">
          <div>
            <h3>Chat format</h3>
            <small>Changes the format of normal player chat messages.</small>
          </div>
          <label class="feature-switch">
            <input v-model="form.chatEnabled" type="checkbox" :disabled="!canManage" />
            <span aria-hidden="true"></span>
            <strong>{{ form.chatEnabled ? 'Enabled' : 'Disabled' }}</strong>
          </label>
        </header>
        <div class="panel-body display-form-body">
          <div class="field">
            <label for="chat-format">Format</label>
            <input
              id="chat-format"
              v-model="form.chatFormat"
              maxlength="256"
              autocomplete="off"
              spellcheck="false"
              :readonly="!canManage"
            />
            <small>Requires <code>{name}</code> and <code>{message}</code>.</small>
          </div>
          <div class="display-preview">
            <span>Preview</span>
            <strong>{{ chatPreview }}</strong>
          </div>
        </div>
      </article>

      <article class="panel span-6 display-setting-card">
        <header class="panel-header">
          <div>
            <h3>Nametag format</h3>
            <small>Changes the name shown above online players.</small>
          </div>
          <label class="feature-switch">
            <input v-model="form.nametagEnabled" type="checkbox" :disabled="!canManage" />
            <span aria-hidden="true"></span>
            <strong>{{ form.nametagEnabled ? 'Enabled' : 'Disabled' }}</strong>
          </label>
        </header>
        <div class="panel-body display-form-body">
          <div class="field">
            <label for="nametag-format">Format</label>
            <input
              id="nametag-format"
              v-model="form.nametagFormat"
              maxlength="256"
              autocomplete="off"
              spellcheck="false"
              :readonly="!canManage"
            />
            <small>Requires <code>{name}</code>.</small>
          </div>
          <div class="display-preview nametag-preview">
            <span>Preview</span>
            <strong>{{ nametagPreview }}</strong>
          </div>
        </div>
      </article>

      <article class="panel span-12 display-placeholders">
        <header class="panel-header">
          <h3>Placeholders</h3>
          <span>Minecraft colour codes supported</span>
        </header>
        <div class="panel-body">
          <code>{prefix}</code><span>Resolved prefix</span> <code>{name}</code
          ><span>Player name</span> <code>{suffix}</code><span>Resolved suffix</span>
          <code>{message}</code><span>Chat only</span>
        </div>
      </article>
    </section>
    <p v-if="errors.length" class="form-error display-errors">{{ errors[0] }}</p>
  </template>
</template>
