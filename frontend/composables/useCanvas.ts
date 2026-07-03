/**
 * Three.js 渲染 —— FPS 第一人称 + AoE4 风格地图。
 *
 * 架构：
 * - 地形：每格 BoxGeometry tile（PBR StandardMaterial），上面按地形类型
 *   散布装饰模型（树/石/草）
 * - 动态物体（建造物/动物/玩家）：单独 Group
 * - 迷雾：每格半透明黑色 Plane，explored 值决定透明度
 * - 摄像机：FPS 第一人称，Pointer Lock 鼠标控制视角
 */

import * as THREE from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import type { Ref } from 'vue'
import type { MapInfo, GameState, TileOverride } from '../stores/game'

// ── 路径前缀 ────────────────────────────────────────────────────
const K = '/assets/kenney_nature-kit/Models/GLTF format/'
const CHAR_PATH = '/assets/blocky_characters/GLB format/'

// ── 地形配置 ────────────────────────────────────────────────────
interface TerrainCfg {
  baseColor: number      // AoE4 自然色系
  baseH: number          // 格子高度
  decorations: [string, number, number, number][]
}

// AoE4 自然调色板：暖色、柔和、低饱和度
const TERRAIN_CFG: Record<number, TerrainCfg> = {
  0:  { baseColor: 0x2a4a8a, baseH: 0.05, decorations: [] },                          // OCEAN 深蓝
  1:  { baseColor: 0x3a7ab0, baseH: 0.06, decorations: [] },                          // SHALLOW_WATER 透亮浅蓝
  2:  { // BEACH
    baseColor: 0xd4c5a0, baseH: 0.1,
    decorations: [
      ['rock_smallA.glb', 0.04, 0.8, 0],
      ['rock_smallB.glb', 0.03, 0.7, 0],
    ],
  },
  3:  { // GRASS
    baseColor: 0x6b8e3a, baseH: 0.12,
    decorations: [
      ['grass.glb',       0.10, 1.0, 0],
      ['grass_large.glb', 0.03, 0.9, 0],
      ['flower_redA.glb', 0.02, 0.9, 0],
    ],
  },
  4:  { // JUNGLE
    baseColor: 0x3a5a2a, baseH: 0.12,
    decorations: [
      ['tree_default.glb',   0.08, 1.0, 0],
      ['tree_small.glb',     0.06, 0.9, 0],
      ['tree_palmShort.glb', 0.05, 1.0, 0],
      ['grass_leafs.glb',    0.10, 1.0, 0],
    ],
  },
  5:  { // DEEP_JUNGLE
    baseColor: 0x2a4a1a, baseH: 0.12,
    decorations: [
      ['tree_tall_dark.glb',  0.10, 1.1, 0],
      ['tree_thin_dark.glb',  0.08, 1.0, 0],
      ['tree_default_dark.glb', 0.06, 1.0, 0],
      ['stump_old.glb',       0.03, 0.8, 0],
    ],
  },
  6:  { // HILLS
    baseColor: 0x8a7a5a, baseH: 0.18,
    decorations: [
      ['rock_largeA.glb', 0.05, 0.8, 0],
      ['rock_largeB.glb', 0.04, 0.7, 0],
      ['tree_small.glb',  0.05, 0.9, 0],
    ],
  },
  7:  { // MOUNTAIN
    baseColor: 0x6a6555, baseH: 0.28,
    decorations: [
      ['rock_largeC.glb', 0.08, 0.9, 0],
      ['rock_largeD.glb', 0.06, 1.0, 0],
      ['cliff_rock.glb',  0.03, 0.6, 0],
    ],
  },
  8:  { // SWAMP
    baseColor: 0x4a4a32, baseH: 0.08,
    decorations: [
      ['stump_old.glb',     0.06, 0.9, 0],
      ['stump_round.glb',   0.04, 0.7, 0],
      ['grass_leafs.glb',   0.08, 0.8, 0],
    ],
  },
  9:  { // RIVER
    baseColor: 0x5a9ac0, baseH: 0.06,
    decorations: [],
  },
  10: { // CLIFF
    baseColor: 0x5a5050, baseH: 0.35,
    decorations: [
      ['cliff_rock.glb',  0.12, 0.8, 0],
      ['rock_largeF.glb', 0.06, 0.9, 0],
    ],
  },
}

// ── 建造物模型 ──────────────────────────────────────────────────
const BUILT_MODEL: Record<string, [string, number]> = {
  fire:    ['campfire_stones.glb', 0.7],
  shelter: ['fence_simple.glb',   1.0],
  storage: ['stump_squareDetailed.glb', 0.8],
  default: ['rock_smallTopA.glb', 0.6],
}

// ── 动画状态 ────────────────────────────────────────────────────
export interface AnimState {
  fromX: number; fromY: number
  toX: number;   toY: number
  t0: number;    dur: number
}

// ── seeded random ──────────────────────────────────────────────
function seededRand(seed: number): number {
  const x = Math.sin(seed) * 10000
  return x - Math.floor(x)
}

// 颜色微调：seeded HSV 偏移，让地表有自然纹理感
function varyColor(base: number, seed: number): number {
  const r = (base >> 16) & 0xff
  const g = (base >> 8) & 0xff
  const b = base & 0xff
  const v = 0.92 + seededRand(seed) * 0.16  // ±8%
  return (
    (Math.min(255, Math.round(r * v)) << 16) |
    (Math.min(255, Math.round(g * v)) << 8)  |
    Math.min(255, Math.round(b * v))
  )
}

// ── 主 composable ──────────────────────────────────────────────
export function useCanvas(
  containerEl: Ref<HTMLElement | null>,
  data: {
    mapInfo:   Ref<MapInfo | null>
    tiles:     Ref<Uint8Array | null>
    explored:  Ref<Uint8Array | null>
    gameState: Ref<GameState | null>
    tileOverrides: Ref<TileOverride[]>
  },
) {
  let renderer: THREE.WebGLRenderer | null = null
  let scene:    THREE.Scene
  let camera:   THREE.PerspectiveCamera
  let animFrameId = 0

  // ── 2D 俯视摄像机 ─────────────────────────────────────────────
  const CAM_FOV = 60
  let camHeight = 20          // 相机高度（滚轮缩放）
  let camOffsetX = 0          // 平移偏移
  let camOffsetZ = 0
  let isPanning = false
  let panStartX = 0
  let panStartY = 0

  // mesh 缓存
  const fogPlanes   = new Map<number, THREE.Mesh>()
  const objectGroup = new THREE.Group()
  let decorationMap: Map<number, THREE.Object3D[]> = new Map()
  let tileMeshMap:  Map<number, THREE.Mesh> = new Map()
  let playerMesh: THREE.Object3D | null = null

  // 动画
  const anim: AnimState = { fromX: 0, fromY: 0, toX: 0, toY: 0, t0: 0, dur: 1 }
  const STEP_MS     = 180
  const RUN_STEP_MS = 90
  let _lastPX = 0
  let _lastPY = 0

  function setAnim(fromX: number, fromY: number, toX: number, toY: number, dur: number) {
    Object.assign(anim, { fromX, fromY, toX, toY, t0: performance.now(), dur })
  }
  function syncAnim(x: number, y: number) { setAnim(x, y, x, y, 1) }

  // GLTF 缓存
  const loader = new GLTFLoader()
  const modelCache = new Map<string, THREE.Object3D>()

  async function loadModel(filename: string): Promise<THREE.Object3D> {
    if (modelCache.has(filename)) return modelCache.get(filename)!.clone()
    return new Promise((resolve, reject) => {
      loader.load(
        K + filename,
        (gltf) => {
          modelCache.set(filename, gltf.scene)
          resolve(gltf.scene.clone())
        },
        undefined,
        reject,
      )
    })
  }

  // ── 初始化 ────────────────────────────────────────────────────
  function init() {
    const container = containerEl.value
    if (!container) return

    renderer = new THREE.WebGLRenderer({ antialias: true })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.shadowMap.enabled = true
    renderer.shadowMap.type = THREE.PCFSoftShadowMap
    renderer.setSize(container.clientWidth, container.clientHeight)
    renderer.domElement.style.display = 'block'
    container.appendChild(renderer.domElement)

    scene = new THREE.Scene()
    // AoE4 天空色
    scene.background = new THREE.Color(0x87ceeb)
    // 天蓝色雾 —— 远景融入天空
    scene.fog = new THREE.Fog(0x87ceeb, 30, 100)

    const aspect = container.clientWidth / container.clientHeight
    camera = new THREE.PerspectiveCamera(CAM_FOV, aspect, 0.1, 500)
    updateCameraPose(0, 0)

    // ── AoE4 风格光照 ──────────────────────────────────────────
    // 半球光：天空蓝 + 地面棕，模拟自然散射
    const hemi = new THREE.HemisphereLight(0x87ceeb, 0x362907, 0.7)
    scene.add(hemi)

    // 环境光降低，让半球光主导
    const ambient = new THREE.AmbientLight(0xffffff, 0.5)
    scene.add(ambient)

    // 暖色太阳光
    const sun = new THREE.DirectionalLight(0xfff8e7, 1.6)
    sun.position.set(20, 35, 10)
    sun.castShadow = true
    sun.shadow.mapSize.set(2048, 2048)
    sun.shadow.camera.near = 0.5
    sun.shadow.camera.far = 120
    const sc = 50
    sun.shadow.camera.left = -sc; sun.shadow.camera.right = sc
    sun.shadow.camera.top  =  sc; sun.shadow.camera.bottom = -sc
    scene.add(sun)

    scene.add(objectGroup)

    // ── 鼠标：左键平移，滚轮缩放 ──────────────────────────────
    const el = renderer.domElement
    el.addEventListener('mousedown', onMouseDown)
    el.addEventListener('mousemove', onMouseMove)
    el.addEventListener('mouseup', onMouseUp)
    el.addEventListener('contextmenu', e => e.preventDefault())
    el.addEventListener('wheel', onWheel, { passive: true })

    startRenderLoop()
  }

  // ── 2D 俯视摄像机位置 ────────────────────────────────────────
  function updateCameraPose(px: number, py: number) {
    const mi = data.mapInfo.value
    const c = containerEl.value
    let tx = px + camOffsetX
    let ty = py + camOffsetZ

    // 边界限定
    if (mi && c) {
      const vh = 2 * camHeight * Math.tan((CAM_FOV / 2) * Math.PI / 180)
      const vw = vh * (c.clientWidth / c.clientHeight)
      tx = Math.max(vw / 2, Math.min(mi.width - vw / 2, tx))
      ty = Math.max(vh / 2, Math.min(mi.height - vh / 2, ty))
    }

    camera.position.set(tx, camHeight, ty)
    camera.lookAt(tx, 0, ty)
  }

  function updateFrustum() {
    const c = containerEl.value
    if (!c || !renderer) return
    camera.aspect = c.clientWidth / c.clientHeight
    camera.updateProjectionMatrix()
  }

  // ── 鼠标控制：左键平移，滚轮缩放 ──────────────────────────
  function onMouseDown(e: MouseEvent) {
    if (e.button === 0) {
      isPanning = true
      panStartX = e.clientX
      panStartY = e.clientY
    }
  }
  function onMouseMove(e: MouseEvent) {
    if (!isPanning || !containerEl.value) return
    const vh = 2 * CAM_HEIGHT * Math.tan((CAM_FOV / 2) * Math.PI / 180)
    const pxPerUnit = containerEl.value.clientHeight / vh
    camOffsetX -= (e.clientX - panStartX) / pxPerUnit
    camOffsetZ -= (e.clientY - panStartY) / pxPerUnit
    panStartX = e.clientX
    panStartY = e.clientY
  }
  function onMouseUp() { isPanning = false }
  function onWheel(e: WheelEvent) {
    camHeight = Math.max(5, Math.min(80, camHeight + e.deltaY * 0.3))
  }

  // ── 地形构建 ──────────────────────────────────────────────────
  async function buildTerrain() {
    const mi = data.mapInfo.value
    const tl = data.tiles.value
    if (!mi || !tl) return

    fogPlanes.forEach(m => scene.remove(m))
    fogPlanes.clear()
    const oldGrp = scene.getObjectByName('terrainGroup')
    if (oldGrp) scene.remove(oldGrp)

    const terrainGroup = new THREE.Group()
    terrainGroup.name = 'terrainGroup'
    scene.add(terrainGroup)

    const decorationGroup = new THREE.Group()
    decorationGroup.name = 'decorationGroup'
    terrainGroup.add(decorationGroup)

    // 重置追踪 map
    decorationMap = new Map()
    tileMeshMap = new Map()

    const TILE = 1.0

    for (let y = 0; y < mi.height; y++) {
      for (let x = 0; x < mi.width; x++) {
        const idx = y * mi.width + x
        const t   = tl[idx]
        const cfg = TERRAIN_CFG[t] ?? TERRAIN_CFG[3]

        // AoE4 PBR 地表（含轻微色彩变化）
        const geo = new THREE.BoxGeometry(TILE, cfg.baseH, TILE)
        const color = varyColor(cfg.baseColor, idx)
        const mat = new THREE.MeshStandardMaterial({
          color,
          roughness: 0.9,
          metalness: 0.05,
        })
        const mesh = new THREE.Mesh(geo, mat)
        mesh.position.set(x, cfg.baseH / 2, y)
        mesh.receiveShadow = true
        terrainGroup.add(mesh)
        tileMeshMap.set(idx, mesh)

        // 迷雾覆盖层
        const fogGeo = new THREE.PlaneGeometry(TILE * 0.99, TILE * 0.99)
        const fogMat = new THREE.MeshBasicMaterial({
          color: 0x000000, transparent: true, opacity: 1.0,
          depthWrite: false,
        })
        const fog = new THREE.Mesh(fogGeo, fogMat)
        fog.rotation.x = -Math.PI / 2
        fog.position.set(x, cfg.baseH + 0.01, y)
        fog.renderOrder = 1
        scene.add(fog)
        fogPlanes.set(idx, fog)
      }
    }

    // 异步加载装饰模型
    const BATCH = 120
    let i = 0
    const tasks: { x: number; y: number; t: number; cfg: TerrainCfg }[] = []
    for (let y = 0; y < mi.height; y++) {
      for (let x = 0; x < mi.width; x++) {
        const t = tl[y * mi.width + x]
        const cfg = TERRAIN_CFG[t] ?? TERRAIN_CFG[3]
        if (cfg.decorations.length) tasks.push({ x, y, t, cfg })
      }
    }

    async function processBatch() {
      const end = Math.min(i + BATCH, tasks.length)
      const mapW = mi!.width
      for (; i < end; i++) {
        const { x, y, cfg } = tasks[i]
        const seed = y * mapW + x
        for (let d = 0; d < cfg.decorations.length; d++) {
          const [file, prob, scale, yOff] = cfg.decorations[d]
          const r = seededRand(seed * 31 + d * 7)
          if (r > prob) continue
          try {
            const obj = await loadModel(file)
            const ox = (seededRand(seed * 13 + d) - 0.5) * 0.7
            const oz = (seededRand(seed * 17 + d) - 0.5) * 0.7
            const rot = seededRand(seed * 19 + d) * Math.PI * 2
            const h = cfg.baseH
            obj.position.set(x + ox, h + yOff, y + oz)
            obj.rotation.y = rot
            obj.scale.setScalar(scale)
            obj.traverse(c => { if ((c as THREE.Mesh).isMesh) { c.castShadow = true; c.receiveShadow = true } })
            obj.userData.isTree = true  // 树木标记为可交互实体
            decorationGroup.add(obj)
            // 追踪该格的装饰物
            if (!decorationMap.has(seed)) decorationMap.set(seed, [])
            decorationMap.get(seed)!.push(obj)
          } catch { /* 静默 */ }
        }
      }
      if (i < tasks.length) {
        await new Promise(r => setTimeout(r, 0))
        await processBatch()
      }
    }
    processBatch()
  }

  // ── 迷雾更新 ──────────────────────────────────────────────────
  let debugFogOff = false

  function updateFog() {
    const ex = data.explored.value
    if (!ex) return
    if (debugFogOff) {
      fogPlanes.forEach(plane => {
        const mat = plane.material as THREE.MeshBasicMaterial
        mat.opacity = 0; mat.visible = false
      })
      return
    }
    fogPlanes.forEach((plane, idx) => {
      const mat = plane.material as THREE.MeshBasicMaterial
      const expl = ex[idx]
      if (expl === 0)      { mat.opacity = 1.0; mat.visible = true  }
      else if (expl === 1) { mat.opacity = 0.35; mat.visible = true  }
      else                 { mat.opacity = 0;    mat.visible = false }
    })
  }

  function toggleDebugFog() { debugFogOff = !debugFogOff; updateFog() }

  // ── 动态物体 ──────────────────────────────────────────────────

  async function ensurePlayerMesh() {
    if (playerMesh) return
    try {
      const obj = await new Promise<THREE.Object3D>((resolve, reject) => {
        loader.load(CHAR_PATH + 'character-a.glb', (gltf) => resolve(gltf.scene), undefined, reject)
      })
      obj.scale.setScalar(0.35)
      obj.traverse((c) => { if ((c as THREE.Mesh).isMesh) c.castShadow = true })
      playerMesh = obj
      objectGroup.add(playerMesh)
    } catch {
      if (!playerMesh) {
        const geo = new THREE.SphereGeometry(0.15, 10, 8)
        const mesh = new THREE.Mesh(geo, new THREE.MeshToonMaterial({ color: 0x84a8ff }))
        mesh.castShadow = true
        playerMesh = mesh
        objectGroup.add(playerMesh)
      }
    }
  }

  async function rebuildObjects() {
    const mi = data.mapInfo.value
    const tl = data.tiles.value
    if (!mi || !tl) return

    const toRemove: THREE.Object3D[] = []
    objectGroup.children.forEach(c => { if (c !== playerMesh) toRemove.push(c) })
    toRemove.forEach(c => objectGroup.remove(c))

    const tileH = (x: number, y: number) => {
      const t = tl[Math.round(y) * mi.width + Math.round(x)] ?? 3
      return (TERRAIN_CFG[t] ?? TERRAIN_CFG[3]).baseH
    }

    const LM_MODEL: Record<string, [string, number]> = {
      wreck:               ['canoe.glb',              0.9],
      fresh_spring:        ['ground_riverTile.glb',   1.0],
      coconut_grove:       ['tree_palmDetailedTall.glb', 1.2],
      rocky_beach:         ['rock_largeB.glb',        1.0],
      cliff_top:           ['cliff_rock.glb',         1.1],
      abandoned_camp:      ['campfire_logs.glb',      0.9],
      cave:                ['cliff_blockCave_rock.glb', 0.8],
      mangrove:            ['tree_default_dark.glb',  1.0],
      lookout_hill:        ['rock_largeA.glb',        0.9],
      deep_jungle_clearing:['stump_oldTall.glb',      1.0],
      shipwreck_far:       ['canoe.glb',              1.1],
      message_in_bottle:   ['rock_smallTopA.glb',     0.7],
      bone_pile:           ['stump_old.glb',          0.6],
      banana_grove:        ['tree_palmShort.glb',     1.1],
      tide_pool:           ['rock_smallFlatA.glb',    0.9],
      old_tree:            ['tree_fat.glb',           1.2],
      cliff_shelter:       ['cliff_block_rock.glb',   0.9],
      salt_flat:           ['ground_pathTile.glb',    1.0],
      fire_pit:            ['campfire_stones.glb',    0.8],
      cliff_path:          ['cliff_blockSlope_rock.glb', 0.8],
    }

    for (const lm of mi.landmarks) {
      const [file, scale] = LM_MODEL[lm.id] ?? ['rock_smallA.glb', 0.7]
      try {
        const obj = await loadModel(file)
        const h = tileH(lm.x, lm.y)
        obj.position.set(lm.x, h, lm.y)
        obj.scale.setScalar(scale)
        obj.traverse(c => { if ((c as THREE.Mesh).isMesh) c.castShadow = true })
        obj.userData.isLandmark = true
        objectGroup.add(obj)
      } catch { /* 静默 */ }
    }

    const gs = data.gameState.value
    if (gs) {
      for (const b of gs.builtThings) {
        const tag = b.tags?.[0] ?? 'default'
        const [file, scale] = BUILT_MODEL[tag] ?? BUILT_MODEL.default
        try {
          const obj = await loadModel(file)
          const h = tileH(b.x, b.y)
          obj.position.set(b.x, h, b.y)
          obj.scale.setScalar(scale)
          obj.traverse(c => { if ((c as THREE.Mesh).isMesh) c.castShadow = true })
          objectGroup.add(obj)
          if (tag === 'fire') {
            const light = new THREE.PointLight(0xff7020, 3, 5, 2)
            light.position.set(b.x, h + 0.8, b.y)
            objectGroup.add(light)
          }
        } catch { /* 静默 */ }
      }

      const ANIMAL_COLOR: Record<string, number> = {
        parrot: 0x22cc44, monkey: 0xaa7733, dog: 0xcc9966,
      }
      for (const a of gs.animalsNear) {
        const h = tileH(a.x, a.y)
        const geo = new THREE.SphereGeometry(0.22, 8, 6)
        const mat2 = new THREE.MeshToonMaterial({ color: ANIMAL_COLOR[a.species] ?? 0x888888 })
        const mesh = new THREE.Mesh(geo, mat2)
        mesh.position.set(a.x, h + 0.22, a.y)
        mesh.castShadow = true
        objectGroup.add(mesh)
      }
    }
  }

  async function rebuildDynamicObjects() {
    const gs = data.gameState.value
    const tl = data.tiles.value
    const mi = data.mapInfo.value
    if (!gs || !tl || !mi) return

    const tileH = (x: number, y: number) => {
      const t = tl[Math.round(y) * mi.width + Math.round(x)] ?? 3
      return (TERRAIN_CFG[t] ?? TERRAIN_CFG[3]).baseH
    }

    const toRemove: THREE.Object3D[] = []
    objectGroup.children.forEach(c => {
      if (c !== playerMesh && !(c.userData?.isLandmark)) toRemove.push(c)
    })
    toRemove.forEach(c => objectGroup.remove(c))

    for (const b of gs.builtThings) {
      const tag = b.tags?.[0] ?? 'default'
      const [file, scale] = BUILT_MODEL[tag] ?? BUILT_MODEL.default
      try {
        const obj = await loadModel(file)
        const h = tileH(b.x, b.y)
        obj.position.set(b.x, h, b.y)
        obj.scale.setScalar(scale)
        obj.traverse(c => { if ((c as THREE.Mesh).isMesh) c.castShadow = true })
        objectGroup.add(obj)
        if (tag === 'fire') {
          const light = new THREE.PointLight(0xff7020, 3, 5, 2)
          light.position.set(b.x, h + 0.8, b.y)
          objectGroup.add(light)
        }
      } catch { /* skip */ }
    }

    const ANIMAL_COLOR: Record<string, number> = {
      parrot: 0x22cc44, monkey: 0xaa7733, dog: 0xcc9966,
    }
    for (const a of gs.animalsNear) {
      const h = tileH(a.x, a.y)
      const geo = new THREE.SphereGeometry(0.22, 8, 6)
      const mat2 = new THREE.MeshToonMaterial({ color: ANIMAL_COLOR[a.species] ?? 0x888888 })
      const mesh = new THREE.Mesh(geo, mat2)
      mesh.position.set(a.x, h + 0.22, a.y)
      mesh.castShadow = true
      objectGroup.add(mesh)
    }
  }

  function updatePlayerPos(px: number, py: number) {
    if (!playerMesh || !data.tiles.value || !data.mapInfo.value) return
    const t = data.tiles.value[Math.round(py) * data.mapInfo.value.width + Math.round(px)] ?? 3
    const h = (TERRAIN_CFG[t] ?? TERRAIN_CFG[3]).baseH
    playerMesh.position.set(px, h, py)
  }

  // ── 渲染循环 ──────────────────────────────────────────────────
  function startRenderLoop() {
    function loop() {
      animFrameId = requestAnimationFrame(loop)
      const elapsed = performance.now() - anim.t0
      const p = Math.min(1, elapsed / anim.dur)
      const e = p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2
      const cx = anim.fromX + (anim.toX - anim.fromX) * e
      const cy = anim.fromY + (anim.toY - anim.fromY) * e
      _lastPX = cx; _lastPY = cy
      updatePlayerPos(cx, cy)
      updateCameraPose(cx, cy)
      updateFog()
      renderer!.render(scene, camera)
    }
    loop()
  }

  // ── resize ────────────────────────────────────────────────────
  function resize() {
    const c = containerEl.value
    if (!c || !renderer) return
    const w = c.clientWidth
    const h = c.clientHeight
    if (w === 0 || h === 0) return
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.setSize(w, h)
    updateFrustum()
  }

  // ── 清理 ──────────────────────────────────────────────────────
  function dispose() {
    cancelAnimationFrame(animFrameId)
    const el = renderer?.domElement
    if (el) {
      el.removeEventListener('mousedown', onMouseDown)
      el.removeEventListener('mousemove', onMouseMove)
      el.removeEventListener('mouseup', onMouseUp)
      el.removeEventListener('contextmenu', e => e.preventDefault())
      el.removeEventListener('wheel', onWheel)
    }
    renderer?.dispose()
    renderer = null
    modelCache.clear()
  }

  function updateTileOverrides() {
    const ovs = data.tileOverrides.value
    const mi = data.mapInfo.value
    if (!ovs?.length || !mi) return
    for (const ov of ovs) {
      const idx = ov.y * mi.width + ov.x
      // 1. 移除该格的装饰物（树等）
      const decos = decorationMap.get(idx)
      if (decos) {
        const decoGrp = scene.getObjectByName('decorationGroup')
        if (decoGrp) {
          decos.forEach(d => decoGrp.remove(d))
        }
        decorationMap.delete(idx)
      }
      // 2. 更新地块颜色
      const tileMesh = tileMeshMap.get(idx)
      if (tileMesh) {
        const cfg = TERRAIN_CFG[ov.terrain] ?? TERRAIN_CFG[3]
        const color = varyColor(cfg.baseColor, idx)
        ;(tileMesh.material as THREE.MeshStandardMaterial).color.set(color)
        // 同时更新高度
        tileMesh.scale.y = cfg.baseH / ((TERRAIN_CFG[tiles.value?.[idx] ?? 3] ?? TERRAIN_CFG[3]).baseH || 0.12)
        tileMesh.position.y = cfg.baseH / 2
      }
    }
  }

  function draw() {}

  return {
    anim, setAnim, syncAnim,
    resize, draw, dispose,
    init, buildTerrain, rebuildObjects, rebuildDynamicObjects, ensurePlayerMesh,
    updateTileOverrides,
    STEP_MS, RUN_STEP_MS,
    toggleDebugFog,
  }
}
