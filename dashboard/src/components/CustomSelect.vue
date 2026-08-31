<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import AppIcon from './AppIcon.vue'

const props = defineProps({
  modelValue: { type: [String, Number, Boolean, Object], default: '' },
  options: { type: Array, default: () => [] },
  valueKey: { type: String, default: 'value' },
  labelKey: { type: String, default: 'label' },
  placeholder: { type: String, default: 'Choose an option…' },
  searchPlaceholder: { type: String, default: 'Filter options' },
  emptyText: { type: String, default: 'No matching options' },
  ariaLabel: { type: String, default: '' },
  searchable: Boolean,
  editable: Boolean,
  disabled: Boolean,
  compact: Boolean,
  maxMenuHeight: { type: Number, default: 320 },
})

const emit = defineEmits(['update:modelValue', 'change'])
const root = ref(null)
const trigger = ref(null)
const menu = ref(null)
const searchInput = ref(null)
const open = ref(false)
const query = ref('')
const activeIndex = ref(-1)
const menuStyle = ref({})
const listboxId = `stoneperms-select-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`

const normalizedOptions = computed(() =>
  props.options.map((option) => {
    if (option !== null && typeof option === 'object' && !Array.isArray(option)) {
      const value = Object.prototype.hasOwnProperty.call(option, props.valueKey)
        ? option[props.valueKey]
        : option.value
      const label = Object.prototype.hasOwnProperty.call(option, props.labelKey)
        ? option[props.labelKey]
        : option.label
      return {
        value,
        label: String(label ?? value ?? ''),
        description: option.description ? String(option.description) : '',
        status: option.status ? String(option.status) : '',
        disabled: Boolean(option.disabled),
      }
    }
    return {
      value: option,
      label: String(option ?? ''),
      description: '',
      status: '',
      disabled: false,
    }
  }),
)

const selectedOption = computed(
  () => normalizedOptions.value.find((option) => Object.is(option.value, props.modelValue)) || null,
)
const inputValue = computed(() => String(props.modelValue ?? ''))
const visibleOptions = computed(() => {
  const search = (props.editable ? inputValue.value : query.value).trim().toLowerCase()
  if (!search || (!props.searchable && !props.editable)) return normalizedOptions.value
  return normalizedOptions.value.filter((option) =>
    `${option.label} ${option.description} ${String(option.value)}`.toLowerCase().includes(search),
  )
})

function optionId(index) {
  return `${listboxId}-option-${index}`
}

function updatePosition() {
  if (!open.value || !trigger.value) return
  const rect = trigger.value.getBoundingClientRect()
  const edge = 12
  const gap = 6
  const viewportWidth = window.innerWidth
  const viewportHeight = window.innerHeight
  const width = Math.min(Math.max(rect.width, 220), viewportWidth - edge * 2)
  const left = Math.min(Math.max(rect.left, edge), viewportWidth - width - edge)
  const searchHeight = props.searchable && !props.editable ? 51 : 0
  const estimatedHeight = Math.min(
    props.maxMenuHeight,
    Math.max(54, visibleOptions.value.length * 42 + searchHeight + 10),
  )
  const below = viewportHeight - rect.bottom - edge - gap
  const above = rect.top - edge - gap
  const placeAbove = below < Math.min(estimatedHeight, 190) && above > below
  const available = Math.max(110, placeAbove ? above : below)
  const style = {
    left: `${Math.round(left)}px`,
    width: `${Math.round(width)}px`,
    maxHeight: `${Math.round(Math.min(props.maxMenuHeight, available))}px`,
  }
  if (placeAbove) style.bottom = `${Math.round(viewportHeight - rect.top + gap)}px`
  else style.top = `${Math.round(rect.bottom + gap)}px`
  menuStyle.value = style
}

function firstEnabledIndex() {
  return visibleOptions.value.findIndex((option) => !option.disabled)
}

function openMenu() {
  if (props.disabled || open.value) return
  open.value = true
  query.value = ''
  const selectedIndex = visibleOptions.value.findIndex((option) =>
    Object.is(option.value, props.modelValue),
  )
  activeIndex.value = selectedIndex >= 0 ? selectedIndex : props.editable ? -1 : firstEnabledIndex()
  nextTick(() => {
    updatePosition()
    if (props.searchable && !props.editable) searchInput.value?.focus()
  })
}

function closeMenu({ restoreFocus = false } = {}) {
  if (!open.value) return
  open.value = false
  query.value = ''
  activeIndex.value = -1
  if (restoreFocus) nextTick(() => trigger.value?.focus())
}

function toggleMenu() {
  if (open.value) closeMenu()
  else openMenu()
}

function selectOption(option) {
  if (!option || option.disabled) return
  emit('update:modelValue', option.value)
  emit('change', option.value)
  closeMenu({ restoreFocus: !props.editable })
}

function moveActive(offset) {
  if (!open.value) openMenu()
  const options = visibleOptions.value
  if (!options.length) return
  let next = activeIndex.value
  for (let count = 0; count < options.length; count += 1) {
    next = (next + offset + options.length) % options.length
    if (!options[next].disabled) {
      activeIndex.value = next
      nextTick(() => document.getElementById(optionId(next))?.scrollIntoView({ block: 'nearest' }))
      return
    }
  }
}

function handleKeydown(event) {
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    moveActive(1)
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    moveActive(-1)
  } else if (event.key === 'Enter') {
    if (!open.value) {
      event.preventDefault()
      openMenu()
    } else if (activeIndex.value >= 0) {
      event.preventDefault()
      selectOption(visibleOptions.value[activeIndex.value])
    } else if (props.editable) {
      closeMenu()
    }
  } else if (event.key === 'Escape') {
    event.preventDefault()
    event.stopPropagation()
    closeMenu({ restoreFocus: !props.editable })
  } else if (event.key === 'Tab') {
    closeMenu()
  } else if (event.key === ' ' && !props.editable && !props.searchable) {
    event.preventDefault()
    toggleMenu()
  }
}

function handleEditableInput(event) {
  emit('update:modelValue', event.target.value)
  activeIndex.value = -1
  if (!open.value) openMenu()
  nextTick(updatePosition)
}

function handleSearchInput(event) {
  query.value = event.target.value
  activeIndex.value = firstEnabledIndex()
  nextTick(updatePosition)
}

function handleDocumentPointer(event) {
  const path = event.composedPath()
  if (root.value && path.includes(root.value)) return
  if (menu.value && path.includes(menu.value)) return
  closeMenu()
}

function handleViewportChange() {
  if (open.value) updatePosition()
}

watch(
  () => visibleOptions.value.length,
  () => {
    if (!open.value) return
    if (activeIndex.value >= visibleOptions.value.length) activeIndex.value = firstEnabledIndex()
    nextTick(updatePosition)
  },
)
watch(
  () => props.disabled,
  (disabled) => {
    if (disabled) closeMenu()
  },
)

onMounted(() => {
  document.addEventListener('pointerdown', handleDocumentPointer)
  window.addEventListener('resize', handleViewportChange)
  window.addEventListener('scroll', handleViewportChange, true)
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', handleDocumentPointer)
  window.removeEventListener('resize', handleViewportChange)
  window.removeEventListener('scroll', handleViewportChange, true)
})
</script>

<template>
  <div
    ref="root"
    :class="[
      'custom-select',
      compact && 'is-compact',
      editable && 'is-editable',
      open && 'is-open',
      disabled && 'is-disabled',
    ]"
  >
    <div v-if="editable" class="custom-select__control">
      <input
        ref="trigger"
        class="custom-select__input"
        type="text"
        role="combobox"
        autocomplete="off"
        :value="inputValue"
        :placeholder="placeholder"
        :disabled="disabled"
        :aria-label="ariaLabel || placeholder"
        :aria-controls="listboxId"
        :aria-expanded="open"
        :aria-activedescendant="activeIndex >= 0 ? optionId(activeIndex) : undefined"
        @focus="openMenu"
        @click="openMenu"
        @input="handleEditableInput"
        @keydown="handleKeydown"
      />
      <button
        class="custom-select__toggle"
        type="button"
        tabindex="-1"
        :disabled="disabled"
        :aria-label="open ? 'Close suggestions' : 'Open suggestions'"
        @mousedown.prevent
        @click="toggleMenu"
      >
        <AppIcon name="chevron" :size="14" />
      </button>
    </div>
    <button
      v-else
      ref="trigger"
      class="custom-select__trigger"
      type="button"
      role="combobox"
      :disabled="disabled"
      :aria-label="ariaLabel || placeholder"
      :aria-controls="listboxId"
      :aria-expanded="open"
      :aria-activedescendant="activeIndex >= 0 ? optionId(activeIndex) : undefined"
      @click="toggleMenu"
      @keydown="handleKeydown"
    >
      <span :class="['custom-select__selected', !selectedOption && 'is-placeholder']">
        <span
          v-if="selectedOption?.status"
          :class="['custom-select__status', `is-${selectedOption.status}`]"
          aria-hidden="true"
        ></span>
        <span>{{ selectedOption?.label || placeholder }}</span>
      </span>
      <AppIcon class="custom-select__chevron" name="chevron" :size="14" />
    </button>

    <Teleport to="body">
      <div
        v-if="open"
        ref="menu"
        class="custom-select-menu"
        :style="menuStyle"
        @keydown="handleKeydown"
      >
        <label v-if="searchable && !editable" class="custom-select-menu__search">
          <AppIcon name="search" :size="14" />
          <input
            ref="searchInput"
            type="search"
            :value="query"
            :placeholder="searchPlaceholder"
            aria-label="Filter options"
            @input="handleSearchInput"
          />
        </label>
        <div :id="listboxId" class="custom-select-menu__options" role="listbox">
          <button
            v-for="(option, index) in visibleOptions"
            :id="optionId(index)"
            :key="`${String(option.value)}:${index}`"
            class="custom-select-menu__option"
            type="button"
            role="option"
            :class="[activeIndex === index && 'is-active', option.status && 'has-status']"
            :disabled="option.disabled"
            :aria-selected="Object.is(option.value, modelValue)"
            @pointermove="activeIndex = index"
            @mousedown.prevent
            @click="selectOption(option)"
          >
            <span
              v-if="option.status"
              :class="['custom-select__status', `is-${option.status}`]"
              aria-hidden="true"
            ></span>
            <span class="custom-select-menu__copy">
              <strong>{{ option.label }}</strong>
              <small v-if="option.description">{{ option.description }}</small>
            </span>
            <AppIcon
              v-if="Object.is(option.value, modelValue)"
              class="custom-select-menu__check"
              name="check"
              :size="14"
            />
          </button>
          <p v-if="!visibleOptions.length" class="custom-select-menu__empty">{{ emptyText }}</p>
        </div>
      </div>
    </Teleport>
  </div>
</template>
