<template>
  <div class="status-bar">
    <span class="time-info">第 {{ gs.day }} 天 · {{ ZH_TIME[gs.time] ?? gs.time }} · {{ ZH_WEATHER[gs.weather] ?? gs.weather }}</span>
    <span class="coord">({{ gs.player.x }}, {{ gs.player.y }})</span>
    <StatBar label="体力" :value="gs.player.hp" kind="hp" />
    <StatBar label="饿" :value="100 - gs.player.hunger" kind="hunger" />
    <StatBar label="渴" :value="100 - gs.player.thirst" kind="thirst" />
    <StatBar label="累" :value="100 - gs.player.fatigue" kind="fatigue" />
    <button class="reset-btn" @click="onReset">重置</button>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useGameStore } from '../stores/game'
import StatBar from './StatBar.vue'

const store = useGameStore()
const gs = computed(() => store.gameState!)

const ZH_TIME: Record<string, string> = { dawn: '黎明', morning: '上午', noon: '正午', afternoon: '下午', dusk: '黄昏', night: '夜晚' }
const ZH_WEATHER: Record<string, string> = { clear: '晴', cloudy: '多云', rain: '雨', storm: '风暴' }

async function onReset() {
  if (!confirm('确定要重置游戏？所有进度会丢失。')) return
  await store.resetGame()
}
</script>

<style scoped>
.status-bar {
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
  padding: 6px 14px; background: rgba(20,20,28,0.88);
  border-top: 1px solid #2a2a3a; font-size: 12px;
}
.time-info { color: #aaa; }
.coord { color: #666; font-variant-numeric: tabular-nums; }
.reset-btn {
  margin-left: auto; background: #2a2a2a; color: #888;
  border: 1px solid #3a3a3a; padding: 2px 8px; border-radius: 3px;
  cursor: pointer; font-size: 11px;
}
.reset-btn:hover { color: #ff6b6b; border-color: #ff6b6b; }
</style>
