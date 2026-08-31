<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import AppIcon from './AppIcon.vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  placeholder: { type: String, default: 'No expiry' },
  ariaLabel: { type: String, default: 'Choose date and time' },
  locale: { type: String, default: 'en-GB' },
  disabled: Boolean,
})

const emit = defineEmits(['update:modelValue', 'change'])
const root = ref(null)
const trigger = ref(null)
const menu = ref(null)
const open = ref(false)
const draft = ref(new Date())
const viewDate = ref(new Date())
const menuStyle = ref({})
const pickerId = `stoneperms-date-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`

const pad = (value) => String(value).padStart(2, '0')
const sameDay = (left, right) =>
  left.getFullYear() === right.getFullYear() &&
  left.getMonth() === right.getMonth() &&
  left.getDate() === right.getDate()

function parseLocalDateTime(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(String(value || ''))
  if (!match) return null
  const [, year, month, day, hour, minute] = match.map(Number)
  const date = new Date(year, month - 1, day, hour, minute, 0, 0)
  if (
    date.getFullYear() !== year ||
    date.getMonth() !== month - 1 ||
    date.getDate() !== day ||
    date.getHours() !== hour ||
    date.getMinutes() !== minute
  )
    return null
  return date
}

function toLocalDateTime(date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`
}

function cleanNow() {
  const date = new Date()
  date.setSeconds(0, 0)
  return date
}

const selectedDate = computed(() => parseLocalDateTime(props.modelValue))
const displayValue = computed(() =>
  selectedDate.value
    ? new Intl.DateTimeFormat(props.locale, {
        day: '2-digit',
        month: 'short',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      }).format(selectedDate.value)
    : props.placeholder,
)
const monthLabel = computed(() =>
  new Intl.DateTimeFormat(props.locale, { month: 'long', year: 'numeric' }).format(viewDate.value),
)
const draftSummary = computed(() =>
  new Intl.DateTimeFormat(props.locale, {
    weekday: 'short',
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  }).format(draft.value),
)
const weekdayLabels = computed(() => {
  const monday = new Date(2024, 0, 1)
  return Array.from({ length: 7 }, (_, index) => {
    const date = new Date(monday)
    date.setDate(monday.getDate() + index)
    return new Intl.DateTimeFormat(props.locale, { weekday: 'short' }).format(date)
  })
})
const calendarDays = computed(() => {
  const year = viewDate.value.getFullYear()
  const month = viewDate.value.getMonth()
  const first = new Date(year, month, 1)
  const mondayOffset = (first.getDay() + 6) % 7
  return Array.from({ length: 42 }, (_, index) => {
    const date = new Date(year, month, 1 - mondayOffset + index)
    return { date, currentMonth: date.getMonth() === month }
  })
})

function dayId(date) {
  return `${pickerId}-${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`
}

function dayLabel(date) {
  return new Intl.DateTimeFormat(props.locale, {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  }).format(date)
}

function updatePosition() {
  if (!open.value || !trigger.value) return
  const rect = trigger.value.getBoundingClientRect()
  const edge = 12
  const gap = 6
  const viewportWidth = window.innerWidth
  const viewportHeight = window.innerHeight
  const width = Math.min(370, viewportWidth - edge * 2)
  const left = Math.min(Math.max(rect.left, edge), viewportWidth - width - edge)
  const estimatedHeight = 474
  const below = viewportHeight - rect.bottom - edge - gap
  const above = rect.top - edge - gap
  const placeAbove = below < estimatedHeight && above > below
  const available = Math.max(120, Math.min(estimatedHeight, placeAbove ? above : below))
  const style = {
    left: `${Math.round(left)}px`,
    width: `${Math.round(width)}px`,
    maxHeight: `${Math.round(available)}px`,
  }
  if (placeAbove) style.bottom = `${Math.round(viewportHeight - rect.top + gap)}px`
  else style.top = `${Math.round(rect.bottom + gap)}px`
  menuStyle.value = style
}

function openPicker() {
  if (props.disabled || open.value) return
  const initial = selectedDate.value || cleanNow()
  draft.value = new Date(initial)
  viewDate.value = new Date(initial.getFullYear(), initial.getMonth(), 1)
  open.value = true
  nextTick(updatePosition)
}

function closePicker({ restoreFocus = false } = {}) {
  if (!open.value) return
  open.value = false
  if (restoreFocus) nextTick(() => trigger.value?.focus())
}

function togglePicker() {
  if (open.value) closePicker()
  else openPicker()
}

function moveView(monthOffset) {
  viewDate.value = new Date(
    viewDate.value.getFullYear(),
    viewDate.value.getMonth() + monthOffset,
    1,
  )
  nextTick(updatePosition)
}

function selectDay(date) {
  draft.value = new Date(
    date.getFullYear(),
    date.getMonth(),
    date.getDate(),
    draft.value.getHours(),
    draft.value.getMinutes(),
    0,
    0,
  )
  viewDate.value = new Date(date.getFullYear(), date.getMonth(), 1)
}

function focusDraftDay() {
  nextTick(() => document.getElementById(dayId(draft.value))?.focus())
}

function moveDraftDay(offset) {
  const next = new Date(draft.value)
  next.setDate(next.getDate() + offset)
  selectDay(next)
  focusDraftDay()
}

function handleDayKeydown(event) {
  const dayOffsets = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }
  if (Object.prototype.hasOwnProperty.call(dayOffsets, event.key)) {
    event.preventDefault()
    moveDraftDay(dayOffsets[event.key])
  } else if (event.key === 'Home' || event.key === 'End') {
    event.preventDefault()
    const weekday = (draft.value.getDay() + 6) % 7
    moveDraftDay(event.key === 'Home' ? -weekday : 6 - weekday)
  } else if (event.key === 'PageUp' || event.key === 'PageDown') {
    event.preventDefault()
    const next = new Date(draft.value)
    next.setMonth(next.getMonth() + (event.key === 'PageUp' ? -1 : 1))
    selectDay(next)
    focusDraftDay()
  }
}

function setTimePart(part, rawValue) {
  const maximum = part === 'hour' ? 23 : 59
  const value = Math.min(maximum, Math.max(0, Number.parseInt(rawValue, 10) || 0))
  const next = new Date(draft.value)
  if (part === 'hour') next.setHours(value)
  else next.setMinutes(value)
  draft.value = next
}

function adjustTime(part, offset) {
  const maximum = part === 'hour' ? 24 : 60
  const current = part === 'hour' ? draft.value.getHours() : draft.value.getMinutes()
  setTimePart(part, (current + offset + maximum) % maximum)
}

function useNow() {
  const now = cleanNow()
  draft.value = now
  viewDate.value = new Date(now.getFullYear(), now.getMonth(), 1)
}

function applyValue() {
  const value = toLocalDateTime(draft.value)
  emit('update:modelValue', value)
  emit('change', value)
  closePicker({ restoreFocus: true })
}

function clearValue() {
  emit('update:modelValue', '')
  emit('change', '')
  closePicker({ restoreFocus: true })
}

function handleTriggerKeydown(event) {
  if (['Enter', ' ', 'ArrowDown'].includes(event.key)) {
    event.preventDefault()
    openPicker()
  } else if (event.key === 'Escape' && open.value) {
    event.preventDefault()
    event.stopPropagation()
    closePicker()
  }
}

function handleMenuKeydown(event) {
  if (event.key === 'Escape') {
    event.preventDefault()
    event.stopPropagation()
    closePicker({ restoreFocus: true })
  }
}

function handleDocumentPointer(event) {
  const path = event.composedPath()
  if (root.value && path.includes(root.value)) return
  if (menu.value && path.includes(menu.value)) return
  closePicker()
}

function handleViewportChange() {
  if (open.value) updatePosition()
}

watch(
  () => props.disabled,
  (disabled) => {
    if (disabled) closePicker()
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
  <div ref="root" :class="['custom-datetime', open && 'is-open', disabled && 'is-disabled']">
    <button
      ref="trigger"
      class="custom-datetime__trigger"
      type="button"
      :disabled="disabled"
      :aria-label="ariaLabel"
      :aria-controls="pickerId"
      :aria-expanded="open"
      aria-haspopup="dialog"
      @click="togglePicker"
      @keydown="handleTriggerKeydown"
    >
      <AppIcon name="calendar" :size="16" />
      <span :class="!selectedDate && 'is-placeholder'">{{ displayValue }}</span>
      <AppIcon class="custom-datetime__chevron" name="chevron" :size="14" />
    </button>

    <Teleport to="body">
      <section
        v-if="open"
        :id="pickerId"
        ref="menu"
        class="custom-datetime-menu"
        :style="menuStyle"
        role="dialog"
        aria-label="Choose expiry date and time"
        @keydown="handleMenuKeydown"
      >
        <header class="custom-datetime-menu__header">
          <div>
            <span class="eyebrow">EXPIRY</span>
            <strong>{{ monthLabel }}</strong>
          </div>
          <div>
            <button type="button" aria-label="Previous month" @click="moveView(-1)">‹</button>
            <button type="button" aria-label="Next month" @click="moveView(1)">›</button>
          </div>
        </header>

        <div class="custom-datetime-calendar" role="grid" :aria-label="monthLabel">
          <span v-for="weekday in weekdayLabels" :key="weekday" role="columnheader">{{
            weekday
          }}</span>
          <button
            v-for="day in calendarDays"
            :id="dayId(day.date)"
            :key="day.date.toISOString()"
            type="button"
            role="gridcell"
            :class="[
              !day.currentMonth && 'is-outside',
              sameDay(day.date, draft) && 'is-selected',
              sameDay(day.date, new Date()) && 'is-today',
            ]"
            :aria-label="dayLabel(day.date)"
            :aria-selected="sameDay(day.date, draft)"
            :aria-current="sameDay(day.date, new Date()) ? 'date' : undefined"
            :tabindex="sameDay(day.date, draft) ? 0 : -1"
            @click="selectDay(day.date)"
            @keydown="handleDayKeydown"
          >
            {{ day.date.getDate() }}
          </button>
        </div>

        <div class="custom-datetime-time">
          <div>
            <span class="eyebrow">DATE &amp; TIME</span>
            <strong>{{ draftSummary }}</strong>
          </div>
          <div class="custom-datetime-time__fields">
            <div class="custom-datetime-stepper">
              <button type="button" aria-label="Decrease hour" @click="adjustTime('hour', -1)">
                −
              </button>
              <label>
                <span>Hour</span>
                <input
                  type="text"
                  inputmode="numeric"
                  maxlength="2"
                  :value="pad(draft.getHours())"
                  aria-label="Hour"
                  @change="setTimePart('hour', $event.target.value)"
                />
              </label>
              <button type="button" aria-label="Increase hour" @click="adjustTime('hour', 1)">
                +
              </button>
            </div>
            <span aria-hidden="true">:</span>
            <div class="custom-datetime-stepper">
              <button type="button" aria-label="Decrease minute" @click="adjustTime('minute', -1)">
                −
              </button>
              <label>
                <span>Minute</span>
                <input
                  type="text"
                  inputmode="numeric"
                  maxlength="2"
                  :value="pad(draft.getMinutes())"
                  aria-label="Minute"
                  @change="setTimePart('minute', $event.target.value)"
                />
              </label>
              <button type="button" aria-label="Increase minute" @click="adjustTime('minute', 1)">
                +
              </button>
            </div>
          </div>
        </div>

        <footer class="custom-datetime-menu__footer">
          <button class="button ghost small" type="button" @click="clearValue">Clear</button>
          <button class="button small" type="button" @click="useNow">Now</button>
          <button class="button primary small" type="button" @click="applyValue">Apply</button>
        </footer>
      </section>
    </Teleport>
  </div>
</template>
