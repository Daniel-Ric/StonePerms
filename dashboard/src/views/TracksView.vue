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
const modal = ref('')
const busy = ref(false)
const selected = ref(null)
const name = ref('')
const serverId = computed(() => String(route.params.serverId))
const tracks = computed(() =>
  (directory.value?.tracks || []).filter((track) =>
    track.name.toLowerCase().includes(query.value.toLowerCase()),
  ),
)
function displayName(value) {
  return directory.value?.groups.find((group) => group.name === value)?.displayName || value
}
function open(action, track = null) {
  modal.value = action
  selected.value = track
  name.value = action === 'rename' ? track.name : ''
}
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
async function submit() {
  busy.value = true
  try {
    if (modal.value === 'create') await stonePermsApi.createTrack(serverId.value, name.value)
    if (modal.value === 'rename')
      await stonePermsApi.renameTrack(serverId.value, selected.value.name, name.value)
    if (modal.value === 'clone')
      await stonePermsApi.cloneTrack(serverId.value, selected.value.name, name.value)
    const messages = {
      create: 'Track created.',
      rename: 'Track renamed.',
      clone: 'Track cloned.',
    }
    toasts.success(messages[modal.value])
    modal.value = ''
    await load()
  } catch (cause) {
    toasts.error(cause.userMessage || cause.message)
  } finally {
    busy.value = false
  }
}
async function remove(track) {
  if (!window.confirm(`Delete track ${track.name}? Player group memberships are not removed.`))
    return
  busy.value = true
  try {
    await stonePermsApi.deleteTrack(serverId.value, track.name)
    toasts.success('Track deleted.')
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
    <h1>Tracks</h1>
    <div class="page-actions">
      <button v-if="store.canEdit()" class="button" type="button" @click="open('create')">
        <AppIcon name="plus" />Create track</button
      ><RouterLink v-if="store.canEdit()" class="button primary" :to="`/servers/${serverId}/editor`"
        ><AppIcon name="editor" />Edit ladders</RouterLink
      >
    </div>
  </header>
  <article class="panel">
    <header class="panel-header">
      <label class="search-field"
        ><AppIcon name="search" :size="15" /><input
          v-model="query"
          type="search"
          placeholder="Filter tracks" /></label
      ><span>{{ tracks.length }} tracks · revision {{ directory?.revision ?? '—' }}</span>
    </header>
    <LoadingBlock v-if="loading" :rows="6" />
    <div v-else-if="tracks.length" class="track-directory">
      <article v-for="track in tracks" :key="track.name" class="track-card">
        <header>
          <div>
            <span class="eyebrow">Track</span>
            <h3>{{ track.name }}</h3>
          </div>
          <div v-if="store.canEdit()" class="table-actions">
            <button class="button small" type="button" @click="open('rename', track)">Rename</button
            ><button class="button small" type="button" @click="open('clone', track)">Clone</button
            ><button class="button small danger" type="button" @click="remove(track)">
              <AppIcon name="trash" :size="13" />
            </button>
          </div>
        </header>
        <ol>
          <li v-for="(group, index) in track.groups" :key="group">
            <span>{{ index + 1 }}</span>
            <div>
              <strong>{{ displayName(group) }}</strong
              ><small>{{ group }}</small>
            </div>
            <i v-if="index < track.groups.length - 1"></i>
          </li>
        </ol>
        <div class="track-card-footer">
          <RouterLink
            class="button small full"
            :to="{ path: `/servers/${serverId}/editor`, query: { holder: `track:${track.name}` } }"
            >Edit group order <AppIcon name="arrow" :size="14"
          /></RouterLink>
        </div>
        <EmptyState
          v-if="!track.groups.length"
          icon="track"
          title="Empty track"
          description="Add groups in the editor to make this ladder usable."
        />
      </article>
    </div>
    <EmptyState
      v-else
      icon="track"
      title="No promotion tracks"
      description="Create the first track, then add its ordered groups in the permission editor."
      ><button v-if="store.canEdit()" class="button primary" type="button" @click="open('create')">
        Create track
      </button></EmptyState
    >
  </article>
  <BaseModal
    v-if="modal"
    :title="`${modal.slice(0, 1).toUpperCase()}${modal.slice(1)} track`"
    :description="
      modal === 'clone'
        ? `Copy ${selected.name} and its full group order.`
        : 'Track names use canonical lowercase identifiers.'
    "
    @close="modal = ''"
    ><div class="field">
      <label>{{
        modal === 'rename' ? 'New track name' : modal === 'clone' ? 'Clone name' : 'Track name'
      }}</label
      ><input v-model="name" placeholder="staff" @keyup.enter="submit" />
    </div>
    <template #footer
      ><button class="button" type="button" @click="modal = ''">Cancel</button
      ><button class="button primary" type="button" :disabled="busy || !name" @click="submit">
        {{ busy ? 'Saving…' : `${modal.slice(0, 1).toUpperCase()}${modal.slice(1)} track` }}
      </button></template
    ></BaseModal
  >
</template>
