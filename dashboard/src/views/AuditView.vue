<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import CustomSelect from '@/components/CustomSelect.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { useLiveRefresh } from '@/composables/useLiveRefresh'
import { stonePermsApi } from '@/services/api'
import { toasts } from '@/services/toasts'
import { auditActionLabel, formatDate } from '@/lib/format'

const route = useRoute()
const outcomeOptions = [
  { value: 'all', label: 'All outcomes' },
  { value: 'success', label: 'Success' },
  { value: 'failed', label: 'Failed' },
]
const limitOptions = [25, 50, 100, 200].map((value) => ({
  value,
  label: `${value} entries`,
}))
const entries = ref([])
const loading = ref(true)
const query = ref('')
const outcome = ref('all')
const limit = ref(50)
const source = ref('api')
const serverId = computed(() =>
  route.name === 'server-audit' ? String(route.params.serverId) : undefined,
)
const filtered = computed(() =>
  entries.value.filter((entry) => {
    const haystack =
      `${entry.action} ${entry.actorUsername || ''} ${entry.target || ''}`.toLowerCase()
    return (
      haystack.includes(query.value.toLowerCase()) &&
      (outcome.value === 'all' || entry.outcome === outcome.value)
    )
  }),
)
async function load({ quiet = false } = {}) {
  if (!quiet) loading.value = true
  try {
    const response =
      source.value === 'plugin' && serverId.value
        ? await stonePermsApi.pluginAudit(serverId.value, limit.value)
        : await stonePermsApi.audit({ serverId: serverId.value, limit: limit.value })
    entries.value = (response.entries || []).map((entry) =>
      entry.created_at
        ? {
            id: entry.id,
            actorUsername: entry.actor,
            serverId: serverId.value,
            action: entry.action,
            target:
              [entry.subject_type, entry.subject_id].filter(Boolean).join(':') ||
              JSON.stringify(entry.details || {}),
            outcome: 'success',
            createdAt: entry.created_at,
          }
        : entry,
    )
  } catch (cause) {
    if (!quiet) toasts.error(cause.userMessage || cause.message)
  } finally {
    if (!quiet) loading.value = false
  }
}
onMounted(load)
watch([serverId, limit, source], () => void load())
useLiveRefresh(() => load({ quiet: true }))
</script>

<template>
  <header class="page-heading">
    <h1>{{ serverId ? 'Server audit' : 'API audit' }}</h1>
  </header>
  <div v-if="serverId" class="tabs audit-source-tabs">
    <button :class="source === 'api' && 'is-active'" type="button" @click="source = 'api'">
      Dashboard activity</button
    ><button :class="source === 'plugin' && 'is-active'" type="button" @click="source = 'plugin'">
      Permission changes
    </button>
  </div>
  <article class="panel">
    <header class="panel-header audit-filters">
      <label class="search-field"
        ><AppIcon name="search" :size="15" /><input
          v-model="query"
          type="search"
          placeholder="Filter action, operator or target"
      /></label>
      <div>
        <CustomSelect
          v-model="outcome"
          :options="outcomeOptions"
          aria-label="Filter outcome"
          compact
        />
        <CustomSelect v-model="limit" :options="limitOptions" aria-label="Entry limit" compact />
      </div>
    </header>
    <LoadingBlock v-if="loading" :rows="7" />
    <div v-else-if="filtered.length" class="responsive-table">
      <table class="data-table mobile-cards">
        <thead>
          <tr>
            <th>Outcome</th>
            <th>Action</th>
            <th>Operator</th>
            <th>Target</th>
            <th>Server</th>
            <th>Timestamp</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="entry in filtered" :key="entry.id">
            <td data-label="Outcome">
              <StatusBadge
                :state="entry.outcome === 'success' ? 'success' : 'failed'"
                :label="entry.outcome"
              />
            </td>
            <td data-label="Action">
              <span class="primary-cell">{{ auditActionLabel(entry.action) }}</span
              ><span class="secondary-cell mono">{{ entry.action }} · Event #{{ entry.id }}</span>
            </td>
            <td data-label="Operator">{{ entry.actorUsername || 'Plugin principal' }}</td>
            <td data-label="Target">
              <code>{{ entry.target || '—' }}</code>
            </td>
            <td data-label="Server">
              <code>{{ entry.serverId || 'System' }}</code>
            </td>
            <td data-label="Timestamp">{{ formatDate(entry.createdAt) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <EmptyState
      v-else
      icon="audit"
      title="No matching events"
      description="No audit entry matches the current filters."
    />
  </article>
</template>
