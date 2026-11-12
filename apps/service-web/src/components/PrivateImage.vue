<script setup>
import { ref, watch, onUnmounted } from 'vue';
import { get } from '../api.js';
import Icon from './Icon.vue';
const props = defineProps({ fileId: String, fileName: String });
const emit = defineEmits(['preview', 'ocr']);
const url = ref(''),
  error = ref(''),
  loading = ref(false);
let controller;
async function load() {
  controller?.abort();
  controller = new AbortController();
  const local = controller;
  error.value = '';
  loading.value = true;
  const old = url.value;
  url.value = '';
  if (old) URL.revokeObjectURL(old);
  try {
    const blob = await get('/files/' + props.fileId, { raw: true, signal: local.signal });
    if (local.signal.aborted) return;
    url.value = URL.createObjectURL(blob);
  } catch (e) {
    if (!local.signal.aborted) error.value = e.message;
  } finally {
    if (controller === local) loading.value = false;
  }
}
watch(() => props.fileId, load, { immediate: true });
onUnmounted(() => {
  controller?.abort();
  if (url.value) URL.revokeObjectURL(url.value);
});
</script>
<template>
  <div class="private-file">
    <button v-if="url" class="image-preview" @click="emit('preview', url, fileName)">
      <img :src="url" :alt="fileName || '用户上传的资料图片'" loading="lazy" />
    </button>
    <div v-else class="image-loading">
      <Icon name="image" :size="24" /><span>{{ loading ? '正在读取授权图片' : error }}</span
      ><button v-if="error" class="text-link" @click="load">重新读取</button>
    </div>
    <div class="file-caption">
      <span>{{ fileName || '资料图片' }}</span
      ><button class="text-link" @click="emit('ocr', fileId)">识别资料</button>
    </div>
  </div>
</template>
