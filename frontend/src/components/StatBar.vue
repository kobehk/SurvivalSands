<template>
  <span class="stat-bar">
    <span class="label">{{ label }}</span>
    <span class="bar" :class="kind">
      <span :style="{ width: pct + '%' }" />
    </span>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
const props = defineProps<{ label: string; value: number; kind: string }>()
const pct = computed(() => Math.max(0, Math.min(100, props.value)))
</script>

<style scoped>
.stat-bar { display: inline-flex; align-items: center; gap: 5px; }
.label { color: #666; font-size: 11px; }
.bar { width: 52px; height: 7px; background: #2a2a2a; border-radius: 2px; overflow: hidden; }
.bar span { display: block; height: 100%; transition: width 0.3s; }
.hp span { background: #c33; }
.hunger span { background: #6a3; }
.thirst span { background: #39c; }
.fatigue span { background: #777; }
</style>
