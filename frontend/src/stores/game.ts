import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export interface ItemStack { id: string; qty: number }
export interface AnimalNear {
  id: string; name: string; species: string; description: string
  x: number; y: number; trust: number; fear: number
}
export interface BuiltThing { x: number; y: number; type: string; description: string; tags: string[] }
export interface GroundItem { id: string; qty: number; x: number; y: number }
export interface CropPlot {
  x: number; y: number; crop_type: string; stage: number
  planted_day: number; watered_count: number; fertilized: boolean
}
export interface GameState {
  day: number; time: string; weather: string
  player: {
    x: number; y: number; hp: number; hunger: number; thirst: number; fatigue: number
    inventory: ItemStack[]; skills: Record<string, number>
  }
  builtThings: BuiltThing[]
  animalsNear: AnimalNear[]
  nearbyGroundItems: GroundItem[]
  cropPlots: CropPlot[]
  currentLandmarkId: string | null
  currentLandmarkArrival: string | null
  arrivalPending: boolean
  storyFlags: Record<string, unknown>
  gameOver: boolean
  deathNarration: string | null
}
export interface MapInfo {
  width: number; height: number
  tilesB64: string; exploredB64: string
  landmarks: { id: string; name: string; x: number; y: number; radius: number }[]
}
export interface ItemDef { id: string; zh: string; category: string; notes: string | null }

export interface LogEntry {
  id: number
  type: 'you' | 'narration' | 'system' | 'error'
  html: string
  meta?: string
}

function b64ToBytes(b64: string): Uint8Array {
  const bin = atob(b64)
  const bytes = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
  return bytes
}

export const useGameStore = defineStore('game', () => {
  const mapInfo = ref<MapInfo | null>(null)
  const tiles = ref<Uint8Array | null>(null)
  const explored = ref<Uint8Array | null>(null)
  const gameState = ref<GameState | null>(null)
  const busy = ref(false)
  const itemCatalog = ref<Record<string, ItemDef>>({})
  const logs = ref<LogEntry[]>([])
  let logIdSeq = 0

  // 当前正在运行的 action abort controller
  let currentAbort: AbortController | null = null

  const player = computed(() => gameState.value?.player ?? null)
  const isReady = computed(() => mapInfo.value !== null && gameState.value !== null)

  function addLog(type: LogEntry['type'], html: string, meta?: string) {
    logs.value.push({ id: logIdSeq++, type, html, meta })
  }

  async function refreshAll() {
    const [mapRes, stateRes] = await Promise.all([
      fetch('/api/map').then(r => r.json()),
      fetch('/api/state').then(r => r.json()),
    ])
    mapInfo.value = mapRes
    tiles.value = b64ToBytes(mapRes.tilesB64)
    explored.value = b64ToBytes(mapRes.exploredB64)
    gameState.value = stateRes
  }

  async function step(dx: number, dy: number): Promise<{ ok: boolean; exploredB64?: string }> {
    const r = await fetch('/api/move', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ dx, dy }),
    }).then(r => r.json())
    if (r.ok && r.state) {
      gameState.value = r.state
      if (r.exploredB64) explored.value = b64ToBytes(r.exploredB64)
    }
    return r
  }

  async function submitAction(text: string): Promise<void> {
    if (busy.value) return
    busy.value = true
    addLog('you', escapeHtml(text))

    // 动物交互启发式
    const targeted = gameState.value?.animalsNear.find(a =>
      text.includes(a.name) ||
      (a.species === 'parrot' && text.includes('鹦鹉')) ||
      (a.species === 'monkey' && text.includes('猴')) ||
      (a.species === 'dog' && text.includes('狗'))
    )

    const ctrl = new AbortController()
    currentAbort = ctrl
    const t0 = Date.now()

    try {
      const url = targeted ? '/api/animal' : '/api/action'
      const body = targeted
        ? { animal: targeted.id, action: text }
        : { action: text }
      const r = await fetch(url, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
        signal: ctrl.signal,
      }).then(r => r.json())

      if (r.error) {
        addLog('error', `出错了：${escapeHtml(r.error)}`)
      } else {
        const ms = r.costMs ?? Date.now() - t0
        const narration = cleanNarration(r.narration ?? '')
        addLog('narration', escapeHtml(narration), `${ms}ms${r.ok === false ? ' · 不可行' : ''}`)
        if (r.state) {
          gameState.value = r.state
        }
      }
    } catch (e: unknown) {
      if (e instanceof Error && (e.name === 'AbortError' || ctrl.signal.aborted)) {
        addLog('system', '已中止')
      } else {
        addLog('error', `网络错误：${escapeHtml(String(e))}`)
      }
    }
    currentAbort = null
    busy.value = false
  }

  function abortAction() {
    if (currentAbort) {
      currentAbort.abort()
      currentAbort = null
    }
  }

  async function resetGame() {
    await fetch('/api/reset', { method: 'POST' })
    await refreshAll()
    addLog('system', '世界已重置。')
  }

  async function fetchItemCatalog(): Promise<Record<string, ItemDef>> {
    if (Object.keys(itemCatalog.value).length > 0) return itemCatalog.value
    try {
      const r = await fetch('/api/items').then(r => r.json())
      const catalog: Record<string, ItemDef> = {}
      for (const it of r.items) catalog[it.id] = it
      itemCatalog.value = catalog
    } catch { /* 拉不到静默失败 */ }
    return itemCatalog.value
  }

  async function pollArrival(): Promise<boolean> {
    const fresh = await fetch('/api/state').then(r => r.json() as Promise<GameState>)
    gameState.value = fresh
    return !fresh.arrivalPending || !!fresh.currentLandmarkArrival
  }

  return {
    mapInfo, tiles, explored, gameState, busy, itemCatalog, logs, player, isReady,
    addLog, refreshAll, step, submitAction, abortAction, resetGame, fetchItemCatalog, pollArrival,
  }
})

// ── 工具函数（不依赖 store，供组件/composables 共用）──

export function escapeHtml(s: string): string {
  return s.replace(/[<>&"]/g, c => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' }[c] ?? c))
}

const ITEM_ZH_FALLBACK: Record<string, string> = {}
export function humanizeItem(id: string, catalog?: Record<string, ItemDef>): string {
  return catalog?.[id]?.zh ?? ITEM_ZH_FALLBACK[id] ?? id.replace(/_/g, ' ')
}

export function cleanNarration(text: string): string {
  return text.replace(/\b[a-z][a-z0-9_]*_[a-z0-9_]+\b/g, m => humanizeItem(m))
}
