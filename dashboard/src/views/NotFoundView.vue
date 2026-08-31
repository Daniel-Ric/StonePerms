<script setup>
import { RouterLink } from 'vue-router'
import EmptyState from '@/components/EmptyState.vue'
</script>
<template>
  <EmptyState
    icon="warning"
    title="Page not found"
    description="This page does not exist or is no longer available."
    ><RouterLink class="button primary" to="/">Return to overview</RouterLink></EmptyState
  >
</template>
