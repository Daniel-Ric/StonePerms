<script setup>
import AppIcon from './AppIcon.vue'
defineProps({
  icon: { type: String, default: 'shield' },
  title: { type: String, required: true },
  description: { type: String, required: true },
})
</script>
<template>
  <div class="empty-state">
    <span><AppIcon :name="icon" :size="24" /></span>
    <h3>{{ title }}</h3>
    <p>{{ description }}</p>
    <slot />
  </div>
</template>
