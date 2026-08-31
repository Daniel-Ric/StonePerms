<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import CustomSelect from '@/components/CustomSelect.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import PlayerAvatar from '@/components/PlayerAvatar.vue'
import { useLiveRefresh } from '@/composables/useLiveRefresh'
import { formatDate, relativeTime, titleCase } from '@/lib/format'
import { stonePermsApi } from '@/services/api'
import { toasts } from '@/services/toasts'
import { useStonePermsStore } from '@/stores/stoneperms'

const route = useRoute()
const store = useStonePermsStore()
const identifier = ref('')
const result = ref(null)
const directory = ref(null)
const loading = ref(false)
const searched = ref(false)
const moving = ref(false)
const selectedTrack = ref('')
const serverId = computed(() => String(route.params.serverId))
const player = computed(() => result.value?.user || null)
const profile = computed(() => result.value?.profile || null)
const playerOptions = computed(() =>
  (directory.value?.users || []).map((user) => ({
    value: user.name,
    label: user.name,
    description: user.id,
  })),
)
const trackOptions = computed(() =>
  (directory.value?.tracks || []).map((track) => ({ value: track.name, label: track.name })),
)
const permissions = computed(
  () => result.value?.nodes.filter((node) => node.type === 'permission') || [],
)

async function loadDirectory({ quiet = false } = {}) {
  try {
    directory.value = await stonePermsApi.directory(serverId.value)
  } catch {
    if (!quiet) directory.value = null
  }
}
async function search(nextIdentifier = identifier.value, { quiet = false } = {}) {
  if (!String(nextIdentifier).trim()) return
  identifier.value = String(nextIdentifier).trim()
  if (!quiet) {
    loading.value = true
    searched.value = true
    result.value = null
  }
  try {
    result.value = await stonePermsApi.player(serverId.value, identifier.value)
    searched.value = true
    selectedTrack.value = directory.value?.tracks[0]?.name || ''
  } catch (cause) {
    if (!quiet) toasts.error(cause.userMessage || cause.message)
  } finally {
    if (!quiet) loading.value = false
  }
}
async function move(direction) {
  if (!selectedTrack.value) return
  moving.value = true
  try {
    const moveResult = await stonePermsApi.movePlayer(
      serverId.value,
      player.value.id,
      selectedTrack.value,
      direction,
    )
    toasts.success(`${titleCase(moveResult.status)} on ${moveResult.track}.`)
    await search()
  } catch (cause) {
    toasts.error(cause.userMessage || cause.message)
  } finally {
    moving.value = false
  }
}

onMounted(loadDirectory)
watch(serverId, () => {
  result.value = null
  searched.value = false
  void loadDirectory()
})
useLiveRefresh(async () => {
  await loadDirectory({ quiet: true })
  if (result.value && identifier.value) await search(identifier.value, { quiet: true })
})
</script>

<template>
  <header class="page-heading">
    <h1>Players</h1>
  </header>
  <form class="player-search panel" @submit.prevent="search()">
    <CustomSelect
      v-model="identifier"
      :options="playerOptions"
      placeholder="Player name, UUID or XUID"
      empty-text="No matching known player"
      aria-label="Player name, UUID or XUID"
      editable
      searchable
    />
    <button class="button primary" type="submit" :disabled="loading || !identifier.trim()">
      {{ loading ? 'Loading…' : 'Inspect player' }}
    </button>
  </form>

  <LoadingBlock v-if="loading" :rows="6" />
  <section v-else-if="player" class="panel-grid">
    <article class="panel span-5">
      <header class="panel-header">
        <h3>Player</h3>
        <span :class="['status-label', profile?.online ? 'is-online' : '']">{{
          profile?.online ? 'ONLINE' : 'OFFLINE'
        }}</span>
      </header>
      <div class="player-profile">
        <PlayerAvatar :server-id="serverId" :player="player" :size="84" />
        <div>
          <h3>{{ player.name || 'Unknown name' }}</h3>
          <code>{{ player.id }}</code
          ><small v-if="player.xuid">XUID {{ player.xuid }}</small
          ><small>{{
            profile ? relativeTime(profile.lastSeenAt) : 'Profile not captured yet'
          }}</small>
        </div>
      </div>
      <div class="panel-body detail-list">
        <div>
          <span>Primary group</span><strong>{{ result.primaryGroup }}</strong>
        </div>
        <div>
          <span>Effective groups</span><strong>{{ result.effectiveGroups.join(', ') }}</strong>
        </div>
        <div>
          <span>Prefix / suffix</span
          ><strong>{{ result.prefix || '—' }} / {{ result.suffix || '—' }}</strong>
        </div>
        <div>
          <span>Resolved metadata</span><strong>{{ Object.keys(result.meta).length }} keys</strong>
        </div>
      </div>
      <div v-if="store.canEdit()" class="panel-body player-operations">
        <RouterLink
          class="button primary full"
          :to="{ path: `/servers/${serverId}/editor`, query: { user: player.id } }"
          ><AppIcon name="editor" />Edit player permissions</RouterLink
        >
        <div class="track-move-control">
          <CustomSelect
            v-model="selectedTrack"
            :options="trackOptions"
            placeholder="Choose track…"
            aria-label="Promotion track"
            compact
          />
          <button
            class="button"
            type="button"
            :disabled="moving || !selectedTrack"
            @click="move('demote')"
          >
            Demote</button
          ><button
            class="button"
            type="button"
            :disabled="moving || !selectedTrack"
            @click="move('promote')"
          >
            Promote
          </button>
        </div>
      </div>
    </article>

    <article class="panel span-7">
      <header class="panel-header">
        <h3>Player profile</h3>
        <span>Captured by Endstone</span>
      </header>
      <div v-if="profile" class="profile-facts">
        <div>
          <span>Platform</span><strong>{{ profile.deviceOs || 'Unknown' }}</strong
          ><small>Bedrock device OS</small>
        </div>
        <div>
          <span>Client</span><strong>{{ profile.gameVersion || '—' }}</strong
          ><small>{{ profile.locale || 'No locale' }}</small>
        </div>
        <div>
          <span>Game mode</span><strong>{{ titleCase(profile.gameMode) || '—' }}</strong
          ><small>{{ profile.pingMs === null ? 'No ping' : `${profile.pingMs} ms ping` }}</small>
        </div>
        <div>
          <span>Experience</span><strong>Level {{ profile.expLevel ?? '—' }}</strong
          ><small>{{ profile.totalExp ?? '—' }} total XP</small>
        </div>
        <div>
          <span>First seen</span><strong>{{ formatDate(profile.firstSeenAt) }}</strong
          ><small>First StonePerms observation</small>
        </div>
        <div>
          <span>Last joined</span><strong>{{ formatDate(profile.lastJoinedAt) }}</strong
          ><small>Last quit {{ formatDate(profile.lastQuitAt) }}</small>
        </div>
      </div>
      <header class="panel-header subsection-header">
        <h3>Skin data</h3>
        <span>{{ profile?.skinWidth || '—' }}×{{ profile?.skinHeight || '—' }}</span>
      </header>
      <div class="panel-body detail-list">
        <div>
          <span>Skin ID</span><code>{{ profile?.skinId || 'Not captured' }}</code>
        </div>
        <div>
          <span>Skin fingerprint</span><code>{{ profile?.skinHash || 'Not captured' }}</code>
        </div>
        <div>
          <span>Skin updated</span><strong>{{ formatDate(profile?.skinUpdatedAt) }}</strong>
        </div>
        <div>
          <span>Cape ID</span><code>{{ profile?.capeId || 'None' }}</code>
        </div>
      </div>
    </article>

    <article class="panel span-7">
      <header class="panel-header">
        <h3>Direct permission nodes</h3>
        <span>{{ permissions.length }} nodes</span>
      </header>
      <div v-if="permissions.length" class="responsive-table">
        <table class="data-table">
          <thead>
            <tr>
              <th>Permission</th>
              <th>Value</th>
              <th>Contexts</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="node in permissions" :key="`${node.key}:${node.contexts}`">
              <td class="primary-cell">{{ node.key }}</td>
              <td>
                <span :class="['decision-value', node.value === 'true' ? 'is-allow' : 'is-deny']">{{
                  node.value === 'true' ? 'Allow' : 'Deny'
                }}</span>
              </td>
              <td>
                {{
                  node.contexts.map((item) => `${item.key}=${item.value}`).join(', ') || 'Global'
                }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <EmptyState
        v-else
        icon="shield"
        title="No direct permissions"
        description="This player currently receives permissions through groups and defaults."
      />
    </article>
    <article class="panel span-5">
      <header class="panel-header">
        <h3>Promotion positions</h3>
        <span>{{ Object.keys(result.tracks).length }} tracks</span>
      </header>
      <div class="panel-body tag-list">
        <span v-for="(groups, track) in result.tracks" :key="track"
          ><strong>{{ track }}</strong
          >{{ groups.join(' → ') }}</span
        >
        <p v-if="!Object.keys(result.tracks).length">
          The player is not directly assigned to a group on any track.
        </p>
      </div>
      <header class="panel-header subsection-header">
        <h3>Resolved metadata</h3>
        <span>{{ Object.keys(result.meta).length }} keys</span>
      </header>
      <div class="panel-body tag-list">
        <span v-for="(value, key) in result.meta" :key="key"
          ><strong>{{ key }}</strong
          >{{ value }}</span
        >
        <p v-if="!Object.keys(result.meta).length">No resolved metadata.</p>
      </div>
    </article>
  </section>

  <EmptyState
    v-else-if="searched"
    icon="users"
    title="Player not found"
    description="The player must have joined this server once or be addressed by a known UUID."
  />
  <section v-else-if="directory?.users?.length" class="panel">
    <header class="panel-header">
      <h3>Known players</h3>
      <span>{{ directory.users.length }} profiles</span>
    </header>
    <div class="player-directory">
      <button
        v-for="user in directory.users"
        :key="user.id"
        type="button"
        class="player-directory-card"
        @click="search(user.id)"
      >
        <PlayerAvatar :server-id="serverId" :player="user" :size="56" />
        <span
          ><strong>{{ user.name }}</strong
          ><small
            >{{ user.deviceOs || 'Unknown platform' }} ·
            {{ user.gameVersion || 'Unknown client' }}</small
          ><small>{{
            user.online ? 'Online now' : `Last seen ${relativeTime(user.lastSeenAt)}`
          }}</small></span
        >
        <i :class="['online-dot', { 'is-online': user.online }]" aria-hidden="true"></i>
      </button>
    </div>
  </section>
  <EmptyState
    v-else
    icon="search"
    title="No known players yet"
    description="Profiles appear after players join this Endstone server once."
  />
</template>
