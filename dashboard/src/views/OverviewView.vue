<script setup>
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import EmptyState from '@/components/EmptyState.vue'
import PermissionActivityChart from '@/components/PermissionActivityChart.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { useLiveRefresh } from '@/composables/useLiveRefresh'
import { stonePermsApi } from '@/services/api'
import { useStonePermsStore } from '@/stores/stoneperms'
import { buildPermissionActivity, isPermissionActivity } from '@/lib/activity'
import { auditActionLabel, relativeTime, titleCase } from '@/lib/format'

const store = useStonePermsStore()
const audit = ref([])
const loading = ref(true)
const selectedServer = computed(() => store.selectedServer)
const activityChart = computed(() => buildPermissionActivity(audit.value))
const activitySuccessRate = computed(() => {
  if (!activityChart.value.total) return null

  return Math.round(
    ((activityChart.value.total - activityChart.value.failures) / activityChart.value.total) * 100,
  )
})
const activityCoverage = computed(() => {
  if (!activityChart.value.buckets.length) return 0

  return Math.round((activityChart.value.activeBuckets / activityChart.value.buckets.length) * 100)
})
const activityChartLabel = computed(
  () =>
    `${activityChart.value.total} permission operations in the last 24 hours, including ${activityChart.value.failures} failed operations.`,
)
const permissionActivity = computed(() => audit.value.filter(isPermissionActivity).slice(0, 8))

async function loadAudit({ quiet = false } = {}) {
  if (!quiet) loading.value = true
  try {
    audit.value = (await stonePermsApi.audit({ limit: 200 })).entries || []
  } catch {
    return
  } finally {
    if (!quiet) loading.value = false
  }
}

onMounted(loadAudit)
useLiveRefresh(() => loadAudit({ quiet: true }))
</script>

<template>
  <header class="page-heading">
    <h1>Overview</h1>
  </header>

  <section class="overview-activity-hero" aria-label="Permission activity for the last 24 hours">
    <header class="overview-activity-toolbar">
      <span>Last 24 hours <small>2-hour intervals</small></span>
      <RouterLink class="overview-activity-link" to="/audit">
        Open audit <AppIcon name="arrow" :size="14" />
      </RouterLink>
    </header>
    <div class="overview-activity-layout">
      <dl class="overview-activity-stats" aria-label="Permission activity summary">
        <div class="overview-activity-stat">
          <dt>Operations</dt>
          <dd>{{ activityChart.total }}</dd>
          <small>Recorded permission changes</small>
        </div>
        <div class="overview-activity-stat" :class="activityChart.failures && 'is-negative'">
          <dt>Success rate</dt>
          <dd>{{ activitySuccessRate === null ? '—' : `${activitySuccessRate}%` }}</dd>
          <small v-if="activityChart.failures">
            {{ activityChart.failures }} failed
            {{ activityChart.failures === 1 ? 'operation' : 'operations' }}
          </small>
          <small v-else>No failed operations</small>
        </div>
        <div class="overview-activity-stat">
          <dt>Active intervals</dt>
          <dd>{{ activityChart.activeBuckets }}/{{ activityChart.buckets.length }}</dd>
          <small>{{ activityCoverage }}% of the timeline</small>
          <span
            class="overview-activity-progress"
            role="progressbar"
            aria-label="Active interval coverage"
            aria-valuemin="0"
            aria-valuemax="100"
            :aria-valuenow="activityCoverage"
          >
            <i :style="{ width: `${activityCoverage}%` }"></i>
          </span>
        </div>
      </dl>
      <PermissionActivityChart :activity="activityChart" :aria-label="activityChartLabel" />
    </div>
  </section>

  <section class="panel-grid overview-grid">
    <article v-if="selectedServer" class="panel span-8 permission-hub">
      <header class="panel-header">
        <h3>Selected server</h3>
        <StatusBadge
          :state="selectedServer.status?.ready ? 'online' : 'offline'"
          :label="selectedServer.status?.ready ? 'Ready' : 'Offline'"
        />
      </header>
      <div class="panel-body">
        <div class="permission-hub-heading">
          <div>
            <span class="eyebrow">{{ titleCase(selectedServer.role) }}</span>
            <h2>{{ selectedServer.name }}</h2>
            <p>Open the editor or inspect this server's players, groups, and tracks.</p>
          </div>
          <RouterLink class="button primary" :to="`/servers/${selectedServer.id}/editor`">
            <AppIcon name="editor" />Open editor
          </RouterLink>
        </div>
        <nav class="permission-shortcuts" aria-label="Permission tools">
          <RouterLink :to="`/servers/${selectedServer.id}/players`">
            <AppIcon name="users" />
            <span><strong>Players</strong><small>Inspect effective permissions</small></span>
            <AppIcon name="arrow" :size="15" />
          </RouterLink>
          <RouterLink :to="`/servers/${selectedServer.id}/groups`">
            <AppIcon name="group" />
            <span><strong>Groups</strong><small>Nodes, parents and metadata</small></span>
            <AppIcon name="arrow" :size="15" />
          </RouterLink>
          <RouterLink :to="`/servers/${selectedServer.id}/tracks`">
            <AppIcon name="track" />
            <span><strong>Tracks</strong><small>Promotion and demotion order</small></span>
            <AppIcon name="arrow" :size="15" />
          </RouterLink>
        </nav>
      </div>
    </article>
    <article v-else class="panel span-8">
      <EmptyState
        icon="server"
        title="No server selected"
        description="Select or pair a server to use these tools."
      >
        <RouterLink class="button primary" to="/servers">View servers</RouterLink>
      </EmptyState>
    </article>

    <article class="panel span-4">
      <header class="panel-header">
        <h3>Recent changes</h3>
        <RouterLink to="/audit">View all</RouterLink>
      </header>
      <div class="panel-body">
        <div v-if="permissionActivity.length" class="activity-list">
          <div v-for="entry in permissionActivity" :key="entry.id" class="activity-row">
            <span>
              <AppIcon :name="entry.outcome === 'success' ? 'check' : 'warning'" :size="14" />
            </span>
            <div>
              <strong>{{ auditActionLabel(entry.action) }}</strong>
              <p>{{ entry.actorUsername || 'Server plugin' }}</p>
            </div>
            <time>{{ relativeTime(entry.createdAt) }}</time>
          </div>
        </div>
        <EmptyState
          v-else-if="!loading"
          icon="audit"
          title="No permission changes yet"
          description="Changes made through the editor will appear here."
        />
      </div>
    </article>
  </section>

  <article class="panel permission-server-panel">
    <header class="panel-header">
      <h3>Servers</h3>
      <RouterLink to="/servers">View all</RouterLink>
    </header>
    <div v-if="store.servers.length" class="permission-server-list">
      <div v-for="server in store.servers" :key="server.id" class="permission-server-row">
        <span class="permission-server-icon"><AppIcon name="server" /></span>
        <div>
          <strong>{{ server.name }}</strong>
          <small>{{ titleCase(server.role) }} access</small>
        </div>
        <StatusBadge
          :state="server.status?.ready ? 'online' : 'offline'"
          :label="server.status?.ready ? 'Ready' : 'Offline'"
        />
        <RouterLink class="button small" :to="`/servers/${server.id}/editor`">
          Open <AppIcon name="arrow" :size="14" />
        </RouterLink>
      </div>
    </div>
    <EmptyState
      v-else
      icon="server"
      title="No servers assigned"
      description="Pair a server to get started."
    />
  </article>
</template>
