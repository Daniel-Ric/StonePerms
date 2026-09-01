<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import BaseModal from '@/components/BaseModal.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { useLiveRefresh } from '@/composables/useLiveRefresh'
import { stonePermsApi } from '@/services/api'
import { toasts } from '@/services/toasts'
import { useStonePermsStore } from '@/stores/stoneperms'
import { formatDate, relativeTime, titleCase } from '@/lib/format'

const route = useRoute()
const router = useRouter()
const store = useStonePermsStore()
const detail = ref(null)
const loading = ref(true)
const confirming = ref('')
const revoking = ref(false)
const deleting = ref(false)
const id = computed(() => String(route.params.serverId))
async function load({ quiet = false } = {}) {
  if (!quiet) loading.value = true
  try {
    detail.value = await stonePermsApi.server(id.value)
  } catch (cause) {
    if (!quiet) toasts.error(cause.userMessage || cause.message)
  } finally {
    if (!quiet) loading.value = false
  }
}
async function revoke() {
  revoking.value = true
  try {
    await stonePermsApi.revokeServer(id.value)
    toasts.success('The server credential was revoked.')
    await store.refresh()
    await router.push('/servers')
  } catch (cause) {
    toasts.error(cause.userMessage || cause.message)
  } finally {
    revoking.value = false
  }
}
async function deleteServer() {
  deleting.value = true
  try {
    await stonePermsApi.deleteServer(id.value)
    toasts.success('The server was deleted from the dashboard.')
    await store.refresh()
    await router.push('/servers')
  } catch (cause) {
    toasts.error(cause.userMessage || cause.message)
  } finally {
    deleting.value = false
  }
}
onMounted(load)
watch(id, () => void load())
useLiveRefresh(() => load({ quiet: true }))
</script>

<template>
  <LoadingBlock v-if="loading" :rows="5" />
  <template v-else-if="detail?.server"
    ><header class="page-heading">
      <h1>{{ detail.server.name }}</h1>
      <div class="page-actions">
        <RouterLink class="button primary" :to="`/servers/${id}/editor`"
          ><AppIcon name="editor" />Open editor</RouterLink
        >
      </div>
    </header>
    <section class="metric-grid">
      <article class="metric-card" :class="detail.server.status?.ready ? 'is-green' : 'is-red'">
        <span class="metric-label">Plugin state</span
        ><strong>{{ detail.server.status?.ready ? 'READY' : 'OFFLINE' }}</strong
        ><small>{{ relativeTime(detail.server.lastSeenAt) }}</small>
      </article>
      <article class="metric-card">
        <span class="metric-label">Your role</span
        ><strong style="font-size: 22px">{{ titleCase(detail.server.role) }}</strong
        ><small>{{
          store.canEdit(detail.server) ? 'Changes are permitted' : 'Read-only access'
        }}</small>
      </article>
      <article class="metric-card is-blue">
        <span class="metric-label">Web operators</span
        ><strong>{{ detail.memberships.length }}</strong
        ><small>Assigned to this server</small>
      </article>
      <article class="metric-card">
        <span class="metric-label">Plugin version</span
        ><strong style="font-size: 22px">{{ detail.server.pluginVersion }}</strong
        ><small>Protocol revision {{ detail.server.protocolVersion }}</small>
      </article>
    </section>
    <section class="panel-grid">
      <article class="panel span-7">
        <header class="panel-header">
          <h3>Instance information</h3>
          <StatusBadge
            :state="detail.server.status?.ready ? 'online' : 'offline'"
            :label="detail.server.status?.ready ? 'WebSocket ready' : 'No live connection'"
          />
        </header>
        <div class="panel-body detail-list">
          <div>
            <span>Server ID</span><code>{{ detail.server.id }}</code>
          </div>
          <div>
            <span>Instance ID</span><code>{{ detail.server.instanceId }}</code>
          </div>
          <div>
            <span>Paired</span><strong>{{ formatDate(detail.server.createdAt) }}</strong>
          </div>
          <div>
            <span>Connected since</span
            ><strong>{{ formatDate(detail.server.status?.connectedAt) }}</strong>
          </div>
        </div>
      </article>
      <article class="panel span-5">
        <header class="panel-header">
          <h3>Server tools</h3>
        </header>
        <div class="panel-body quick-links">
          <RouterLink :to="`/servers/${id}/groups`"
            ><AppIcon name="group" /><span
              ><strong>Groups</strong><small>Inheritance, weights and nodes</small></span
            ><AppIcon name="arrow" /></RouterLink
          ><RouterLink :to="`/servers/${id}/tracks`"
            ><AppIcon name="track" /><span
              ><strong>Tracks</strong><small>Promotion ladders and order</small></span
            ><AppIcon name="arrow" /></RouterLink
          ><RouterLink :to="`/servers/${id}/display`"
            ><AppIcon name="display" /><span
              ><strong>Chat and nametags</strong><small>Prefix and suffix display</small></span
            ><AppIcon name="arrow" /></RouterLink
          ><RouterLink :to="`/servers/${id}/audit`"
            ><AppIcon name="audit" /><span
              ><strong>Audit</strong><small>Permission and settings changes</small></span
            ><AppIcon name="arrow"
          /></RouterLink>
        </div>
      </article>
    </section>
    <article v-if="store.canOwn(detail.server)" class="panel danger-zone">
      <header class="panel-header">
        <div>
          <h3>Server access</h3>
          <small>Revoke only the credential or remove the complete dashboard assignment.</small>
        </div>
        <div class="page-actions">
          <button class="button" type="button" @click="confirming = 'revoke'">
            <AppIcon name="lock" />Revoke connection
          </button>
          <button class="button danger" type="button" @click="confirming = 'delete'">
            <AppIcon name="trash" />Delete server
          </button>
        </div>
      </header>
    </article>
    <BaseModal
      v-if="confirming === 'revoke'"
      title="Revoke server connection?"
      :description="`The credential for ${detail.server.name} will stop working immediately.`"
      @close="confirming = ''"
      ><p class="modal-warning">
        <AppIcon name="warning" />This does not delete the permission database on the Minecraft
        server. It only removes dashboard access until the plugin is paired again.
      </p>
      <template #footer
        ><button class="button" type="button" @click="confirming = ''">Cancel</button
        ><button class="button danger" type="button" :disabled="revoking" @click="revoke">
          {{ revoking ? 'Revoking…' : 'Revoke credential' }}
        </button></template
      ></BaseModal
    >
    <BaseModal
      v-if="confirming === 'delete'"
      title="Delete server from dashboard?"
      :description="`${detail.server.name} and all team access will be removed from this dashboard.`"
      @close="confirming = ''"
      ><p class="modal-warning">
        <AppIcon name="warning" />The Minecraft server's local permission database is not deleted.
        Its current web credential stops working and the instance can be paired again as a new
        server.
      </p>
      <template #footer
        ><button class="button" type="button" @click="confirming = ''">Cancel</button
        ><button class="button danger" type="button" :disabled="deleting" @click="deleteServer">
          {{ deleting ? 'Deleting…' : 'Delete server' }}
        </button></template
      ></BaseModal
    >
  </template>
</template>
