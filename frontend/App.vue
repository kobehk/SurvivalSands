<template>
  <div class="app">
    <MapCanvas
      ref="mapRef"
      class="map-layer"
      @open-pack="packOpen = true"
      @close-pack="packOpen = false"
    />

    <div v-if="store.isReady" class="status-float">
      <StatusBar />
    </div>

    <div v-if="store.isReady" class="right-panel">
      <ScenePanel />
      <EnvStatus />
      <ActionLog />
      <ActionInput @open-pack="packOpen = true" />
    </div>

    <PackOverlay v-model="packOpen" @close="packOpen = false" />
    <DeathOverlay />

    <div v-if="!store.isReady" class="loading">
      <div class="loading-text">加载中…</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { useGameStore } from './stores/game'
import MapCanvas from './components/MapCanvas.vue'
import StatusBar from './components/StatusBar.vue'
import ScenePanel from './components/ScenePanel.vue'
import EnvStatus from './components/EnvStatus.vue'
import ActionLog from './components/ActionLog.vue'
import ActionInput from './components/ActionInput.vue'
import PackOverlay from './components/PackOverlay.vue'
import DeathOverlay from './components/DeathOverlay.vue'

const store = useGameStore()
const packOpen = ref(false)
const mapRef = ref<InstanceType<typeof MapCanvas> | null>(null)

watch(packOpen, (v) => mapRef.value?.setPackOpen(v))

let pollTimer: ReturnType<typeof setTimeout> | null = null
watch(() => store.gameState?.arrivalPending, (pending) => {
  if (!pending || store.gameState?.currentLandmarkArrival) return
  if (pollTimer) return
  pollTimer = setTimeout(async function poll() {
    pollTimer = null
    const done = await store.pollArrival()
    if (!done) pollTimer = setTimeout(poll, 1500)
  }, 1500)
})

onMounted(async () => {
  await store.refreshAll()
  store.addLog('system', '你睁开眼睛。咸涩的海风扑面而来。')
  store.addLog('system', 'WASD 走动，右侧输入框描述你想做什么，I 查看背包。')
  store.fetchItemCatalog()
})
</script>

<style>
* { box-sizing: border-box; }
html, body {
  height: 100%; margin: 0; overflow: hidden;
  background: #0a0a14; color: #ddd;
  font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif;
}
</style>

<style scoped>
.app { position: relative; width: 100vw; height: 100dvh; overflow: hidden; }
.map-layer { position: absolute; inset: 0; }
.status-float { position: absolute; bottom: 0; left: 0; right: 380px; }
.right-panel {
  position: absolute; top: 0; right: 0; bottom: 0; width: 380px;
  background: rgba(16,16,22,0.92); border-left: 1px solid #2a2a3a;
  display: flex; flex-direction: column; overflow: hidden;
}
.loading {
  position: absolute; inset: 0; background: #0a0a14;
  display: flex; align-items: center; justify-content: center;
}
.loading-text { color: #555; font-size: 14px; }
@media (max-width: 720px) {
  .right-panel { width: 100%; top: 50%; border-left: none; border-top: 1px solid #2a2a3a; }
  .status-float { right: 0; }
}
</style>
