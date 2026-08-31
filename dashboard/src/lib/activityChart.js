const DARK_COLORS = {
  accent: '#d7d391',
  accentStrong: '#fdfbcf',
  accentDeep: '#8b8855',
  accentInk: '#141e25',
  muted: '#73818a',
  grid: 'rgba(77, 91, 100, 0.25)',
  red: '#d06c62',
  redStrong: '#e8948c',
  panel: '#11181d',
  line: '#344149',
  text: '#eef0e8',
  areaStart: 'rgba(215, 211, 145, 0.30)',
  areaMid: 'rgba(139, 136, 85, 0.08)',
  areaEnd: 'rgba(139, 136, 85, 0)',
  lineShadow: '#d7d39130',
}

const LIGHT_COLORS = {
  accent: '#8b8750',
  accentStrong: '#69652f',
  accentDeep: '#aaa66d',
  accentInk: '#fffef7',
  muted: '#697577',
  grid: 'rgba(74, 86, 88, 0.17)',
  red: '#b64f47',
  redStrong: '#ca6c63',
  panel: '#fffef7',
  line: '#c9c8bb',
  text: '#182126',
  areaStart: 'rgba(139, 135, 80, 0.25)',
  areaMid: 'rgba(170, 166, 109, 0.08)',
  areaEnd: 'rgba(170, 166, 109, 0)',
  lineShadow: '#8b875035',
}

export function movingAverage(values, size = 3) {
  return values.map((_, index) => {
    const start = Math.max(0, index - size + 1)
    const window = values.slice(start, index + 1)
    return Number((window.reduce((sum, value) => sum + value, 0) / window.length).toFixed(2))
  })
}

export function buildPermissionActivityOption(activity, options = {}) {
  const COLORS = options.theme === 'light' ? LIGHT_COLORS : DARK_COLORS
  const buckets = activity?.buckets || []
  const labels = buckets.map((bucket) => bucket.label)
  const successful = buckets.map((bucket) => bucket.success)
  const failed = buckets.map((bucket) => bucket.failed)
  const total = buckets.map((bucket) => bucket.total)
  const trend = movingAverage(total)
  const valueFormatter = (value) => `${value} operation${Number(value) === 1 ? '' : 's'}`

  return {
    animation: !options.reducedMotion,
    animationDuration: 620,
    animationEasing: 'cubicOut',
    color: [COLORS.accent, COLORS.accentStrong, COLORS.red, COLORS.muted],
    aria: {
      enabled: true,
      decal: { show: false },
      description: options.description || 'Permission activity for the last 24 hours.',
    },
    tooltip: {
      trigger: 'axis',
      order: 'valueDesc',
      backgroundColor: COLORS.panel,
      borderColor: COLORS.line,
      borderWidth: 1,
      padding: [9, 11],
      textStyle: { color: COLORS.text, fontSize: 11 },
      axisPointer: {
        type: 'cross',
        lineStyle: { color: COLORS.accentDeep, width: 1, type: 'dashed' },
        crossStyle: { color: COLORS.accentDeep, width: 1, type: 'dashed' },
        label: { color: COLORS.accentInk, backgroundColor: COLORS.accent },
      },
    },
    legend: {
      top: 3,
      right: 8,
      itemWidth: 16,
      itemHeight: 7,
      itemGap: 15,
      icon: 'roundRect',
      textStyle: { color: COLORS.muted, fontSize: 9 },
      data: ['Successful', 'Failed', 'Activity trend'],
    },
    grid: { top: 42, right: 18, bottom: 30, left: 14, containLabel: true },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: labels,
      axisLine: { lineStyle: { color: COLORS.line } },
      axisTick: { show: false },
      axisLabel: {
        color: COLORS.muted,
        fontFamily: 'IBM Plex Mono, monospace',
        fontSize: 8,
        interval: 1,
        hideOverlap: true,
      },
    },
    yAxis: {
      type: 'value',
      min: 0,
      minInterval: 1,
      splitNumber: 3,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        color: COLORS.muted,
        fontFamily: 'IBM Plex Mono, monospace',
        fontSize: 8,
      },
      splitLine: { lineStyle: { color: COLORS.grid, type: 'dashed' } },
    },
    dataZoom: [
      {
        type: 'inside',
        start: 0,
        end: 100,
        filterMode: 'none',
        zoomOnMouseWheel: 'ctrl',
        moveOnMouseWheel: 'shift',
        moveOnMouseMove: true,
      },
    ],
    series: [
      {
        name: 'Successful',
        type: 'line',
        data: successful,
        smooth: 0.38,
        smoothMonotone: 'x',
        showSymbol: false,
        symbol: 'circle',
        symbolSize: 7,
        lineStyle: {
          color: COLORS.accent,
          width: 2.5,
          shadowColor: COLORS.lineShadow,
          shadowBlur: 10,
        },
        itemStyle: { color: COLORS.accentStrong, borderColor: COLORS.accentDeep, borderWidth: 1 },
        areaStyle: {
          opacity: 1,
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: COLORS.areaStart },
              { offset: 0.72, color: COLORS.areaMid },
              { offset: 1, color: COLORS.areaEnd },
            ],
          },
        },
        emphasis: { focus: 'series', lineStyle: { width: 3.5 } },
        tooltip: { valueFormatter },
        markPoint:
          activity?.total > 0
            ? {
                symbol: 'pin',
                symbolSize: 36,
                label: { color: COLORS.accentInk, fontSize: 9, formatter: '{c}' },
                itemStyle: { color: COLORS.accentStrong, borderColor: COLORS.accentDeep },
                data: [{ type: 'max', name: 'Peak' }],
              }
            : undefined,
      },
      {
        name: 'Failed',
        type: 'line',
        data: failed,
        smooth: 0.3,
        showSymbol: true,
        symbol: 'diamond',
        symbolSize: 7,
        lineStyle: { color: COLORS.red, width: 2 },
        itemStyle: { color: COLORS.redStrong, borderColor: COLORS.red, borderWidth: 1 },
        emphasis: { focus: 'series', lineStyle: { width: 3 } },
        tooltip: { valueFormatter },
      },
      {
        name: 'Activity trend',
        type: 'line',
        data: trend,
        smooth: 0.5,
        connectNulls: true,
        showSymbol: false,
        lineStyle: { color: COLORS.muted, width: 1.5, type: 'dashed', opacity: 0.9 },
        emphasis: { focus: 'series', lineStyle: { width: 2.5 } },
        tooltip: { valueFormatter },
        markLine:
          activity?.total > 0
            ? {
                silent: true,
                symbol: 'none',
                precision: 1,
                label: {
                  color: COLORS.muted,
                  fontSize: 8,
                  formatter: 'AVG {c}',
                  position: 'insideEndTop',
                },
                lineStyle: { color: COLORS.accentDeep, width: 1, type: 'dotted', opacity: 0.7 },
                data: [{ type: 'average', name: 'Average activity' }],
              }
            : undefined,
      },
    ],
  }
}
