<template>
  <Teleport to="body">
    <div v-if="isOpen" class="pack-overlay" @click.self="close">
      <div class="pack-panel">
        <div class="pack-header">
          <span>背包 <span class="summary">{{ summary }}</span></span>
          <button class="close-btn" @click="close">关闭 (ESC / I)</button>
        </div>
        <div class="pack-body">
          <div v-if="!inv.length" class="empty">背包空空如也。</div>
          <template v-else>
            <div v-for="cat in activeCats" :key="cat" class="cat-section">
              <div class="cat-label">{{ CATEGORY_LABEL[cat] ?? cat }}</div>
              <div
                v-for="item in byCat[cat]"
                :key="item.stack.id"
                class="item-row"
              >
                <span class="item-name">{{ item.def?.zh ?? item.stack.id }}</span>
                <span class="item-qty">×{{ item.stack.qty }}</span>
                <span v-if="item.def?.notes" class="item-notes">{{ item.def.notes }}</span>
                <button
                  v-if="item.stack.id === 'bottle_message'"
                  class="read-btn"
                  @click="readBottle"
                >阅读</button>
              </div>
            </div>
            <!-- 技能 -->
            <div v-if="skillEntries.length" class="cat-section">
              <div class="cat-label">技能</div>
              <div v-for="[k, v] in skillEntries" :key="k" class="item-row">
                <span class="item-name">{{ SKILL_ZH[k] ?? k }}</span>
                <span class="item-qty lv">Lv {{ v }}</span>
              </div>
            </div>
          </template>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, watch } from 'vue'
import { useGameStore } from '../stores/game'
import { storeToRefs } from 'pinia'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [boolean]; close: [] }>()

const store = useGameStore()
const { gameState: gs, itemCatalog } = storeToRefs(store)

const isOpen = computed(() => props.modelValue)
function close() { emit('update:modelValue', false); emit('close') }

const CATEGORY_LABEL: Record<string, string> = {
  food: '食物', water: '水', fuel: '燃料', material: '原料', tool: '工具', misc: '杂物',
}
const CATEGORY_ORDER = ['food', 'water', 'fuel', 'material', 'tool', 'misc']
const SKILL_ZH: Record<string, string> = { crafting: '制作', foraging: '采集', fishing: '捕鱼', cooking: '烹饪' }

const inv = computed(() => gs.value?.player.inventory ?? [])
const summary = computed(() => {
  if (!inv.value.length) return ''
  const total = inv.value.reduce((s, x) => s + x.qty, 0)
  return `· ${inv.value.length} 种 / 共 ${total} 件`
})

const byCat = computed(() => {
  const map: Record<string, { stack: { id: string; qty: number }; def: typeof itemCatalog.value[string] | undefined }[]> = {}
  for (const stack of inv.value) {
    const def = itemCatalog.value[stack.id]
    const cat = def?.category ?? 'misc'
    ;(map[cat] ??= []).push({ stack, def })
  }
  return map
})

const activeCats = computed(() => CATEGORY_ORDER.filter(c => byCat.value[c]?.length))

const skillEntries = computed(() =>
  Object.entries(gs.value?.player.skills ?? {}).filter(([, v]) => v > 0)
)

// 打开时拉物品目录
watch(isOpen, (v) => { if (v) store.fetchItemCatalog() })

async function readBottle() {
  close()
  await store.submitAction('我读瓶中信')
}
</script>

<style scoped>
.pack-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.65);
  z-index: 200; display: flex; align-items: center; justify-content: center;
}
.pack-panel {
  width: min(680px, 92vw); max-height: 80vh; overflow-y: auto;
  background: #1a1a24; border: 1px solid #3a3a4a; border-radius: 10px;
  padding: 20px 24px; box-shadow: 0 10px 50px rgba(0,0,0,0.7);
}
.pack-header {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 16px; font-size: 16px; color: #f0c97c; font-weight: 600;
}
.summary { color: #666; font-size: 12px; font-weight: normal; }
.close-btn { background: none; border: none; color: #666; cursor: pointer; font-size: 12px; padding: 0; }
.close-btn:hover { color: #ccc; }
.empty { color: #555; font-style: italic; text-align: center; padding: 30px; }
.cat-section { margin-bottom: 16px; }
.cat-label { font-size: 11px; color: #555; text-transform: uppercase; letter-spacing: 1px;
  border-bottom: 1px solid #2a2a3a; padding-bottom: 4px; margin-bottom: 8px; }
.item-row {
  display: grid; grid-template-columns: 1fr auto; gap: 8px 16px;
  padding: 5px 4px; border-bottom: 1px dashed #222; font-size: 13px;
}
.item-row:last-child { border-bottom: none; }
.item-name { color: #ccc; }
.item-qty { color: #f0c97c; font-variant-numeric: tabular-nums; }
.item-qty.lv { color: #7aaa55; }
.item-notes { color: #666; font-size: 11px; grid-column: 1 / -1; margin-top: 1px; }
.read-btn {
  grid-column: 1 / -1; margin-top: 4px; width: fit-content;
  background: #2a200a; color: #c4a84a; border: 1px solid #5a4820;
  padding: 3px 10px; border-radius: 4px; cursor: pointer; font-size: 11px;
}
.read-btn:hover { background: #3a2a0a; }
</style>
