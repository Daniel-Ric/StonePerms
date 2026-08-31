<script setup>
defineProps({ name: { type: String, required: true }, size: { type: Number, default: 18 } })
const paths = {
  overview: ['M4 4h6v6H4zM14 4h6v10h-6zM4 14h6v6H4zM14 18h6v2h-6z'],
  server: ['M4 5h16v5H4zM4 14h16v5H4z', 'M7 7.5h.01M7 16.5h.01'],
  users: [
    'M16 20v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 10a4 4 0 1 0 0-8 4 4 0 0 0 0 8M22 20v-2a4 4 0 0 0-3-3.87M16 2.13a4 4 0 0 1 0 7.75',
  ],
  group: ['M12 3v6M5 21v-5h14v5M5 16v-4h14v4', 'M9 3h6v6H9zM2 21h6M16 21h6'],
  track: ['M5 4v16M19 4v16M5 8h14M5 16h14', 'M9 8v8M15 8v8'],
  editor: ['M4 20h4L19 9l-4-4L4 16zM13.5 6.5l4 4M4 20l4-4'],
  display: ['M4 5h16v12H9l-5 4z', 'M8 9h8M8 13h5'],
  audit: ['M6 3h12v18H6z', 'M9 8h6M9 12h6M9 16h4'],
  settings: [
    'M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7',
    'M19 15a2 2 0 0 0 1-1.7V11a2 2 0 0 0-1-1.7l-1-.6.1-1.2-1.6-1.6-1.2.1-.6-1A2 2 0 0 0 13 4h-2a2 2 0 0 0-1.7 1l-.6 1-1.2-.1-1.6 1.6.1 1.2-1 .6A2 2 0 0 0 4 11v2.3A2 2 0 0 0 5 15l1 .6-.1 1.2 1.6 1.6 1.2-.1.6 1A2 2 0 0 0 11 20h2a2 2 0 0 0 1.7-1l.6-1 1.2.1 1.6-1.6-.1-1.2z',
  ],
  shield: ['M12 3 4 6v6c0 5 3.4 8 8 9 4.6-1 8-4 8-9V6z', 'M9 12l2 2 4-5'],
  search: ['M11 19a8 8 0 1 1 0-16 8 8 0 0 1 0 16M21 21l-4.35-4.35'],
  plus: ['M12 5v14M5 12h14'],
  close: ['M6 6l12 12M18 6 6 18'],
  menu: ['M4 6h16M4 12h16M4 18h16'],
  sidebar: ['M4 4h16v16H4zM9 4v16', 'M14 9l-3 3 3 3'],
  refresh: ['M20 6v5h-5M4 18v-5h5', 'M6.1 9a7 7 0 0 1 11.6-2.6L20 9M4 15l2.3 2.6A7 7 0 0 0 18 15'],
  logout: ['M10 17l5-5-5-5M15 12H3M21 19V5a2 2 0 0 0-2-2h-6'],
  warning: ['M12 3 2 21h20zM12 9v5M12 18h.01'],
  check: ['M5 12l4 4L19 6'],
  arrow: ['M5 12h14M13 6l6 6-6 6'],
  chevron: ['M9 18l6-6-6-6'],
  copy: ['M8 8h11v11H8z', 'M5 16H4V5h11v1'],
  trash: ['M4 7h16M9 7V4h6v3M7 7l1 14h8l1-14M10 11v6M14 11v6'],
  clock: ['M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18M12 7v5l3 2'],
  sun: [
    'M12 4V2M12 22v-2M4 12H2M22 12h-2M5.6 5.6 4.2 4.2M19.8 19.8l-1.4-1.4M18.4 5.6l1.4-1.4M4.2 19.8l1.4-1.4',
    'M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10',
  ],
  moon: ['M20 15.2A8.5 8.5 0 0 1 8.8 4 8.5 8.5 0 1 0 20 15.2z'],
  monitor: ['M3 4h18v13H3zM8 21h8M12 17v4'],
  calendar: [
    'M5 4h14v16H5zM8 2v4M16 2v4M5 9h14',
    'M9 13h.01M12 13h.01M15 13h.01M9 16h.01M12 16h.01M15 16h.01',
  ],
  lock: ['M6 10h12v11H6zM8 10V7a4 4 0 0 1 8 0v3'],
  terminal: ['M4 5h16v14H4zM7 9l3 3-3 3M12 15h5'],
  dots: ['M5 12h.01M12 12h.01M19 12h.01'],
  drag: ['M9 5h.01M15 5h.01M9 12h.01M15 12h.01M9 19h.01M15 19h.01'],
}
</script>

<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.7"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path v-for="path in paths[name] || paths.warning" :key="path" :d="path" />
  </svg>
</template>
