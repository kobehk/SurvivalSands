<template>
  <div ref="containerEl" class="map-container" />
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { useGameStore } from '../stores/game'
import { useCanvas } from '../composables/useCanvas'
import { useInput } from '../composables/useInput'
import { storeToRefs } from 'pinia'

const store = useGameStore()
const { mapInfo, tiles, explored, gameState, busy } = storeToRefs(store)

const containerEl = ref<HTMLElement | null>(null)
const canvas = useCanvas(containerEl, { mapInfo, tiles, explored, gameState })

const packOpen = ref(false)
const emit = defineEmits<{ openPack: []; closePack: [] }>()

const input = useInput(canvas.anim, containerEl as any, {
  STEP_MS: canvas.STEP_MS,
  RUN_STEP_MS: canvas.RUN_STEP_MS,
  isBusy: () => busy.value,
  isPackOpen: () => packOpen.value,
  onStep: async (dx, dy, dur) => {
    const fromX = gameState.value!.player.x
    const fromY = gameState.value!.player.y
    canvas.setAnim(fromX, fromY, fromX + dx, fromY + dy, dur)
    const r = await store.step(dx, dy)
    if (!r.ok) canvas.setAnim(fromX, fromY, fromX, fromY, 120)
  },
  onAbort: () => store.abortAction(),
  onOpenPack: () => emit('openPack'),
  onClosePack: () => emit('closePack'),
})

defineExpose({ setPackOpen: (v: boolean) => { packOpen.value = v } })

const ro = new ResizeObserver(canvas.resize)

onMounted(() => {
  canvas.init()
  if (containerEl.value) ro.observe(containerEl.value)
  window.addEventListener('keydown', input.onKeyDown)
  window.addEventListener('keyup', input.onKeyUp)
})

onUnmounted(() => {
  canvas.dispose()
  ro.disconnect()
  window.removeEventListener('keydown', input.onKeyDown)
  window.removeEventListener('keyup', input.onKeyUp)
})

// 地图数据就绪 → 构建地形（只做一次）
watch(mapInfo, (mi) => {
  if (!mi) return
  canvas.buildTerrain()
  canvas.rebuildObjects()
})

// state 更新 → 重建动态物体 + 同步动画锚点
watch(gameState, (gs) => {
  if (!gs) return
  canvas.syncAnim(gs.player.x, gs.player.y)
  canvas.rebuildObjects()
})
</script>

<style scoped>
.map-container {
  width: 100%;
  height: 100%;
  background: #0a0a14;
  overflow: hidden;
}

/* Three.js 插入的 canvas 填满容器 */
.map-container :deep(canvas) {
  display: block;
  width: 100% !important;
  height: 100% !important;
}
</style>
