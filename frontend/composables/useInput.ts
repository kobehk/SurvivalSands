// 键盘移动队列 —— 支持批量移动，减少 HTTP 往返
import type { Ref } from 'vue'
import type { AnimState } from './useCanvas'

// OCEAN=0, CLIFF=10 不可通行
const IMPASSABLE = new Set([0, 10])

// 地形视野半径（与后端 TERRAIN_SIGHT 一致）
const TERRAIN_SIGHT: Record<number, number> = {
  0: 12,   // OCEAN
  1: 10,   // SHALLOW_WATER
  2: 10,   // BEACH
  3: 8,    // GRASS
  4: 4,    // JUNGLE
  5: 3,    // DEEP_JUNGLE
  6: 12,   // HILLS
  7: 16,   // MOUNTAIN
  8: 4,    // SWAMP
  9: 6,    // RIVER
  10: 12,  // CLIFF
}

export function useInput(
  anim: AnimState,
  tiles: Ref<Uint8Array | null>,
  mapInfo: Ref<{ width: number; height: number } | null>,
  explored: Ref<Uint8Array | null>,
  _canvasEl: Ref<HTMLCanvasElement | null>,
  opts: {
    STEP_MS: number
    RUN_STEP_MS: number
    getPlayerPos: () => { x: number; y: number }
    isBusy: () => boolean
    isPackOpen: () => boolean
    onMoveBatch: (moves: { dx: number; dy: number }[]) => Promise<void>
    onAbort: () => void
    onOpenPack: () => void
    onClosePack: () => void
  },
) {
  const { STEP_MS, RUN_STEP_MS } = opts
  const moveQueue: { dx: number; dy: number; dur: number }[] = []
  const moveBuffer: { dx: number; dy: number }[] = []
  let predictedX = 0
  let predictedY = 0
  let predInit = false
  let stepInFlight = false
  let heldRunning = false
  let lastStepAt = 0
  let autoMoveTimer: ReturnType<typeof setTimeout> | null = null
  const heldDirs = new Set<string>()

  function ensurePred() {
    if (!predInit) {
      const p = opts.getPlayerPos()
      predictedX = p.x
      predictedY = p.y
      predInit = true
    }
  }

  function isPassable(x: number, y: number): boolean {
    const t = tiles.value
    const mi = mapInfo.value
    if (!t || !mi) return true
    if (x < 0 || x >= mi.width || y < 0 || y >= mi.height) return false
    return !IMPASSABLE.has(t[y * mi.width + x])
  }

  function localReveal(cx: number, cy: number) {
    const ex = explored.value
    const mi = mapInfo.value
    const tl = tiles.value
    if (!ex || !mi || !tl) return
    // 从本地 tiles 读取地形，确定视野半径（与后端 TERRAIN_SIGHT 一致）
    const t = tl[cy * mi.width + cx] ?? 3
    const sight = TERRAIN_SIGHT[t] ?? 6
    // 需要 copy 一份触发 Vue 响应
    const copy = new Uint8Array(ex)
    for (let dy = -sight; dy <= sight; dy++) {
      for (let dx = -sight; dx <= sight; dx++) {
        if (dx * dx + dy * dy > sight * sight) continue
        const nx = cx + dx; const ny = cy + dy
        if (nx < 0 || ny < 0 || nx >= mi.width || ny >= mi.height) continue
        const idx = ny * mi.width + nx
        if (copy[idx] < 1) copy[idx] = 1  // 标记为「见过」
      }
    }
    // 当前格标记为「走过」
    const curIdx = cy * mi.width + cx
    if (copy[curIdx] < 2) copy[curIdx] = 2
    explored.value = copy
  }

  function queueMove(dx: number, dy: number, running: boolean) {
    const dur = running ? RUN_STEP_MS : STEP_MS
    const last = moveQueue[moveQueue.length - 1]
    if (!last || last.dx !== dx || last.dy !== dy) moveQueue.push({ dx, dy, dur })
    if (!stepInFlight) takeNext()
  }

  async function takeNext() {
    if (opts.isBusy()) return
    const next = moveQueue.shift()
    if (!next) return
    stepInFlight = true

    ensurePred()
    const tx = predictedX + next.dx
    const ty = predictedY + next.dy

    if (isPassable(tx, ty)) {
      // 本地预测可通行 → 立即播放动画
      Object.assign(anim, {
        fromX: predictedX, fromY: predictedY,
        toX: tx, toY: ty,
        t0: performance.now(), dur: next.dur,
      })
      predictedX = tx
      predictedY = ty
      moveBuffer.push({ dx: next.dx, dy: next.dy })
      // 客户端迷雾预测：用当前格地形决定视野半径
      localReveal(tx, ty)
    } else {
      // 不可通行 → 短暂回弹
      Object.assign(anim, {
        fromX: predictedX, fromY: predictedY,
        toX: predictedX, toY: predictedY,
        t0: performance.now(), dur: 120,
      })
    }

    setTimeout(() => {
      stepInFlight = false
      if (moveQueue.length > 0) takeNext()
    }, next.dur)
  }

  async function flushBatch() {
    if (moveBuffer.length === 0) return
    const batch = [...moveBuffer]
    moveBuffer.length = 0
    // 清空本地状态，让下次按键从服务器位置重新计算
    moveQueue.length = 0
    stepInFlight = false
    predInit = false
    await opts.onMoveBatch(batch)
  }

  function scheduleAutoMove() {
    if (autoMoveTimer) return
    const now = performance.now()
    const stepDelay = heldRunning ? RUN_STEP_MS : STEP_MS
    const wait = Math.max(0, stepDelay - (now - lastStepAt))
    autoMoveTimer = setTimeout(() => {
      autoMoveTimer = null
      if (heldDirs.size === 0) return
      const dir = Array.from(heldDirs).pop()!
      const [dx, dy] = dir.split(',').map(Number)
      lastStepAt = performance.now()
      queueMove(dx, dy, heldRunning)
      if (heldDirs.size > 0) scheduleAutoMove()
    }, wait)
  }

  function onKeyDown(e: KeyboardEvent) {
    // ESC
    if (e.key === 'Escape') {
      if (opts.isPackOpen()) { e.preventDefault(); opts.onClosePack(); return }
      opts.onAbort()
      return
    }
    // I — 背包
    if ((e.key === 'i' || e.key === 'I') && document.activeElement !== document.getElementById('action-input')) {
      e.preventDefault()
      opts.isPackOpen() ? opts.onClosePack() : opts.onOpenPack()
      return
    }
    // WASD / 方向键 — 输入框聚焦时当字符
    if (document.activeElement === document.getElementById('action-input')) return
    if (opts.isPackOpen()) return
    let dx = 0; let dy = 0
    switch (e.key.toLowerCase()) {
      case 'w': case 'arrowup':    dy = -1; break
      case 's': case 'arrowdown':  dy =  1; break
      case 'a': case 'arrowleft':  dx = -1; break
      case 'd': case 'arrowright': dx =  1; break
      case 'shift': heldRunning = true; return
      default: return
    }
    e.preventDefault()
    if (e.repeat) return
    const key = `${dx},${dy}`
    if (heldDirs.has(key)) return
    heldDirs.add(key)
    scheduleAutoMove()
  }

  function onKeyUp(e: KeyboardEvent) {
    if (e.key.toLowerCase() === 'shift') { heldRunning = false; return }
    let dx = 0; let dy = 0
    switch (e.key.toLowerCase()) {
      case 'w': case 'arrowup':    dy = -1; break
      case 's': case 'arrowdown':  dy =  1; break
      case 'a': case 'arrowleft':  dx = -1; break
      case 'd': case 'arrowright': dx = 1; break
      default: return
    }
    heldDirs.delete(`${dx},${dy}`)
    if (heldDirs.size === 0) {
      if (autoMoveTimer) { clearTimeout(autoMoveTimer); autoMoveTimer = null }
      flushBatch()
    }
  }

  return { onKeyDown, onKeyUp, queueMove }
}
