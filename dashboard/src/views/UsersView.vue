<script setup>
import { computed, onMounted, ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import BaseModal from '@/components/BaseModal.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { useLiveRefresh } from '@/composables/useLiveRefresh'
import { stonePermsApi } from '@/services/api'
import { toasts } from '@/services/toasts'
import { formatDate, titleCase } from '@/lib/format'

const users = ref([])
const loading = ref(true)
const open = ref(false)
const busy = ref(false)
const query = ref('')
const form = ref({ username: '', password: '' })
const error = ref('')
const filtered = computed(() =>
  users.value.filter((user) => user.username.toLowerCase().includes(query.value.toLowerCase())),
)
async function load({ quiet = false } = {}) {
  if (!quiet) loading.value = true
  try {
    users.value = (await stonePermsApi.users()).users || []
  } catch (cause) {
    if (!quiet) toasts.error(cause.userMessage || cause.message)
  } finally {
    if (!quiet) loading.value = false
  }
}
async function create() {
  error.value = ''
  if (form.value.password.length < 12) {
    error.value = 'Password must contain at least 12 characters.'
    return
  }
  busy.value = true
  try {
    await stonePermsApi.createUser(form.value)
    toasts.success('Web user created.')
    open.value = false
    form.value = { username: '', password: '' }
    await load()
  } catch (cause) {
    error.value = cause.userMessage || cause.message
  } finally {
    busy.value = false
  }
}
onMounted(load)
useLiveRefresh(() => load({ quiet: true }))
</script>

<template>
  <header class="page-heading">
    <h1>Web users</h1>
    <div class="page-actions">
      <button class="button primary" type="button" @click="open = true">
        <AppIcon name="plus" />Create web user
      </button>
    </div>
  </header>
  <article class="panel">
    <header class="panel-header">
      <label class="search-field"
        ><AppIcon name="search" :size="15" /><input
          v-model="query"
          type="search"
          placeholder="Filter web users" /></label
      ><span>{{ users.length }} users</span>
    </header>
    <LoadingBlock v-if="loading" :rows="5" />
    <div v-else-if="filtered.length" class="responsive-table">
      <table class="data-table mobile-cards">
        <thead>
          <tr>
            <th>Username</th>
            <th>System role</th>
            <th>State</th>
            <th>Created</th>
            <th>User ID</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="user in filtered" :key="user.id">
            <td data-label="Username">
              <span class="primary-cell">{{ user.username }}</span>
            </td>
            <td data-label="System role">{{ titleCase(user.systemRole) }}</td>
            <td data-label="State">
              <StatusBadge
                :state="user.disabledAt ? 'offline' : 'online'"
                :label="user.disabledAt ? 'Disabled' : 'Active'"
              />
            </td>
            <td data-label="Created">{{ formatDate(user.createdAt) }}</td>
            <td data-label="User ID">
              <code>{{ user.id }}</code>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <EmptyState
      v-else
      icon="users"
      title="No matching web users"
      description="Create a local identity, then assign it from a server's Team access page."
    />
  </article>
  <BaseModal
    v-if="open"
    title="Create web user"
    description="Create the identity first; server access is granted separately."
    @close="open = false"
    ><div class="form-grid">
      <div class="field full">
        <label>Username</label
        ><input
          v-model="form.username"
          autocomplete="off"
          placeholder="operator-name"
          minlength="3"
          maxlength="32"
        />
      </div>
      <div class="field full">
        <label>Temporary password</label
        ><input
          v-model="form.password"
          type="password"
          autocomplete="new-password"
          minlength="12"
        /><small>At least 12 characters. Share it through a secure channel.</small>
      </div>
    </div>
    <p v-if="error" class="form-error" role="alert">{{ error }}</p>
    <template #footer
      ><button class="button" type="button" @click="open = false">Cancel</button
      ><button
        class="button primary"
        type="button"
        :disabled="busy || !form.username || !form.password"
        @click="create"
      >
        {{ busy ? 'Creating…' : 'Create user' }}
      </button></template
    ></BaseModal
  >
</template>
