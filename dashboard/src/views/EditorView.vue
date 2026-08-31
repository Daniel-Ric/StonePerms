<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import BaseModal from '@/components/BaseModal.vue'
import CustomDateTimePicker from '@/components/CustomDateTimePicker.vue'
import CustomSelect from '@/components/CustomSelect.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import { stonePermsApi } from '@/services/api'
import { toasts } from '@/services/toasts'
import { useStonePermsStore } from '@/stores/stoneperms'
import {
  blankNode,
  changedSubjects,
  changedTracks,
  clone,
  expiryInput,
  expiryTimestamp,
  NODE_TYPES,
  nodeSlot,
  nodeTitle,
  normalizeNode,
} from '@/lib/editor'
import { formatDate, relativeTime, titleCase } from '@/lib/format'

const route = useRoute()
const store = useStonePermsStore()
const session = ref(null)
const baseline = ref(null)
const loading = ref(false)
const applying = ref(false)
const scopeOpen = ref(false)
const reviewOpen = ref(false)
const nodeOpen = ref(false)
const scopeUsers = ref(typeof route.query.user === 'string' ? route.query.user : '')
const includeGroups = ref(true)
const includeTracks = ref(true)
const holderQuery = ref('')
const selectedKey = ref('')
const activeTab = ref('nodes')
const editingIndex = ref(-1)
const draft = ref(blankNode())
const draftExpiry = ref('')
const draftContextKey = ref('')
const draftContextValue = ref('')
const editorError = ref('')
const now = ref(Math.floor(Date.now() / 1000))
let clock

const canEdit = computed(() => store.canEdit())
const subjects = computed(() => session.value?.subjects || [])
const tracks = computed(() => session.value?.tracks || [])
const selectedSubject = computed(
  () => subjects.value.find((item) => `${item.type}:${item.id}` === selectedKey.value) || null,
)
const selectedTrack = computed(
  () => tracks.value.find((item) => `track:${item.name}` === selectedKey.value) || null,
)
const groups = computed(() => session.value?.metadata?.groups || [])
const filteredSubjects = computed(() =>
  subjects.value.filter((item) =>
    `${item.id} ${item.displayName || item.name || ''}`
      .toLowerCase()
      .includes(holderQuery.value.toLowerCase()),
  ),
)
const filteredTracks = computed(() =>
  tracks.value.filter((item) => item.name.toLowerCase().includes(holderQuery.value.toLowerCase())),
)
const subjectChanges = computed(() =>
  session.value && baseline.value ? changedSubjects(session.value, baseline.value) : [],
)
const trackChanges = computed(() =>
  session.value && baseline.value ? changedTracks(session.value, baseline.value) : [],
)
const changeCount = computed(() => subjectChanges.value.length + trackChanges.value.length)
const secondsLeft = computed(() => Math.max(0, (session.value?.expiresAt || 0) - now.value))
const expiryLabel = computed(() =>
  secondsLeft.value
    ? `${Math.floor(secondsLeft.value / 60)}:${String(secondsLeft.value % 60).padStart(2, '0')}`
    : 'Expired',
)
const nodeStats = computed(() => {
  const nodes = selectedSubject.value?.nodes || []
  return NODE_TYPES.reduce(
    (result, type) => ({ ...result, [type]: nodes.filter((node) => node.type === type).length }),
    {},
  )
})
const nodeTypeOptions = NODE_TYPES.map((type) => ({ value: type, label: titleCase(type) }))
const decisionOptions = [
  { value: 'true', label: 'Allow' },
  { value: 'false', label: 'Deny' },
]
const availableTrackGroupOptions = computed(() =>
  groups.value
    .filter((group) => !selectedTrack.value?.groups.includes(group.name))
    .map((group) => ({ value: group.name, label: group.displayName, description: group.name })),
)
const permissionOptions = computed(() =>
  (session.value?.knownPermissions || []).map((permission) => ({
    value: permission,
    label: permission,
  })),
)
const parentGroupOptions = computed(() =>
  groups.value.map((group) => ({
    value: group.name,
    label: group.name,
    description: group.displayName,
  })),
)
const contextKeyOptions = computed(() =>
  (session.value?.potentialContexts || []).map((context) => ({
    value: context.key,
    label: context.key,
  })),
)

function userScope() {
  return [
    ...new Set(
      scopeUsers.value
        .split(/[\n,]+/)
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  ]
}
async function createSession() {
  if (!includeGroups.value && !includeTracks.value && !userScope().length) {
    editorError.value = 'Select groups, tracks or at least one player.'
    return
  }
  loading.value = true
  editorError.value = ''
  try {
    const result = await stonePermsApi.createEditorSession(String(route.params.serverId), {
      users: userScope(),
      includeGroups: includeGroups.value,
      includeTracks: includeTracks.value,
    })
    session.value = result
    baseline.value = clone(result)
    scopeOpen.value = false
    const requestedHolder = typeof route.query.holder === 'string' ? route.query.holder : ''
    const holderExists =
      result.subjects?.some((item) => `${item.type}:${item.id}` === requestedHolder) ||
      result.tracks?.some((item) => `track:${item.name}` === requestedHolder)
    selectedKey.value = holderExists
      ? requestedHolder
      : result.subjects?.[0]
        ? `${result.subjects[0].type}:${result.subjects[0].id}`
        : result.tracks?.[0]
          ? `track:${result.tracks[0].name}`
          : ''
  } catch (cause) {
    editorError.value = cause.userMessage || cause.message
  } finally {
    loading.value = false
  }
}
function discard() {
  if (!baseline.value) return
  session.value = clone(baseline.value)
  reviewOpen.value = false
  toasts.info('Local editor changes were discarded.')
}
function openNode(index = -1) {
  editingIndex.value = index
  draft.value = index >= 0 ? clone(selectedSubject.value.nodes[index]) : blankNode()
  draftExpiry.value = expiryInput(draft.value.expiresAt)
  draftContextKey.value = ''
  draftContextValue.value = ''
  editorError.value = ''
  nodeOpen.value = true
}
function changeNodeType() {
  const replacement = blankNode(draft.value.type)
  replacement.contexts = draft.value.contexts || []
  draft.value = replacement
}
function addContext() {
  const key = draftContextKey.value.trim().toLowerCase(),
    value = draftContextValue.value.trim().toLowerCase()
  if (!key || !value) return
  draft.value.contexts.push({ key, value })
  draftContextKey.value = ''
  draftContextValue.value = ''
}
function saveNode() {
  editorError.value = ''
  try {
    draft.value.expiresAt = expiryTimestamp(draftExpiry.value)
    const node = normalizeNode(draft.value)
    const duplicate = selectedSubject.value.nodes.some(
      (item, index) => index !== editingIndex.value && nodeSlot(item) === nodeSlot(node),
    )
    if (duplicate)
      throw new Error('A node already occupies this type, context, expiry and priority slot.')
    if (
      node.type === 'parent' &&
      selectedSubject.value.type === 'group' &&
      node.key === selectedSubject.value.id
    )
      throw new Error('A group cannot inherit from itself.')
    if (editingIndex.value >= 0) selectedSubject.value.nodes.splice(editingIndex.value, 1, node)
    else selectedSubject.value.nodes.push(node)
    nodeOpen.value = false
  } catch (cause) {
    editorError.value = cause.message
  }
}
function removeNode(index) {
  selectedSubject.value.nodes.splice(index, 1)
}
function moveTrack(index, offset) {
  const next = index + offset
  if (next < 0 || next >= selectedTrack.value.groups.length) return
  const [group] = selectedTrack.value.groups.splice(index, 1)
  selectedTrack.value.groups.splice(next, 0, group)
}
function removeTrackGroup(index) {
  selectedTrack.value.groups.splice(index, 1)
}
function addTrackGroup(name) {
  if (name && !selectedTrack.value.groups.includes(name)) selectedTrack.value.groups.push(name)
}
async function applyChanges() {
  applying.value = true
  editorError.value = ''
  const payload = {
    schema: 'stoneperms.editor/changes',
    version: 1,
    sessionId: session.value.sessionId,
    baseRevision: session.value.baseRevision,
    subjects: subjectChanges.value,
    tracks: trackChanges.value,
  }
  try {
    const result = await stonePermsApi.applyEditorChanges(String(route.params.serverId), payload)
    reviewOpen.value = false
    toasts.success(
      `Applied ${result.changedSubjects} subject and ${result.changedTracks} track change${result.changedTracks === 1 ? '' : 's'}.`,
    )
    scopeOpen.value = false
    session.value = null
    baseline.value = null
  } catch (cause) {
    editorError.value = cause.userMessage || cause.message
    if (
      ['STALE_EDITOR_SESSION', 'EDITOR_SESSION_EXPIRED', 'EDITOR_SESSION_CONSUMED'].includes(
        cause.code,
      )
    )
      toasts.warning('Create a fresh editor session before retrying.')
  } finally {
    applying.value = false
  }
}
onMounted(() => {
  clock = window.setInterval(() => {
    now.value = Math.floor(Date.now() / 1000)
  }, 1000)
})
onBeforeUnmount(() => window.clearInterval(clock))
watch(
  () => route.params.serverId,
  () => {
    session.value = null
    baseline.value = null
    scopeOpen.value = false
  },
)
</script>

<template>
  <header class="page-heading editor-heading">
    <h1>Permission editor</h1>
    <div class="page-actions">
      <button v-if="session" class="button" type="button" @click="scopeOpen = true">
        <AppIcon name="refresh" />New session</button
      ><button
        v-if="session && canEdit"
        class="button primary"
        type="button"
        :disabled="!changeCount || secondsLeft === 0"
        @click="reviewOpen = true"
      >
        <AppIcon name="check" />Review {{ changeCount }} change{{ changeCount === 1 ? '' : 's' }}
      </button>
    </div>
  </header>
  <LoadingBlock v-if="loading" :rows="7" />
  <EmptyState
    v-else-if="!session"
    icon="editor"
    title="Start an editor session"
    description="Load the groups, tracks, and players you want to edit."
    ><button class="button primary" type="button" @click="scopeOpen = true">
      Start session
    </button></EmptyState
  >
  <section v-else class="editor-workspace">
    <aside class="editor-holders panel">
      <header class="panel-header">
        <div>
          <h3>Data holders</h3>
          <small>{{ subjects.length }} subjects · {{ tracks.length }} tracks</small>
        </div>
      </header>
      <div class="holder-search">
        <label class="search-field"
          ><AppIcon name="search" :size="15" /><input
            v-model="holderQuery"
            type="search"
            placeholder="Filter holders"
        /></label>
      </div>
      <nav aria-label="Editor data holders">
        <span class="holder-section">Groups & players</span
        ><button
          v-for="item in filteredSubjects"
          :key="`${item.type}:${item.id}`"
          :class="['holder-row', selectedKey === `${item.type}:${item.id}` && 'is-active']"
          type="button"
          @click="selectedKey = `${item.type}:${item.id}`"
        >
          <AppIcon :name="item.type === 'group' ? 'group' : 'users'" :size="16" /><span
            ><strong>{{ item.displayName || item.name || item.id }}</strong
            ><small>{{ item.type }} · {{ item.nodes.length }} direct nodes</small></span
          ></button
        ><span v-if="tracks.length" class="holder-section">Promotion tracks</span
        ><button
          v-for="track in filteredTracks"
          :key="`track:${track.name}`"
          :class="['holder-row', selectedKey === `track:${track.name}` && 'is-active']"
          type="button"
          @click="selectedKey = `track:${track.name}`"
        >
          <AppIcon name="track" :size="16" /><span
            ><strong>{{ track.name }}</strong
            ><small>{{ track.groups.length }} ladder groups</small></span
          >
        </button>
      </nav>
    </aside>
    <main class="editor-main panel">
      <template v-if="selectedSubject"
        ><header class="editor-subject-header">
          <div>
            <span class="eyebrow">{{ titleCase(selectedSubject.type) }}</span>
            <h3>{{ selectedSubject.displayName || selectedSubject.name || selectedSubject.id }}</h3>
            <p>
              {{ selectedSubject.id
              }}<template v-if="selectedSubject.type === 'group'">
                · weight {{ selectedSubject.weight }}</template
              >
            </p>
          </div>
          <div class="session-clock">
            <AppIcon name="clock" :size="15" /><span
              ><small>SESSION EXPIRES</small><strong>{{ expiryLabel }}</strong></span
            >
          </div>
        </header>
        <div class="tabs">
          <button
            :class="activeTab === 'nodes' && 'is-active'"
            type="button"
            @click="activeTab = 'nodes'"
          >
            Direct nodes <span>{{ selectedSubject.nodes.length }}</span></button
          ><button
            :class="activeTab === 'summary' && 'is-active'"
            type="button"
            @click="activeTab = 'summary'"
          >
            Holder summary
          </button>
        </div>
        <div v-if="activeTab === 'nodes'" class="editor-content">
          <div class="editor-toolbar">
            <div class="node-summary">
              <span v-for="type in NODE_TYPES" :key="type"
                ><strong>{{ nodeStats[type] }}</strong
                >{{ titleCase(type) }}</span
              >
            </div>
            <button v-if="canEdit" class="button primary" type="button" @click="openNode()">
              <AppIcon name="plus" />Add node
            </button>
          </div>
          <div v-if="selectedSubject.nodes.length" class="node-list">
            <article
              v-for="(node, index) in selectedSubject.nodes"
              :key="`${nodeSlot(node)}:${index}`"
              class="node-row"
            >
              <span :class="['node-type', `is-${node.type}`]">{{
                node.type.slice(0, 1).toUpperCase()
              }}</span>
              <div>
                <strong>{{ nodeTitle(node) }}</strong>
                <div class="node-meta">
                  <span :class="node.value === 'false' && 'is-negative'">{{
                    node.type === 'permission' ? node.value : titleCase(node.type)
                  }}</span
                  ><span v-if="node.priority">priority {{ node.priority }}</span
                  ><span v-for="context in node.contexts" :key="`${context.key}:${context.value}`"
                    >{{ context.key }}={{ context.value }}</span
                  ><span v-if="node.expiresAt">expires {{ relativeTime(node.expiresAt) }}</span>
                </div>
              </div>
              <div v-if="canEdit" class="table-actions">
                <button class="button small" type="button" @click="openNode(index)">Edit</button
                ><button
                  class="button small danger"
                  type="button"
                  aria-label="Remove node"
                  @click="removeNode(index)"
                >
                  <AppIcon name="trash" :size="14" />
                </button>
              </div>
            </article>
          </div>
          <EmptyState
            v-else
            icon="shield"
            title="No direct nodes"
            description="Permissions currently come from groups or defaults."
          />
        </div>
        <div v-else class="editor-content">
          <section class="holder-summary-grid">
            <article>
              <span>Direct nodes</span><strong>{{ selectedSubject.nodes.length }}</strong>
            </article>
            <article>
              <span>Contexts used</span
              ><strong>{{
                new Set(
                  selectedSubject.nodes.flatMap((node) => node.contexts.map((item) => item.key)),
                ).size
              }}</strong>
            </article>
            <article>
              <span>Temporary nodes</span
              ><strong>{{ selectedSubject.nodes.filter((node) => node.expiresAt).length }}</strong>
            </article>
            <article>
              <span>Denied permissions</span
              ><strong>{{
                selectedSubject.nodes.filter(
                  (node) => node.type === 'permission' && node.value === 'false',
                ).length
              }}</strong>
            </article>
          </section>
          <p class="protocol-note">
            <AppIcon name="shield" />Snapshot revision {{ session.baseRevision }}. The plugin
            calculates effective permissions from these nodes.
          </p>
        </div>
      </template>
      <template v-else-if="selectedTrack"
        ><header class="editor-subject-header">
          <div>
            <span class="eyebrow">Track</span>
            <h3>{{ selectedTrack.name }}</h3>
            <p>Ordered independently from inheritance · {{ selectedTrack.groups.length }} groups</p>
          </div>
          <div class="session-clock">
            <AppIcon name="clock" :size="15" /><span
              ><small>SESSION EXPIRES</small><strong>{{ expiryLabel }}</strong></span
            >
          </div>
        </header>
        <div class="editor-content">
          <div class="track-editor-toolbar">
            <div>
              <h4>Promotion ladder</h4>
              <p>Players move from top to bottom when promoted.</p>
            </div>
            <label v-if="canEdit" class="field compact-add"
              ><span class="sr-only">Add group</span
              ><CustomSelect
                :model-value="''"
                :options="availableTrackGroupOptions"
                placeholder="Add group…"
                search-placeholder="Filter groups"
                empty-text="All groups are already on this track"
                aria-label="Add group to track"
                searchable
                compact
                @update:model-value="addTrackGroup"
            /></label>
          </div>
          <ol v-if="selectedTrack.groups.length" class="track-ladder">
            <li v-for="(groupName, index) in selectedTrack.groups" :key="groupName">
              <span class="track-index">{{ String(index + 1).padStart(2, '0') }}</span
              ><span class="track-rail"></span>
              <div>
                <strong>{{
                  groups.find((group) => group.name === groupName)?.displayName || groupName
                }}</strong
                ><small>{{ groupName }}</small>
              </div>
              <div v-if="canEdit" class="table-actions">
                <button
                  class="icon-button"
                  type="button"
                  :disabled="index === 0"
                  aria-label="Move up"
                  @click="moveTrack(index, -1)"
                >
                  ↑</button
                ><button
                  class="icon-button"
                  type="button"
                  :disabled="index === selectedTrack.groups.length - 1"
                  aria-label="Move down"
                  @click="moveTrack(index, 1)"
                >
                  ↓</button
                ><button
                  class="icon-button"
                  type="button"
                  aria-label="Remove from track"
                  @click="removeTrackGroup(index)"
                >
                  <AppIcon name="trash" :size="14" />
                </button>
              </div>
            </li>
          </ol>
          <EmptyState
            v-else
            icon="track"
            title="Empty promotion track"
            description="Add groups in the order players should progress through them."
          /></div
      ></template>
      <EmptyState
        v-else
        icon="search"
        title="Choose a data holder"
        description="Select a group, player or track from the editor sidebar."
      />
    </main>
  </section>

  <BaseModal
    v-if="scopeOpen"
    title="Start editor session"
    description="Choose what to load. The session remains open for 15 minutes."
    @close="scopeOpen = false"
    ><div class="scope-grid">
      <label class="scope-card"
        ><input v-model="includeGroups" type="checkbox" /><AppIcon name="group" /><span
          ><strong>All groups</strong><small>Direct nodes and read-only group metadata</small></span
        ></label
      ><label class="scope-card"
        ><input v-model="includeTracks" type="checkbox" /><AppIcon name="track" /><span
          ><strong>All tracks</strong
          ><small>Read and reorder existing promotion ladders</small></span
        ></label
      >
    </div>
    <div class="field" style="margin-top: 14px">
      <label for="scope-users">Players (optional)</label
      ><textarea
        id="scope-users"
        v-model="scopeUsers"
        placeholder="Player name or UUID, separated by commas or new lines"
      ></textarea
      ><small>Player records are loaded only when explicitly named.</small>
    </div>
    <p v-if="editorError" class="form-error" role="alert">{{ editorError }}</p>
    <template #footer
      ><button class="button" type="button" @click="scopeOpen = false">Cancel</button
      ><button class="button primary" type="button" :disabled="loading" @click="createSession">
        <AppIcon name="editor" />{{ loading ? 'Loading…' : 'Start session' }}
      </button></template
    ></BaseModal
  >

  <BaseModal
    v-if="nodeOpen"
    :title="editingIndex >= 0 ? 'Edit direct node' : 'Add direct node'"
    description="The server checks the node before it is saved."
    wide
    @close="nodeOpen = false"
    ><div class="form-grid">
      <div class="field">
        <label>Node type</label>
        <CustomSelect
          v-model="draft.type"
          :options="nodeTypeOptions"
          aria-label="Node type"
          @change="changeNodeType"
        />
      </div>
      <div v-if="draft.type === 'permission'" class="field">
        <label>Value</label>
        <CustomSelect v-model="draft.value" :options="decisionOptions" aria-label="Value" />
      </div>
      <div v-else-if="draft.type === 'prefix' || draft.type === 'suffix'" class="field">
        <label>Priority</label><input v-model.number="draft.priority" type="number" step="1" />
      </div>
      <div v-if="draft.type !== 'prefix' && draft.type !== 'suffix'" class="field full">
        <label>{{
          draft.type === 'parent'
            ? 'Parent group'
            : draft.type === 'meta'
              ? 'Meta key'
              : 'Permission'
        }}</label
        ><CustomSelect
          v-if="draft.type === 'permission'"
          v-model="draft.key"
          :options="permissionOptions"
          placeholder="plugin.feature.use"
          empty-text="No matching known permission — you can still enter it"
          aria-label="Permission"
          editable
          searchable
        />
        <CustomSelect
          v-else-if="draft.type === 'parent'"
          v-model="draft.key"
          :options="parentGroupOptions"
          placeholder="member"
          empty-text="No matching group — you can still enter it"
          aria-label="Parent group"
          editable
          searchable
        />
        <input v-else v-model="draft.key" placeholder="chat-color" />
      </div>
      <div v-if="draft.type !== 'parent' && draft.type !== 'permission'" class="field full">
        <label>{{ titleCase(draft.type) }} value</label
        ><input v-model="draft.value" placeholder="Value" />
      </div>
      <div class="field full">
        <label>Expiry (optional)</label>
        <CustomDateTimePicker
          v-model="draftExpiry"
          placeholder="Permanent — no expiry"
          aria-label="Choose expiry date and time"
        />
        <small>Leave empty for a permanent node. Times use your local timezone.</small>
      </div>
      <div class="field full">
        <label>Contexts</label>
        <div class="context-composer">
          <CustomSelect
            v-model="draftContextKey"
            :options="contextKeyOptions"
            placeholder="Key"
            empty-text="No matching known context — you can still enter it"
            aria-label="Context key"
            editable
            searchable
          />
          <input v-model="draftContextValue" placeholder="Value" @keyup.enter="addContext" /><button
            class="button"
            type="button"
            @click="addContext"
          >
            <AppIcon name="plus" />Add
          </button>
        </div>
        <div v-if="draft.contexts.length" class="context-tags">
          <button
            v-for="(context, index) in draft.contexts"
            :key="`${context.key}:${context.value}`"
            type="button"
            @click="draft.contexts.splice(index, 1)"
          >
            {{ context.key }}={{ context.value }} <span>×</span>
          </button>
        </div>
        <small>Values sharing one key are alternatives; different keys must all match.</small>
      </div>
    </div>
    <p v-if="editorError" class="form-error" role="alert">{{ editorError }}</p>
    <template #footer
      ><button class="button" type="button" @click="nodeOpen = false">Cancel</button
      ><button class="button primary" type="button" @click="saveNode">Save node</button></template
    ></BaseModal
  >

  <BaseModal
    v-if="reviewOpen"
    title="Review changes"
    :description="`Revision ${session.baseRevision} · session expires ${formatDate(session.expiresAt)}`"
    wide
    @close="reviewOpen = false"
    ><div class="review-summary">
      <article>
        <strong>{{ subjectChanges.length }}</strong
        ><span>Changed subjects</span>
      </article>
      <article>
        <strong>{{ trackChanges.length }}</strong
        ><span>Changed tracks</span>
      </article>
      <article>
        <strong>{{
          subjectChanges.reduce((count, subject) => count + subject.nodes.length, 0)
        }}</strong
        ><span>Resulting direct nodes</span>
      </article>
    </div>
    <div class="change-review">
      <section v-for="subject in subjectChanges" :key="`${subject.type}:${subject.id}`">
        <header>
          <AppIcon :name="subject.type === 'group' ? 'group' : 'users'" /><strong>{{
            subject.id
          }}</strong
          ><span>{{ subject.nodes.length }} resulting nodes</span>
        </header>
      </section>
      <section v-for="track in trackChanges" :key="track.name">
        <header>
          <AppIcon name="track" /><strong>{{ track.name }}</strong
          ><span>{{ track.groups.join(' → ') || 'Empty track' }}</span>
        </header>
      </section>
    </div>
    <p class="protocol-note">
      <AppIcon name="warning" />StonePerms applies the complete changeset in one transaction. If the
      repository revision changed, nothing is written and a fresh session is required.
    </p>
    <p v-if="editorError" class="form-error" role="alert">{{ editorError }}</p>
    <template #footer
      ><button class="button danger" type="button" @click="discard">Discard changes</button
      ><button class="button" type="button" @click="reviewOpen = false">Keep editing</button
      ><button
        class="button primary"
        type="button"
        :disabled="applying || secondsLeft === 0"
        @click="applyChanges"
      >
        <AppIcon name="check" />{{ applying ? 'Applying…' : 'Apply changes' }}
      </button></template
    ></BaseModal
  >
</template>
