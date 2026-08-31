<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import {
  AriaComponent,
  AxisPointerComponent,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  MarkPointComponent,
  TooltipComponent,
} from 'echarts/components'
import { SVGRenderer } from 'echarts/renderers'
import { usePreferences } from '@/composables/usePreferences'
import { buildPermissionActivityOption } from '@/lib/activityChart'

echarts.use([
  LineChart,
  AriaComponent,
  AxisPointerComponent,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  MarkPointComponent,
  TooltipComponent,
  SVGRenderer,
])

const props = defineProps({
  activity: { type: Object, required: true },
  ariaLabel: { type: String, default: '' },
})
const { effectiveReducedMotion, resolvedTheme } = usePreferences()

const root = ref(null)
let chart = null
let resizeObserver = null

function renderChart() {
  if (!chart) return
  chart.setOption(
    buildPermissionActivityOption(props.activity, {
      reducedMotion: effectiveReducedMotion.value,
      theme: resolvedTheme.value,
      description: props.ariaLabel,
    }),
    { notMerge: true, lazyUpdate: true },
  )
}

function resizeChart() {
  chart?.resize({ animation: { duration: 160 } })
}

watch(
  [() => props.activity, () => props.ariaLabel, resolvedTheme, effectiveReducedMotion],
  renderChart,
  { deep: true },
)

onMounted(async () => {
  await nextTick()
  chart = echarts.init(root.value, null, { renderer: 'svg' })
  renderChart()
  resizeObserver = new ResizeObserver(resizeChart)
  resizeObserver.observe(root.value)
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div ref="root" class="permission-activity-chart" role="img" :aria-label="ariaLabel"></div>
</template>
