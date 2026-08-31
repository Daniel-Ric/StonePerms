<script setup>
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import BaseModal from '@/components/BaseModal.vue'
import EmptyState from '@/components/EmptyState.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { stonePermsApi } from '@/services/api'
import { toasts } from '@/services/toasts'
import { useStonePermsStore } from '@/stores/stoneperms'
import { relativeTime, shortId, titleCase } from '@/lib/format'

const store = useStonePermsStore()
const query = ref('')
const pairing = ref(null)
const pairingBusy = ref(false)
const copied = ref(false)
const filtered = computed(() =>
  store.servers.filter((server) =>
    `${server.name} ${server.instanceId}`.toLowerCase().includes(query.value.toLowerCase()),
  ),
)

async function createPairingCode() {
  pairingBusy.value = true
  try {
    pairing.value = await stonePermsApi.createPairingCode()
  } catch (cause) {
    toasts.error(cause.userMessage || cause.message)
  } finally {
    pairingBusy.value = false
  }
}
async function copyCode() {
  await navigator.clipboard.writeText(pairing.value.code)
  copied.value = true
  window.setTimeout(() => {
    copied.value = false
  }, 1600)
}
</script>

<template>
  <header class="page-heading">
    <h1>Servers</h1>
    <div class="page-actions">
      <button
        class="button primary"
        type="button"
        :disabled="pairingBusy"
        @click="createPairingCode"
      >
        <AppIcon name="plus" />{{ pairingBusy ? 'Generating…' : 'Pair a server' }}
      </button>
    </div>
  </header>
  <div class="panel" style="margin-bottom: 14px">
    <div class="panel-body">
      <label class="search-field"
        ><AppIcon name="search" :size="16" /><input
          v-model="query"
          type="search"
          placeholder="Filter by server name or instance ID"
          aria-label="Filter servers"
      /></label>
    </div>
  </div>
  <section v-if="filtered.length" class="server-card-grid">
    <RouterLink
      v-for="server in filtered"
      :key="server.id"
      class="server-card"
      :to="`/servers/${server.id}`"
      ><header>
        <div>
          <h3>{{ server.name }}</h3>
          <div class="server-id">{{ shortId(server.instanceId, 18) }}</div>
        </div>
        <StatusBadge
          :state="server.status?.ready ? 'online' : 'offline'"
          :label="server.status?.ready ? 'Ready' : 'Offline'"
        />
      </header>
      <dl>
        <div>
          <dt>Your role</dt>
          <dd>{{ titleCase(server.role) }}</dd>
        </div>
        <div>
          <dt>Plugin</dt>
          <dd>v{{ server.pluginVersion }}</dd>
        </div>
        <div>
          <dt>Protocol</dt>
          <dd>Revision {{ server.protocolVersion }}</dd>
        </div>
        <div>
          <dt>Last seen</dt>
          <dd>{{ relativeTime(server.lastSeenAt) }}</dd>
        </div>
      </dl>
      <footer>
        <span>{{ server.revokedAt ? 'Credential revoked' : 'Credential active' }}</span
        ><AppIcon name="arrow" :size="16" /></footer
    ></RouterLink>
  </section>
  <EmptyState
    v-else
    icon="server"
    title="No matching servers"
    description="Change the filter or pair a new plugin instance."
    ><button class="button primary" type="button" @click="createPairingCode">
      Create pairing code
    </button></EmptyState
  >
  <BaseModal
    v-if="pairing"
    title="Pair a server"
    description="This one-time code expires shortly and can only claim one plugin instance."
    @close="pairing = null"
  >
    <div class="pairing-code">
      <span>ONE-TIME PAIRING CODE</span><strong>{{ pairing.code }}</strong
      ><small>Expires {{ relativeTime(pairing.expiresAt) }}</small>
    </div>
    <ol class="instruction-list">
      <li>Open the Endstone server console.</li>
      <li>
        Run <code>sp web pair {{ pairing.code }}</code> using the StonePerms command.
      </li>
      <li>Keep the API reachable until this dialog reports the new server.</li>
    </ol>
    <template #footer
      ><button class="button" type="button" @click="pairing = null">Close</button
      ><button class="button primary" type="button" @click="copyCode">
        <AppIcon name="copy" />{{ copied ? 'Copied' : 'Copy code' }}
      </button></template
    >
  </BaseModal>
</template>
