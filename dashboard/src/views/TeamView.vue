<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import BaseModal from '@/components/BaseModal.vue'
import CustomSelect from '@/components/CustomSelect.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import { useLiveRefresh } from '@/composables/useLiveRefresh'
import { stonePermsApi } from '@/services/api'
import { toasts } from '@/services/toasts'
import { titleCase } from '@/lib/format'

const route = useRoute()
const detail = ref(null)
const loading = ref(true)
const addOpen = ref(false)
const busy = ref(false)
const selectedUsername = ref('')
const selectedRole = ref('viewer')
const roleOptions = [
  { value: 'viewer', label: 'Viewer' },
  { value: 'editor', label: 'Editor' },
  { value: 'admin', label: 'Admin' },
]
const serverId = computed(() => String(route.params.serverId))
async function load({ quiet = false } = {}) {
  if (!quiet) loading.value = true
  try {
    detail.value = await stonePermsApi.server(serverId.value)
  } catch (cause) {
    if (!quiet) toasts.error(cause.userMessage || cause.message)
  } finally {
    if (!quiet) loading.value = false
  }
}
async function grantMember() {
  busy.value = true
  try {
    await stonePermsApi.grantMembership(serverId.value, {
      username: selectedUsername.value.trim(),
      role: selectedRole.value,
    })
    toasts.success('Server access was granted.')
    addOpen.value = false
    selectedUsername.value = ''
    await load()
  } catch (cause) {
    toasts.error(cause.userMessage || cause.message)
  } finally {
    busy.value = false
  }
}
async function saveMember(userId, role) {
  busy.value = true
  try {
    await stonePermsApi.setMembership(serverId.value, userId, role)
    toasts.success('Server access was updated.')
    addOpen.value = false
    await load()
  } catch (cause) {
    toasts.error(cause.userMessage || cause.message)
  } finally {
    busy.value = false
  }
}
async function removeMember(member) {
  if (!window.confirm(`Remove ${member.username} from this server?`)) return
  busy.value = true
  try {
    await stonePermsApi.removeMembership(serverId.value, member.userId)
    toasts.success('Server access was removed.')
    await load()
  } catch (cause) {
    toasts.error(cause.userMessage || cause.message)
  } finally {
    busy.value = false
  }
}
onMounted(load)
watch(serverId, () => void load())
useLiveRefresh(() => load({ quiet: true }))
</script>

<template>
  <header class="page-heading">
    <h1>Team access</h1>
    <div class="page-actions">
      <button class="button primary" type="button" @click="addOpen = true">
        <AppIcon name="plus" />Add operator
      </button>
    </div>
  </header>
  <section class="role-explainer">
    <article>
      <strong>Owner</strong>
      <p>Can manage the connection, operators, and all permissions.</p>
    </article>
    <article>
      <strong>Admin</strong>
      <p>Can edit permissions, groups, tracks, and server settings.</p>
    </article>
    <article>
      <strong>Editor</strong>
      <p>Can edit permissions, groups, and tracks.</p>
    </article>
    <article>
      <strong>Viewer</strong>
      <p>Reads server status and audit history.</p>
    </article>
  </section>
  <article class="panel">
    <header class="panel-header">
      <h3>Assigned operators</h3>
      <span>{{ detail?.memberships?.length || 0 }} operators</span>
    </header>
    <LoadingBlock v-if="loading" :rows="5" />
    <div v-else-if="detail?.memberships?.length" class="responsive-table">
      <table class="data-table mobile-cards">
        <thead>
          <tr>
            <th>Operator</th>
            <th>Role</th>
            <th>Capabilities</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="member in detail.memberships" :key="member.userId">
            <td data-label="Operator">
              <span class="primary-cell">{{ member.username }}</span
              ><span class="secondary-cell">{{ member.userId }}</span>
            </td>
            <td data-label="Role">
              <CustomSelect
                v-if="member.role !== 'owner'"
                :model-value="member.role"
                :options="roleOptions"
                :disabled="busy"
                aria-label="Server role"
                compact
                @update:model-value="saveMember(member.userId, $event)"
              />
              <strong v-else>{{ titleCase(member.role) }}</strong>
            </td>
            <td data-label="Capabilities">
              {{
                member.role === 'owner'
                  ? 'All controls'
                  : member.role === 'viewer'
                    ? 'Status and audit'
                    : 'Permission editor'
              }}
            </td>
            <td data-label="Action">
              <div class="table-actions">
                <button
                  v-if="member.role !== 'owner'"
                  class="button small danger"
                  type="button"
                  :disabled="busy"
                  @click="removeMember(member)"
                >
                  <AppIcon name="trash" :size="14" />Remove
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <EmptyState
      v-else
      icon="users"
      title="No assigned operators"
      description="Add an existing web user to this server."
    />
  </article>
  <BaseModal
    v-if="addOpen"
    title="Add server operator"
    description="The selected web user receives access only to this server."
    @close="addOpen = false"
    ><div class="form-grid">
      <div class="field full">
        <label for="operator-username">StonePerms username</label>
        <input
          id="operator-username"
          v-model="selectedUsername"
          autocomplete="off"
          placeholder="operator-name"
          minlength="3"
          maxlength="32"
        />
        <small>Enter the exact username of an existing StonePerms account.</small>
      </div>
      <div class="field full">
        <label>Server role</label>
        <CustomSelect v-model="selectedRole" :options="roleOptions" aria-label="Server role" />
      </div>
    </div>
    <template #footer
      ><button class="button" type="button" @click="addOpen = false">Cancel</button
      ><button
        class="button primary"
        type="button"
        :disabled="!selectedUsername.trim() || busy"
        @click="grantMember"
      >
        Grant access
      </button></template
    ></BaseModal
  >
</template>
