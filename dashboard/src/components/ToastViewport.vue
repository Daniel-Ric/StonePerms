<script setup>
import AppIcon from './AppIcon.vue'
import { toasts } from '@/services/toasts'
const icons = { success: 'check', error: 'warning', warning: 'warning', info: 'shield' }
</script>

<template>
  <div class="toast-viewport" role="region" aria-label="Notifications">
    <TransitionGroup name="toast-list">
      <article
        v-for="toast in toasts.state.items"
        :key="toast.id"
        :class="['toast-card', `is-${toast.type}`]"
        role="status"
      >
        <span class="toast-icon"><AppIcon :name="icons[toast.type]" /></span>
        <div>
          <strong>{{ toast.title }}</strong>
          <p>{{ toast.message }}</p>
        </div>
        <button type="button" aria-label="Dismiss notification" @click="toasts.dismiss(toast.id)">
          ×
        </button>
      </article>
    </TransitionGroup>
  </div>
</template>
