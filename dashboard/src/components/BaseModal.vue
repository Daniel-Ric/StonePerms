<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, useId } from 'vue'
import AppIcon from './AppIcon.vue'

defineProps({
  title: { type: String, required: true },
  description: { type: String, default: '' },
  wide: Boolean,
})
const emit = defineEmits(['close'])
const panel = ref(null)
const id = useId().replace(/[^a-zA-Z0-9_-]/g, '')
const titleId = `stoneperms-modal-title-${id}`
const descriptionId = `stoneperms-modal-description-${id}`
let previousFocus = null

function onKey(event) {
  if (event.key === 'Escape') emit('close')
}

onMounted(() => {
  previousFocus = document.activeElement
  document.body.classList.add('modal-open')
  window.addEventListener('keydown', onKey)
  nextTick(() => panel.value?.focus({ preventScroll: true }))
})

onBeforeUnmount(() => {
  document.body.classList.remove('modal-open')
  window.removeEventListener('keydown', onKey)
  if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus()
})
</script>

<template>
  <Teleport to="body">
    <Transition name="modal" appear>
      <div class="modal-backdrop" role="presentation" @mousedown.self="$emit('close')">
        <section
          ref="panel"
          :class="['modal-panel', wide && 'is-wide']"
          role="dialog"
          aria-modal="true"
          :aria-labelledby="titleId"
          :aria-describedby="description ? descriptionId : undefined"
          tabindex="-1"
        >
          <header>
            <div>
              <h2 :id="titleId">{{ title }}</h2>
              <p v-if="description" :id="descriptionId">{{ description }}</p>
            </div>
            <button
              class="icon-button"
              type="button"
              aria-label="Close dialog"
              @click="$emit('close')"
            >
              <AppIcon name="close" />
            </button>
          </header>
          <div class="modal-body"><slot /></div>
          <footer v-if="$slots.footer"><slot name="footer" /></footer>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>
