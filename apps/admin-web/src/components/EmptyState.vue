<script setup>
import Icon from './Icon.vue';
defineProps({
  title: { type: String, default: '这里还没有记录' },
  text: { type: String, default: '业务产生后会显示在这里。' },
  icon: { type: String, default: 'file' },
});
</script>
<template>
  <div class="empty">
    <div class="empty-icon"><Icon :name="icon" :size="27" /></div>
    <strong>{{ title }}</strong>
    <p>{{ text }}</p>
    <slot />
  </div>
</template>
