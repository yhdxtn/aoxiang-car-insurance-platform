<script setup>
import { statusName, statusTone } from '../domain.js';
defineProps({ value: String });
</script>
<template>
  <span class="badge" :class="statusTone(value)"><i></i>{{ statusName(value) }}</span>
</template>
