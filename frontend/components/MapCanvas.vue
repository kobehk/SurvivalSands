<template>
  <div ref="containerEl" class="map-container" />
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, computed } from 'vue'
import { useGameStore } from '../stores/game'
import { useCanvas } from '../composables/useCanvas'
import { useInput } from '../composables/useInput'
import { storeToRefs } from 'pinia'

const store = useGameStore()
const { mapInfo, tiles, explored, gameState, busy } = storeToRefs(store)

const containerEl = ref<HTMLElement | null>(null)
const tileOverrides = computed(() => gameState.value?.tileOverrides ?? [])
const canvas = useCanvas(containerEl, { mapInfo, tiles, explored, gameState, tileOverrides })

const packOpen = ref(false)
const emit = defineEmits<{ openPack: []; closePack: [] }>()

const input = useInput(canvas.anim, tiles, mapInfo, explored, containerEl as any, {
  STEP_MS: canvas.STEP_MS,
  RUN_STEP_MS: canvas.RUN_STEP_MS,
  getPlayerPos: () => ({
    x: gameState.value?.player.x ?? 0,
    y: gameState.value?.player.y ?? 0,
  }),
  isBusy: () => busy.value,
  isPackOpen: () => packOpen.value,
  onMoveBatch: async (moves) => {
    await store.stepBatch(moves)
  },
  onAbort: () => store.abortAction(),
  onOpenPack: () => emit('openPack'),
  onClosePack: () => emit('closePack'),
})

defineExpose({ setPackOpen: (v: boolean) => { packOpen.value = v } })

function onDebugKey(e: KeyboardEvent) {
  if (e.key === '`' && document.activeElement !== document.getElementById('action-input')) {
    e.preventDefault()
    canvas.toggleDebugFog()
  }
}

const ro = new ResizeObserver(canvas.resize)

onMounted(() => {
  canvas.init()
  if (containerEl.value) ro.observe(containerEl.value)
  window.addEventListener('keydown', input.onKeyDown)
  window.addEventListener('keyup', input.onKeyUp)
  window.addEventListener('keydown', onDebugKey)
})

onUnmounted(() => {
  canvas.dispose()
  ro.disconnect()
  window.removeEventListener('keydown', input.onKeyDown)
  window.removeEventListener('keyup', input.onKeyUp)
  window.removeEventListener('keydown', onDebugKey)
})

// 地图数据就绪 → 构建地形 + 地标 + 房间角色（只做一次）
watch(mapInfo, (mi) => {
  if (!mi) return
  canvas.buildTerrain()
  canvas.rebuildObjects()
})

// 游戏状态首次就绪 → 创建角色小人
watch(() => store.isReady, (ready) => {
  if (ready) canvas.ensurePlayerMesh()
})

// state 更新 → 同步动画 + 重建动态物体 + 更新地块 override
watch(gameState, (gs) => {
  if (!gs) return
  canvas.syncAnim(gs.player.x, gs.player.y)
  canvas.rebuildDynamicObjects()
  canvas.updateTileOverrides()
})
</script>

<style scoped>
.map-container {
  width: 100%;
  height: 100%;
  background: #0a0a14;
  overflow: hidden;
}
</style>
