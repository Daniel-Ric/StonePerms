<script setup>
import { computed, ref, watch } from 'vue'
import { stonePermsApi } from '@/services/api'

const props = defineProps({
  serverId: { type: String, required: true },
  player: { type: Object, required: true },
  size: { type: Number, default: 72 },
})
const failed = ref(false)
const hasAvatarCandidate = computed(
  () => Boolean(props.player?.skinHash) || /^\d{1,20}$/.test(String(props.player?.xuid ?? '')),
)
const source = computed(() =>
  hasAvatarCandidate.value ? stonePermsApi.playerAvatarUrl(props.serverId, props.player) : null,
)
const initial = computed(() =>
  String(props.player?.name || '?')
    .slice(0, 1)
    .toUpperCase(),
)
watch(source, () => {
  failed.value = false
})
</script>

<template>
  <span class="player-avatar" :style="{ '--avatar-size': `${size}px` }">
    <img
      v-if="source && !failed"
      :src="source"
      :alt="`${player.name || 'Player'} skin face`"
      loading="lazy"
      decoding="async"
      @error="failed = true"
    />
    <strong v-else aria-hidden="true">{{ initial }}</strong>
  </span>
</template>
