<template>
  <div class="env-status">
    <!-- 建造物效果 -->
    <div class="built-tags">
      <span
        v-for="tag in BUILT_TAGS"
        :key="tag.key"
        :class="['tag', hasTag(tag.key) ? 'active' : 'dim']"
        :title="tag.effect"
      >
        {{ tag.icon }} {{ tag.label }}
        <span v-if="hasTag(tag.key)" class="effect">{{ tag.effect }}</span>
      </span>
    </div>
    <!-- 技能（全部显示，0级也显示） -->
    <div class="skills">
      <span v-for="[k, v] in allSkills" :key="k" class="skill" :class="{ zero: v === 0 }">
        {{ SKILL_ZH[k] ?? k }}<span class="lv">{{ v }}</span>
      </span>
    </div>
    <!-- 附近作物 -->
    <div v-if="cropSummary" class="crops">{{ cropSummary }}</div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useGameStore } from '../stores/game'
import { storeToRefs } from 'pinia'

const store = useGameStore()
const { gameState: gs } = storeToRefs(store)

const SKILL_ZH: Record<string, string> = { crafting: '制作', foraging: '采集', fishing: '捕鱼', cooking: '烹饪' }

const BUILT_TAGS = [
  { key: 'fire',    icon: '🔥', label: '火',   effect: '休息恢复+35%' },
  { key: 'shelter', icon: '🏕️', label: '遮蔽', effect: '雨天消耗-30%' },
  { key: 'storage', icon: '📦', label: '储物', effect: '食物不腐败' },
]

function hasTag(tag: string): boolean {
  if (!gs.value) return false
  const p = gs.value.player
  const RADIUS = 2
  return gs.value.builtThings.some(b =>
    (b.tags ?? []).includes(tag) &&
    Math.abs(b.x - p.x) <= RADIUS && Math.abs(b.y - p.y) <= RADIUS
  )
}

const allSkills = computed(() => {
  if (!gs.value) return []
  const s = gs.value.player.skills
  return ['crafting', 'foraging', 'fishing', 'cooking'].map(k => [k, s[k] ?? 0] as [string, number])
})

const CROP_STAGE = { 0: '🌿', 1: '🌱', 2: '🌾' } as Record<number, string>
const CROP_ZH: Record<string, string> = { seeds: '种子', banana_seedling: '香蕉幼苗' }

const cropSummary = computed(() => {
  if (!gs.value) return ''
  const p = gs.value.player
  const nearby = gs.value.cropPlots.filter(c =>
    Math.abs(c.x - p.x) <= 5 && Math.abs(c.y - p.y) <= 5
  )
  if (!nearby.length) return ''
  return nearby.map(c =>
    `${CROP_STAGE[c.stage]}${CROP_ZH[c.crop_type] ?? c.crop_type}${c.stage === 2 ? '(可收)' : ''}`
  ).join(' ')
})
</script>

<style scoped>
.env-status {
  padding: 8px 14px; border-bottom: 1px solid #2a2a3a;
  display: flex; flex-direction: column; gap: 7px;
}
.built-tags { display: flex; flex-wrap: wrap; gap: 6px; }
.tag {
  font-size: 11px; padding: 3px 8px; border-radius: 4px;
  display: flex; align-items: center; gap: 4px;
}
.tag.active { color: #e8d070; background: #2a2408; border: 1px solid #4a3e10; }
.tag.dim    { color: #333; background: #141418; border: 1px solid #222; }
.effect { color: #a08840; font-size: 10px; margin-left: 2px; }
.skills { display: flex; gap: 8px; flex-wrap: wrap; }
.skill {
  font-size: 11px; color: #888;
  display: inline-flex; align-items: baseline; gap: 3px;
}
.skill.zero { color: #3a3a3a; }
.lv {
  font-size: 12px; font-variant-numeric: tabular-nums;
  color: #7aaa55; font-weight: 600;
}
.skill.zero .lv { color: #3a3a3a; }
.crops { font-size: 11px; color: #7aaa55; }
</style>

