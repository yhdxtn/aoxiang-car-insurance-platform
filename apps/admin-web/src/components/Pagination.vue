<script setup>
defineProps({ page: Number, total: Number, size: { type: Number, default: 20 } });
defineEmits(['change']);
</script>
<template>
  <div class="pagination">
    <span>共 {{ total || 0 }} 条记录</span>
    <div>
      <button class="button small" :disabled="page <= 1" @click="$emit('change', page - 1)">
        上一页</button
      ><span>第 {{ page }} 页</span
      ><button
        class="button small"
        :disabled="page * size >= total"
        @click="$emit('change', page + 1)"
      >
        下一页
      </button>
    </div>
  </div>
</template>
