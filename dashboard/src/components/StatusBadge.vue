<script setup>
defineProps({ state: { type: String, required: true }, label: { type: String, default: '' } })
</script>
<template>
  <span :class="['status-badge', `is-${state}`]"><span></span>{{ label || state }}</span>
</template>
