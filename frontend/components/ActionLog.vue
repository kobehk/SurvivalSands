<template>
  <div ref="logEl" class="action-log">
    <div
      v-for="entry in logs"
      :key="entry.id"
      :class="['entry', entry.type]"
    >
      <div v-if="entry.type === 'you'" class="you-text">› {{ entry.html }}</div>
      <div v-else-if="entry.type === 'narration'" class="narration-text">{{ entry.html }}</div>
      <div v-else class="system-text">{{ entry.html }}</div>
      <div v-if="entry.meta" class="meta">{{ entry.meta }}</div>
    </div>
    <div v-if="store.busy" class="entry system">
      <div class="system-text thinking">沉吟片刻…</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import { useGameStore } from '../stores/game'
import { storeToRefs } from 'pinia'

const store = useGameStore()
const { logs } = storeToRefs(store)
const logEl = ref<HTMLDivElement | null>(null)

watch(logs, async () => {
  await nextTick()
  if (logEl.value) logEl.value.scrollTop = logEl.value.scrollHeight
}, { deep: true })
</script>

<style scoped>
.action-log {
  flex: 1 1 0; min-height: 0; overflow-y: auto;
  padding: 10px 14px; display: flex; flex-direction: column; gap: 10px;
}
.entry { padding-bottom: 8px; border-bottom: 1px dashed #222; }
.entry:last-child { border-bottom: none; }
.you-text { color: #7090e8; font-size: 13px; }
.narration-text { color: #ccc; font-size: 13px; line-height: 1.6; white-space: pre-wrap; }
.system-text { color: #666; font-size: 12px; font-style: italic; }
.meta { color: #555; font-size: 11px; margin-top: 3px; }
.thinking { animation: blink 1s step-end infinite; }
@keyframes blink { 50% { opacity: 0.3 } }
</style>
