<script setup>
import { onMounted, onUnmounted } from 'vue';
import Icon from './Icon.vue';
defineProps({ title: String, wide: Boolean });
const emit = defineEmits(['close']);
const key = (e) => {
  if (e.key === 'Escape') emit('close');
};
onMounted(() => document.addEventListener('keydown', key));
onUnmounted(() => document.removeEventListener('keydown', key));
</script>
<template>
  <Teleport to="body"
    ><div class="modal-layer" @click.self="emit('close')">
      <section class="modal" :class="{ wide }" role="dialog" aria-modal="true" :aria-label="title">
        <header>
          <h2>{{ title }}</h2>
          <button class="icon-button" aria-label="关闭" @click="emit('close')">
            <Icon name="close" />
          </button>
        </header>
        <div class="modal-body"><slot /></div>
      </section></div
  ></Teleport>
</template>
