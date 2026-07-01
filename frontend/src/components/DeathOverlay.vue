<template>
  <Teleport to="body">
    <div v-if="visible" class="death-overlay" :class="{ dark: darkened }">
      <div class="narration">{{ gameState?.deathNarration }}</div>
      <div class="countdown">{{ countdownText }}</div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useGameStore } from '../stores/game'
import { storeToRefs } from 'pinia'

const store = useGameStore()
const { gameState } = storeToRefs(store)

const visible = ref(false)
const darkened = ref(false)
const countdownText = ref('')

watch(gameState, (gs) => {
  if (!gs?.gameOver || !gs.deathNarration) return
  visible.value = true
  setTimeout(() => { darkened.value = true }, 50)

  let secs = 8
  countdownText.value = `${secs} 秒后重生……`
  const timer = setInterval(() => {
    secs--
    if (secs > 0) {
      countdownText.value = `${secs} 秒后重生……`
    } else {
      clearInterval(timer)
      darkened.value = false
      setTimeout(async () => {
        visible.value = false
        await store.refreshAll()
      }, 1200)
    }
  }, 1000)
})
</script>

<style scoped>
.death-overlay {
  position: fixed; inset: 0; z-index: 300;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  padding: 40px; text-align: center;
  background: rgba(0,0,0,0); transition: background 1.2s ease;
  pointer-events: none;
}
.death-overlay.dark { background: rgba(0,0,0,0.92); pointer-events: all; }
.narration {
  max-width: 520px; font-size: 15px; line-height: 1.9; color: #bbb;
  white-space: pre-wrap; opacity: 0; transition: opacity 1.5s ease 0.6s;
}
.death-overlay.dark .narration { opacity: 1; }
.countdown { margin-top: 28px; font-size: 12px; color: #555; }
</style>
