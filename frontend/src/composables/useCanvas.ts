/**
 * Three.js 3D 渲染，替换原有 canvas 2D。
 *
 * 设计决策：
 * - 地形：每格一个 BoxGeometry，高度由 Terrain 类型决定
 * - 迷雾：未探索格子不渲染，见过但未走过的格子用半透明黑色 plane 覆盖
 * - 地标/建造物：柱状几何体（CylinderGeometry / BoxGeometry）
 * - 动物/玩家：圆柱 + 半球
 * - 摄像机：OrthographicCamera，支持旋转（Y轴）和缩放，固定俯仰角
 */

import * as THREE from 'three'
import type { Ref } from 'vue'
import type { MapInfo, GameState } from '../stores/game'

// ── 地形高度和颜色 ──────────────────────────────────────────────
const TERRAIN_HEIGHT: Record<number, number> = {
  0: 0,    // OCEAN
  1: 0.05, // SHALLOW_WATER
  2: 0.12, // BEACH
  3: 0.18, // GRASS
  4: 0.22, // JUNGLE
  5: 0.28, // DEEP_JUNGLE
  6: 0.38, // HILLS
  7: 0.55, // MOUNTAIN
  8: 0.10, // SWAMP
  9: 0.08, // RIVER
  10: 0.65, // CLIFF
}

const TERRAIN_COLOR: Record<number, number> = {
  0:  0x1a3a6e,
  1:  0x3a6db0,
  2:  0xe3d390,
  3:  0x5a8e3c,
  4:  0x2e6e2e,
  5:  0x1f4a1f,
  6:  0x7a6a45,
  7:  0x5a5550,
  8:  0x5a4a6e,
  9:  0x4a8ec0,
  10: 0x2a2a2a,
}

// ── 工具 ───────────────────────────────────────────────────────

export interface AnimState {
  fromX: number; fromY: number
  toX: number;   toY: number
  t0: number;    dur: number
}

// ── 主 composable ──────────────────────────────────────────────
export function useCanvas(
  containerEl: Ref<HTMLElement | null>,
  data: {
    mapInfo:    Ref<MapInfo | null>
    tiles:      Ref<Uint8Array | null>
    explored:   Ref<Uint8Array | null>
    gameState:  Ref<GameState | null>
  },
) {
  // ── Three 核心对象 ──
  let renderer: THREE.WebGLRenderer | null = null
  let scene:    THREE.Scene
  let camera:   THREE.OrthographicCamera
  let animFrameId = 0

  // ── 摄像机控制 ──
  let camAngleY  = Math.PI / 4    // 水平旋转（Y轴）
  const CAM_PITCH = Math.PI / 3.5  // 俯仰角（固定）
  let camZoom    = 12              // 正交相机 frustum 半宽（格数）
  let isDragging = false
  let dragLastX  = 0

  // ── 场景 mesh 缓存 ──
  const tileMeshes  = new Map<number, THREE.Mesh>()  // idx → terrain mesh
  const fogPlanes   = new Map<number, THREE.Mesh>()  // idx → fog overlay
  const objectGroup = new THREE.Group()              // 地标、建造物、动物、玩家

  // ── 走路动画 ──
  const anim: AnimState = { fromX: 0, fromY: 0, toX: 0, toY: 0, t0: 0, dur: 1 }
  const STEP_MS     = 500
  const RUN_STEP_MS = 220

  function setAnim(fromX: number, fromY: number, toX: number, toY: number, dur: number) {
    Object.assign(anim, { fromX, fromY, toX, toY, t0: performance.now(), dur })
  }
  function syncAnim(x: number, y: number) {
    setAnim(x, y, x, y, 1)
  }

  // ── 初始化 ──────────────────────────────────────────────────
  function init() {
    const container = containerEl.value
    if (!container) return

    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false })
    renderer.setPixelRatio(window.devicePixelRatio)
    renderer.shadowMap.enabled = true
    renderer.shadowMap.type = THREE.PCFSoftShadowMap
    renderer.setSize(container.clientWidth, container.clientHeight)
    container.appendChild(renderer.domElement)

    scene = new THREE.Scene()
    scene.background = new THREE.Color(0x0a0a14)
    scene.fog = new THREE.Fog(0x0a0a14, 30, 60)

    // 正交相机
    const aspect = container.clientWidth / container.clientHeight
    camera = new THREE.OrthographicCamera(
      -camZoom * aspect, camZoom * aspect,
      camZoom, -camZoom,
      0.1, 200,
    )
    updateCameraPosition(0, 0)

    // 光照
    const ambient = new THREE.AmbientLight(0xffffff, 0.6)
    scene.add(ambient)
    const sun = new THREE.DirectionalLight(0xfff5e0, 1.2)
    sun.position.set(10, 20, 10)
    sun.castShadow = true
    sun.shadow.mapSize.set(2048, 2048)
    sun.shadow.camera.near = 0.5
    sun.shadow.camera.far = 100
    sun.shadow.camera.left = -30
    sun.shadow.camera.right = 30
    sun.shadow.camera.top = 30
    sun.shadow.camera.bottom = -30
    scene.add(sun)

    scene.add(objectGroup)

    // 鼠标/触摸旋转
    const el = renderer.domElement
    el.addEventListener('mousedown', onMouseDown)
    el.addEventListener('mousemove', onMouseMove)
    el.addEventListener('mouseup',   onMouseUp)
    el.addEventListener('mouseleave', onMouseUp)
    el.addEventListener('wheel',     onWheel, { passive: true })

    startRenderLoop()
  }

  // ── 相机位置 ────────────────────────────────────────────────
  function updateCameraPosition(cx: number, cy: number) {
    const dist = 30
    camera.position.set(
      cx + dist * Math.sin(camAngleY) * Math.cos(CAM_PITCH),
      dist * Math.sin(CAM_PITCH),
      cy + dist * Math.cos(camAngleY) * Math.cos(CAM_PITCH),
    )
    camera.lookAt(cx, 0, cy)
    camera.up.set(0, 1, 0)
  }

  function updateCameraFrustum() {
    const container = containerEl.value
    if (!container) return
    const aspect = container.clientWidth / container.clientHeight
    camera.left   = -camZoom * aspect
    camera.right  =  camZoom * aspect
    camera.top    =  camZoom
    camera.bottom = -camZoom
    camera.updateProjectionMatrix()
  }

  // ── 地形网格构建（全量，首次或 reset 后调用）───────────────────
  function buildTerrain() {
    const mi = data.mapInfo.value
    const tl = data.tiles.value
    if (!mi || !tl) return

    // 清旧网格
    tileMeshes.forEach(m => scene.remove(m))
    fogPlanes.forEach(m => scene.remove(m))
    tileMeshes.clear()
    fogPlanes.clear()

    const TILE = 1.0  // 每格世界单位

    for (let y = 0; y < mi.height; y++) {
      for (let x = 0; x < mi.width; x++) {
        const idx = y * mi.width + x
        const t   = tl[idx]
        const h   = TERRAIN_HEIGHT[t] ?? 0.15

        const geo = new THREE.BoxGeometry(TILE, h + 0.01, TILE)
        const mat = new THREE.MeshLambertMaterial({ color: TERRAIN_COLOR[t] ?? 0x444444 })
        const mesh = new THREE.Mesh(geo, mat)
        mesh.position.set(x, (h) / 2, y)
        mesh.receiveShadow = true
        mesh.castShadow = false
        scene.add(mesh)
        tileMeshes.set(idx, mesh)

        // 迷雾覆盖层（初始全黑）
        const fogGeo = new THREE.PlaneGeometry(TILE, TILE)
        const fogMat = new THREE.MeshBasicMaterial({
          color: 0x000000, transparent: true, opacity: 1.0,
          depthWrite: false,
        })
        const fogPlane = new THREE.Mesh(fogGeo, fogMat)
        fogPlane.rotation.x = -Math.PI / 2
        fogPlane.position.set(x, h + 0.02, y)
        scene.add(fogPlane)
        fogPlanes.set(idx, fogPlane)
      }
    }
  }

  // ── 迷雾更新（每帧或 explored 变化时）────────────────────────
  function updateFog() {
    const mi = data.mapInfo.value
    const ex = data.explored.value
    const tl = data.tiles.value
    if (!mi || !ex || !tl) return

    fogPlanes.forEach((plane, idx) => {
      const expl = ex[idx]
      const mat  = plane.material as THREE.MeshBasicMaterial
      if (expl === 0) {
        mat.opacity = 1.0; mat.visible = true
      } else if (expl === 1) {
        mat.opacity = 0.55; mat.visible = true
      } else {
        mat.opacity = 0;   mat.visible = false
      }
    })
  }

  // ── 动态物体（地标、建造物、动物、玩家）────────────────────────
  function rebuildObjects() {
    objectGroup.clear()

    const mi = data.mapInfo.value
    const gs = data.gameState.value
    const tl = data.tiles.value
    if (!mi || !gs || !tl) return

    const tileH = (x: number, y: number) => {
      const idx = y * mi.width + x
      const t = tl[idx] ?? 0
      return TERRAIN_HEIGHT[t] ?? 0.15
    }

    // ── 地标 ──
    const LM_COLOR: Record<string, number> = {
      wreck: 0x8a7060, fresh_spring: 0x60aacc, coconut_grove: 0x3a8a3a,
      cliff_top: 0x888888, abandoned_camp: 0x706050, cave: 0x443344,
      default: 0xaaaaaa,
    }
    for (const lm of mi.landmarks) {
      const h = tileH(lm.x, lm.y)
      const c = LM_COLOR[lm.id] ?? LM_COLOR.default
      const geo = new THREE.CylinderGeometry(0.25, 0.35, 0.5, 6)
      const mat = new THREE.MeshLambertMaterial({ color: c })
      const mesh = new THREE.Mesh(geo, mat)
      mesh.position.set(lm.x, h + 0.3, lm.y)
      mesh.castShadow = true
      objectGroup.add(mesh)
    }

    // ── 建造物 ──
    const BUILT_COLOR: Record<string, number> = {
      fire: 0xff6020, shelter: 0xa08060, storage: 0x806040, default: 0x888888,
    }
    for (const b of gs.builtThings) {
      const h = tileH(b.x, b.y)
      const tag = b.tags?.[0] ?? 'default'
      const c = BUILT_COLOR[tag] ?? BUILT_COLOR.default
      const geo = new THREE.BoxGeometry(0.5, 0.4, 0.5)
      const mat = new THREE.MeshLambertMaterial({ color: c })
      const mesh = new THREE.Mesh(geo, mat)
      mesh.position.set(b.x, h + 0.22, b.y)
      mesh.castShadow = true
      objectGroup.add(mesh)

      // 火堆额外加点光
      if (tag === 'fire') {
        const light = new THREE.PointLight(0xff6020, 2, 4)
        light.position.set(b.x, h + 0.8, b.y)
        objectGroup.add(light)
      }
    }

    // ── 动物 ──
    const ANIMAL_COLOR: Record<string, number> = {
      parrot: 0x22aa44, monkey: 0x996633, dog: 0xaa8855,
    }
    for (const a of gs.animalsNear) {
      const h = tileH(a.x, a.y)
      const c = ANIMAL_COLOR[a.species] ?? 0x888888
      const body = new THREE.CylinderGeometry(0.18, 0.18, 0.3, 8)
      const mat  = new THREE.MeshLambertMaterial({ color: c })
      const mesh = new THREE.Mesh(body, mat)
      mesh.position.set(a.x, h + 0.18, a.y)
      mesh.castShadow = true
      objectGroup.add(mesh)
    }
  }

  // ── 玩家 mesh（单独跟踪以便每帧插值）──────────────────────────
  let playerMesh: THREE.Mesh | null = null

  function ensurePlayer() {
    if (playerMesh) return
    const geo = new THREE.CylinderGeometry(0.2, 0.2, 0.45, 10)
    const mat = new THREE.MeshLambertMaterial({ color: 0x84a8ff })
    playerMesh = new THREE.Mesh(geo, mat)
    playerMesh.castShadow = true
    scene.add(playerMesh)
  }

  function updatePlayer(px: number, py: number) {
    ensurePlayer()
    if (!playerMesh || !data.tiles.value || !data.mapInfo.value) return
    const idx = Math.round(py) * data.mapInfo.value.width + Math.round(px)
    const t = data.tiles.value[idx] ?? 0
    const h = TERRAIN_HEIGHT[t] ?? 0.15
    playerMesh.position.set(px, h + 0.25, py)
  }

  // ── 渲染循环 ────────────────────────────────────────────────
  function startRenderLoop() {
    function loop() {
      animFrameId = requestAnimationFrame(loop)

      // 走路动画插值
      const elapsed = performance.now() - anim.t0
      const p = Math.min(1, elapsed / anim.dur)
      const e = p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2
      const cx = anim.fromX + (anim.toX - anim.fromX) * e
      const cy = anim.fromY + (anim.toY - anim.fromY) * e

      updatePlayer(cx, cy)
      updateCameraPosition(cx, cy)
      updateFog()

      renderer!.render(scene, camera)
    }
    loop()
  }

  // ── resize ──────────────────────────────────────────────────
  function resize() {
    const container = containerEl.value
    if (!container || !renderer) return
    renderer.setSize(container.clientWidth, container.clientHeight)
    updateCameraFrustum()
  }

  // ── 鼠标控制 ────────────────────────────────────────────────
  function onMouseDown(e: MouseEvent) {
    if (e.button !== 0) return
    isDragging = true; dragLastX = e.clientX
  }
  function onMouseMove(e: MouseEvent) {
    if (!isDragging) return
    const dx = e.clientX - dragLastX
    camAngleY -= dx * 0.01
    dragLastX = e.clientX
  }
  function onMouseUp()   { isDragging = false }
  function onWheel(e: WheelEvent) {
    camZoom = Math.max(4, Math.min(25, camZoom + e.deltaY * 0.02))
    updateCameraFrustum()
  }

  // ── 清理 ────────────────────────────────────────────────────
  function dispose() {
    cancelAnimationFrame(animFrameId)
    const el = renderer?.domElement
    if (el) {
      el.removeEventListener('mousedown', onMouseDown)
      el.removeEventListener('mousemove', onMouseMove)
      el.removeEventListener('mouseup',   onMouseUp)
      el.removeEventListener('mouseleave', onMouseUp)
      el.removeEventListener('wheel',     onWheel)
    }
    renderer?.dispose()
    renderer = null
  }

  // draw / rebuild 供外部调用（和旧 API 兼容）
  function draw() { /* 渲染循环已自驱，外部调用为空操作 */ }

  return {
    anim, setAnim, syncAnim,
    resize, draw, dispose,
    init, buildTerrain, rebuildObjects,
    STEP_MS, RUN_STEP_MS,
  }
}
