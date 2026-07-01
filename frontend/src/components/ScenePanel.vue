<template>
  <div class="scene-panel">
    <div class="scene-title">{{ title }}</div>
    <div class="scene-desc">
      <template v-if="gs?.arrivalPending && !arrival">
        <em class="pending">你环顾四周……</em>
      </template>
      <template v-else>
        {{ displayText }}
      </template>
    </div>

    <!-- 附近动物 -->
    <div v-if="gs?.animalsNear.length" class="animals">
      <span v-for="a in gs!.animalsNear" :key="a.id" class="animal-chip">
        {{ ANIMAL_SYMBOL[a.species] ?? '🐾' }} {{ a.name }}
        <span class="trust">{{ trustHint(a.trust) }}</span>
      </span>
    </div>

    <!-- 地面物品 -->
    <div v-if="groundSummary" class="ground-items">
      📦 {{ groundSummary }}
    </div>

    <!-- 附近建造物 -->
    <div v-if="nearbyBuilt.length" class="built-list">
      <span v-for="b in nearbyBuilt" :key="`${b.x},${b.y},${b.type}`" class="built-chip">
        {{ builtIcon(b.tags) }} {{ b.type }}
        <span v-if="b.description" class="built-desc">· {{ b.description }}</span>
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useGameStore } from '../stores/game'
import { storeToRefs } from 'pinia'

const store = useGameStore()
const { gameState: gs, mapInfo } = storeToRefs(store)

const ANIMAL_SYMBOL: Record<string, string> = { parrot: '🦜', monkey: '🐒', dog: '🐕' }

const LM_BLURB: Record<string, string> = {
  wreck: '小船的残骸半埋在沙里。这是你漂上来的地方。',
  fresh_spring: '一股清泉从岩石间渗出。',
  coconut_grove: '高大的椰子树，地上有掉落的椰子。',
  rocky_beach: '岩石海岸。退潮时礁石间能找到东西。',
  cliff_top: '岛上最高的崖顶。视野极佳。',
  abandoned_camp: '一处废弃的营地，有过燃烧痕迹。',
  cave: '岩壁里的洞穴入口，黑漆漆的。',
  mangrove: '红树林沼泽，闷热潮湿。',
  lookout_hill: '视野开阔的小丘陵。',
  deep_jungle_clearing: '密林深处一片空地，有棵被雷劈过的枯树。',
  shipwreck_far: '退潮时能看到礁石间的另一艘沉船。',
  message_in_bottle: '沙滩上的漂流瓶。',
  bone_pile: '一堆白骨和锈刀。',
  banana_grove: '野生香蕉林。',
  tide_pool: '潮汐池，里面困着小生物。',
  old_tree: '一棵不知年龄的巨树。',
  cliff_shelter: '崖底一处天然凹陷，可以遮风挡雨。',
  salt_flat: '海边晒盐的低洼。',
  fire_pit: '地上一圈烧黑的痕迹。',
  cliff_path: '一条蜿蜒的悬崖小径。',
}
const TERRAIN_NAME: Record<number, string> = {
  0: '深海', 1: '浅滩', 2: '沙滩', 3: '草地', 4: '丛林',
  5: '密林', 6: '丘陵', 7: '山地', 8: '沼泽', 9: '河流', 10: '悬崖',
}

function trustHint(t: number) {
  if (t < 10) return '警惕'
  if (t < 40) return '防备'
  if (t < 70) return '接受'
  return '亲近'
}

const lm = computed(() => {
  if (!gs.value || !mapInfo.value) return null
  return mapInfo.value.landmarks.find(l => l.id === gs.value!.currentLandmarkId) ?? null
})
const arrival = computed(() => gs.value?.currentLandmarkArrival ?? null)
const terrain = computed(() => {
  if (!gs.value || !mapInfo.value) return 0
  // tiles 不在 store computed 里，只能用 0 fallback；可在父组件传入
  return 0
})

const title = computed(() => {
  if (!gs.value || !mapInfo.value) return '…'
  const l = lm.value
  if (l) return l.name
  return `荒野 · ${TERRAIN_NAME[terrain.value] ?? ''}`
})

const displayText = computed(() => {
  if (!gs.value) return ''
  if (lm.value) return arrival.value ?? LM_BLURB[lm.value.id] ?? ''
  return ''
})

const groundSummary = computed(() => {
  if (!gs.value) return ''
  const grouped: Record<string, number> = {}
  for (const g of gs.value.nearbyGroundItems) grouped[g.id] = (grouped[g.id] ?? 0) + g.qty
  const entries = Object.entries(grouped)
  if (!entries.length) return ''
  return entries.map(([id, qty]) => `${store.itemCatalog[id]?.zh ?? id}×${qty}`).join('、')
})

const nearbyBuilt = computed(() => {
  if (!gs.value) return []
  const p = gs.value.player
  return gs.value.builtThings.filter(b =>
    Math.abs(b.x - p.x) <= 3 && Math.abs(b.y - p.y) <= 3
  )
})

function builtIcon(tags: string[] = []): string {
  if (tags.includes('fire')) return '🔥'
  if (tags.includes('shelter')) return '🏕️'
  if (tags.includes('storage')) return '📦'
  return '🏠'
}
</script>

<style scoped>
.scene-panel { padding: 12px 14px; border-bottom: 1px solid #2a2a3a; }
.scene-title { font-size: 14px; font-weight: 600; color: #f0c97c; margin-bottom: 6px; }
.scene-desc { font-size: 12px; color: #999; line-height: 1.55; }
.pending { color: #666; }
.animals { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 6px; }
.animal-chip { font-size: 12px; color: #aaa; background: #1f1f2a; border-radius: 4px; padding: 2px 7px; }
.trust { color: #666; margin-left: 4px; }
.ground-items { margin-top: 6px; font-size: 12px; color: #c4a84a; }
.built-list { margin-top: 6px; display: flex; flex-direction: column; gap: 3px; }
.built-chip { font-size: 12px; color: #9a8a6a; }
.built-desc { color: #666; font-size: 11px; }
</style>
