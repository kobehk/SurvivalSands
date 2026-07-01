// 键盘移动队列逻辑
import type { Ref } from 'vue'
import type { AnimState } from './useCanvas'

export function useInput(
  anim: AnimState,
  _canvasEl: Ref<HTMLCanvasElement | null>,
  opts: {
    STEP_MS: number
    RUN_STEP_MS: number
    isBusy: () => boolean
    isPackOpen: () => boolean
    onStep: (dx: number, dy: number, dur: number) => void
    onAbort: () => void
    onOpenPack: () => void
    onClosePack: () => void
  },
) {
  const { STEP_MS, RUN_STEP_MS } = opts
  const moveQueue: { dx: number; dy: number; dur: number }[] = []
  let stepInFlight = false
  let heldRunning = false
  let lastStepAt = 0
  let autoMoveTimer: ReturnType<typeof setTimeout> | null = null
  const heldDirs = new Set<string>()

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
    opts.onStep(next.dx, next.dy, next.dur)
    const remain = next.dur - (performance.now() - anim.t0)
    setTimeout(() => {
      stepInFlight = false
      if (moveQueue.length > 0) takeNext()
    }, Math.max(0, remain))
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
      case 'w': case 'arrowup': dy = -1; break
      case 's': case 'arrowdown': dy = 1; break
      case 'a': case 'arrowleft': dx = -1; break
      case 'd': case 'arrowright': dx = 1; break
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
      case 'w': case 'arrowup': dy = -1; break
      case 's': case 'arrowdown': dy = 1; break
      case 'a': case 'arrowleft': dx = -1; break
      case 'd': case 'arrowright': dx = 1; break
      default: return
    }
    heldDirs.delete(`${dx},${dy}`)
  }

  return { onKeyDown, onKeyUp, queueMove }
}
