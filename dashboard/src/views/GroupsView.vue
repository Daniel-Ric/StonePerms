<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import BaseModal from '@/components/BaseModal.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import { useLiveRefresh } from '@/composables/useLiveRefresh'
import { stonePermsApi } from '@/services/api'
import { toasts } from '@/services/toasts'
import { useStonePermsStore } from '@/stores/stoneperms'

const route = useRoute()
const store = useStonePermsStore()
const directory = ref(null)
const loading = ref(true)
const query = ref('')
const busy = ref(false)
const createOpen = ref(false)
const weightOpen = ref(false)
const selected = ref(null)
const form = ref({ name: '', displayName: '', weight: 0 })
const serverId = computed(() => String(route.params.serverId))
const canManage = computed(() => ['owner', 'admin'].includes(store.selectedServer?.role))
const groups = computed(() =>
  (directory.value?.groups || [])
    .filter((item) =>
      `${item.name} ${item.displayName}`.toLowerCase().includes(query.value.toLowerCase()),
    )
    .sort((a, b) => b.weight - a.weight),
)

async function load({ quiet = false } = {}) {
  if (!quiet) loading.value = true
  try {
    directory.value = await stonePermsApi.directory(serverId.value)
  } catch (cause) {
    if (!quiet) toasts.error(cause.userMessage || cause.message)
  } finally {
    if (!quiet) loading.value = false
  }
}
function openWeight(group) {
  selected.value = group
  form.value.weight = group.weight
  weightOpen.value = true
}
async function create() {
  busy.value = true
  try {
    await stonePermsApi.createGroup(serverId.value, {
      name: form.value.name,
      displayName: form.value.displayName || null,
      weight: Number(form.value.weight),
    })
    toasts.success('Permission group created.')
    createOpen.value = false
    form.value = { name: '', displayName: '', weight: 0 }
    await load()
  } catch (cause) {
    toasts.error(cause.userMessage || cause.message)
  } finally {
    busy.value = false
  }
}
async function saveWeight() {
  busy.value = true
  try {
    await stonePermsApi.setGroupWeight(
      serverId.value,
      selected.value.name,
      Number(form.value.weight),
    )
    toasts.success('Group weight updated.')
    weightOpen.value = false
    await load()
  } catch (cause) {
    toasts.error(cause.userMessage || cause.message)
  } finally {
    busy.value = false
  }
}
async function remove(group) {
  if (
    !window.confirm(
      `Delete group ${group.name}? Its permissions, parent assignments, and track entries will be removed.`,
    )
  )
    return
  busy.value = true
  try {
    await stonePermsApi.deleteGroup(serverId.value, group.name)
    toasts.success('Permission group deleted.')
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
    <h1>Groups</h1>
    <div class="page-actions">
      <button v-if="canManage" class="button" type="button" @click="createOpen = true">
        <AppIcon name="plus" />Create group</button
      ><RouterLink v-if="store.canEdit()" class="button primary" :to="`/servers/${serverId}/editor`"
        ><AppIcon name="editor" />Edit nodes</RouterLink
      >
    </div>
  </header>
  <article class="panel">
    <header class="panel-header">
      <label class="search-field"
        ><AppIcon name="search" :size="15" /><input
          v-model="query"
          type="search"
          placeholder="Filter groups" /></label
      ><span>{{ groups.length }} groups · revision {{ directory?.revision ?? '—' }}</span>
    </header>
    <LoadingBlock v-if="loading" :rows="7" />
    <div v-else-if="groups.length" class="group-directory">
      <article v-for="group in groups" :key="group.name" class="group-row is-compact">
        <div class="group-weight">
          <strong>{{ group.weight }}</strong
          ><span>Weight</span>
        </div>
        <div class="group-identity">
          <span class="eyebrow">{{
            group.name === directory.defaultGroup ? 'Default group' : 'Group'
          }}</span>
          <h3>{{ group.displayName }}</h3>
          <code>{{ group.name }}</code>
        </div>
        <div class="group-actions">
          <button v-if="canManage" class="button small" type="button" @click="openWeight(group)">
            Set weight</button
          ><button
            v-if="canManage && group.name !== directory.defaultGroup"
            class="button small danger"
            type="button"
            :disabled="busy"
            @click="remove(group)"
          >
            <AppIcon name="trash" :size="13" /></button
          ><RouterLink
            class="button small"
            :to="{ path: `/servers/${serverId}/editor`, query: { holder: `group:${group.name}` } }"
            >Open <AppIcon name="arrow" :size="14"
          /></RouterLink>
        </div>
      </article>
    </div>
    <EmptyState
      v-else
      icon="group"
      title="No groups available"
      description="This server has no groups to display."
    />
  </article>
  <BaseModal
    v-if="createOpen"
    title="Create permission group"
    description="Group names use lowercase identifiers and cannot be renamed later."
    @close="createOpen = false"
    ><div class="form-grid">
      <div class="field full">
        <label>Group name</label><input v-model="form.name" placeholder="helper" />
      </div>
      <div class="field">
        <label>Display name</label><input v-model="form.displayName" placeholder="Helper" />
      </div>
      <div class="field">
        <label>Weight</label><input v-model.number="form.weight" type="number" step="1" />
      </div>
    </div>
    <template #footer
      ><button class="button" type="button" @click="createOpen = false">Cancel</button
      ><button class="button primary" type="button" :disabled="busy || !form.name" @click="create">
        {{ busy ? 'Creating…' : 'Create group' }}
      </button></template
    ></BaseModal
  >
  <BaseModal
    v-if="weightOpen"
    title="Update group weight"
    description="Metadata from higher-weight groups wins when all other factors are equal."
    @close="weightOpen = false"
    ><div class="field">
      <label>{{ selected.displayName }} weight</label
      ><input v-model.number="form.weight" type="number" step="1" />
    </div>
    <template #footer
      ><button class="button" type="button" @click="weightOpen = false">Cancel</button
      ><button class="button primary" type="button" :disabled="busy" @click="saveWeight">
        Save weight
      </button></template
    ></BaseModal
  >
</template>
