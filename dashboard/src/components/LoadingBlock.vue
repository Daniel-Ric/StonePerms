<script setup>
defineProps({ rows: { type: Number, default: 3 } })
</script>
<template>
  <div class="loading-block" aria-label="Loading">
    <span v-for="index in rows" :key="index"></span>
  </div>
</template>
