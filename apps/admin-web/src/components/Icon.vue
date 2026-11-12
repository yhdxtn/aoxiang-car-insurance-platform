<script setup>
defineProps({ name: String, size: { type: [Number, String], default: 20 } });
const paths = {
  grid: 'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
  orders: 'M7 3h10l3 3v15H4V3h3 M8 9h8 M8 13h8 M8 17h5',
  users:
    'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M16 4a4 4 0 0 1 0 8 M22 21v-2a4 4 0 0 0-3-3.87 M13 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0',
  tree: 'M9 2h6v6H9z M2 16h6v6H2z M16 16h6v6h-6z M12 8v4 M5 16v-4h14v4',
  shield: 'M12 3 3 7v6c0 5 9 8 9 8s9-3 9-8V7z M8 12l3 3 5-6',
  file: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z M14 2v6h6 M8 13h8 M8 17h5',
  chart: 'M3 3v18h18 M7 16v-5 M12 16V7 M17 16v-8',
  gift: 'M3 8h18v5H3z M5 13v8h14v-8 M12 8v13 M12 8H8a3 3 0 1 1 3-3z M12 8h4a3 3 0 1 0-3-3z',
  sliders: 'M4 21v-7 M4 10V3 M12 21v-9 M12 8V3 M20 21v-5 M20 12V3 M1 10h6 M9 8h6 M17 16h6',
  clock: 'M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0 M12 6v6l4 2',
  lock: 'M5 11h14v10H5z M8 11V7a4 4 0 0 1 8 0v4',
  search: 'M21 21l-6-6 M17 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0',
  plus: 'M12 5v14 M5 12h14',
  refresh: 'M20 8a9 9 0 1 0 1 7 M20 2v6h-6',
  arrow: 'M5 12h14 M14 7l5 5-5 5',
  close: 'M6 6l12 12 M6 18 18 6',
  logout: 'M9 21H3V3h6 M9 12h12 M17 8l4 4-4 4',
  chevron: 'm9 5 7 7-7 7',
  chat: 'M21 11a9 9 0 0 1-9 9H5l-4 3 2-7a9 9 0 1 1 18-5 M7 11h.01 M12 11h.01 M17 11h.01',
  car: 'm3 10 2-6h14l2 6 M2 10h20v9H2z M5 19v3 M19 19v3 M5 14h3 M16 14h3',
  check: 'm4 12 5 5L20 6',
  info: 'M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0 M12 11v6 M12 7h.01',
  upload: 'M12 16V3 M7 8l5-5 5 5 M3 14v7h18v-7',
  send: 'm22 2-7 20-4-9-9-4z M22 2 11 13',
  image: 'M3 3h18v18H3z m3 12 4-4 8 8 M15 7h.01',
  download: 'M12 3v12 m-5-5 5 5 5-5 M3 16v5h18v-5',
  eye: 'M2 12s4-8 10-8 10 8 10 8-4 8-10 8-10-8-10-8 M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0',
  menu: 'M3 6h18 M3 12h18 M3 18h18',
  headset: 'M3 14V9a9 9 0 0 1 18 0v5 M3 11H1v7h5v-7H3 M21 11h2v7h-5v-7h3 M21 18c0 3-4 4-9 4',
};
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
    <path :d="paths[name] || paths.file" />
  </svg>
</template>
