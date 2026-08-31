<script setup>
import { computed } from 'vue'

const props = defineProps({
  name: { type: String, default: '' },
  seed: { type: [String, Number], default: '' },
  size: { type: Number, default: 30 },
})

const initials = computed(() => {
  const parts = String(props.name || '')
    .trim()
    .split(/[\s._-]+/)
    .filter(Boolean)
  if (!parts.length) return '?'
  if (parts.length === 1) return parts[0].slice(0, 1).toUpperCase()
  return `${parts[0][0]}${parts.at(-1)[0]}`.toUpperCase()
})

const variant = computed(() => {
  const value = String(props.seed || props.name || 'stoneperms')
  let hash = 0
  for (const character of value) hash = (hash * 31 + character.codePointAt(0)) >>> 0
  return `is-variant-${hash % 6}`
})
</script>

<template>
  <span
    :class="['operator-avatar', variant]"
    :style="{ '--operator-avatar-size': `${size}px` }"
    role="img"
    :aria-label="`${name || 'User'} avatar`"
  >
    <span class="operator-avatar__facet" aria-hidden="true"></span>
    <strong aria-hidden="true">{{ initials }}</strong>
  </span>
</template>
