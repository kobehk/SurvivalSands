<template>
  <div class="action-input-wrap">
    <!-- 快捷操作按钮 -->
    <div class="shortcuts">
      <button
        v-for="s in shortcuts"
        :key="s.label"
        class="shortcut-btn"
        :disabled="store.busy"
        @click="submit(s.action)"
      >{{ s.label }}</button>
      <button class="shortcut-btn pack-btn" @click="emit('openPack')">背包 [I]</button>
    </div>
    <!-- 输入框 -->
    <div class="input-row">
      <input
        id="action-input"
        v-model="text"
        placeholder="描述你想做的事（回车提交）"
        autocomplete="off"
        :disabled="store.busy"
        @keydown.enter="onEnter"
        @keydown.esc="onEsc"
      />
      <button
        v-if="store.busy"
        class="abort-btn"
        @click="store.abortAction()"
      >中止</button>
    </div>
    <div class="hint">WASD 走动 · Shift 跑步 · I 背包 · ESC 中止</div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useGameStore } from '../stores/game'

const store = useGameStore()
const emit = defineEmits<{ openPack: [] }>()
const text = ref('')

const shortcuts = [
  { label: '休息', action: '我休息一会儿' },
  { label: '喝水', action: '我喝点水' },
  { label: '吃东西', action: '我吃点东西' },
  { label: '查看配方', action: '我学会了什么配方' },
  { label: '环顾四周', action: '我环顾四周看看有什么' },
]

async function submit(action: string) {
  if (!action.trim() || store.busy) return
  await store.submitAction(action)
}

async function onEnter() {
  const t = text.value.trim()
  if (!t) return
  text.value = ''
  if (t === '/reset') { await store.resetGame(); return }
  await store.submitAction(t)
}

function onEsc() {
  if (store.busy) store.abortAction()
  else text.value = ''
}
</script>

<style scoped>
.action-input-wrap {
  flex: 0 0 auto; padding: 10px 12px;
  border-top: 1px solid #2a2a3a; background: rgba(20,20,28,0.95);
}
.shortcuts { display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 8px; }
.shortcut-btn {
  background: #1e1e28; color: #8a8a9a; border: 1px solid #333;
  padding: 4px 9px; border-radius: 4px; cursor: pointer; font-size: 12px;
  transition: background 0.15s, color 0.15s;
}
.shortcut-btn:hover:not(:disabled) { background: #2a2a3a; color: #ccc; }
.shortcut-btn:disabled { opacity: 0.4; cursor: default; }
.pack-btn { color: #7090e8; border-color: #3a3a6a; }
.input-row { display: flex; gap: 6px; }
#action-input {
  flex: 1; padding: 9px 12px; font-size: 13px;
  background: #1a1a24; border: 1px solid #333; color: #eee;
  border-radius: 6px; font-family: inherit; outline: none;
  transition: border-color 0.2s;
}
#action-input:focus { border-color: #f0c97c; }
#action-input:disabled { opacity: 0.5; }
.abort-btn {
  background: #3a1a1a; color: #ff8a8a; border: 1px solid #5a2a2a;
  padding: 0 12px; border-radius: 6px; cursor: pointer; font-size: 12px;
}
.abort-btn:hover { background: #4a2020; }
.hint { font-size: 11px; color: #444; margin-top: 5px; }
</style>
