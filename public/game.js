// SurvivalSands web client.
// 渲染：把整个岛画到一张大 canvas，再用 transform 把"以玩家为中心"的视野显示出来。
// 移动：WASD 触发"走一步"，每步在画面上平滑滑动 STEP_MS 毫秒，再 ack 给服务端。
// 输入框：回车 → /api/action（自由动作判定）

const TILE_SIZE = 40;          // 每格像素
const STEP_MS = 500;           // 走一格的动画时长（毫秒）— 约 2 格/秒，散步速度
const RUN_STEP_MS = 220;       // 按住 Shift 跑的速度

// 地形 enum 必须和后端 src/terrain.ts 一致
const Terrain = {
  Ocean: 0, ShallowWater: 1, Beach: 2, Grass: 3, Jungle: 4,
  DeepJungle: 5, Hills: 6, Mountain: 7, Swamp: 8, River: 9, Cliff: 10,
};

const TERRAIN_COLOR = {
  [Terrain.Ocean]:        '#1a3a6e',
  [Terrain.ShallowWater]: '#3a6db0',
  [Terrain.Beach]:        '#e3d390',
  [Terrain.Grass]:        '#5a8e3c',
  [Terrain.Jungle]:       '#2e6e2e',
  [Terrain.DeepJungle]:   '#1f4a1f',
  [Terrain.Hills]:        '#7a6a45',
  [Terrain.Mountain]:     '#5a5550',
  [Terrain.Swamp]:        '#5a4a6e',
  [Terrain.River]:        '#4a8ec0',
  [Terrain.Cliff]:        '#2a2a2a',
};

const TERRAIN_NAME = {
  [Terrain.Ocean]: '深海', [Terrain.ShallowWater]: '浅滩', [Terrain.Beach]: '沙滩',
  [Terrain.Grass]: '草地', [Terrain.Jungle]: '丛林', [Terrain.DeepJungle]: '密林',
  [Terrain.Hills]: '丘陵', [Terrain.Mountain]: '山地', [Terrain.Swamp]: '沼泽',
  [Terrain.River]: '河流', [Terrain.Cliff]: '悬崖',
};

const $ = (sel) => document.querySelector(sel);

const canvas = $('#map');
const ctx = canvas.getContext('2d');

let mapInfo = null;     // { width, height, tilesB64, landmarks, exploredB64 }
let tiles = null;       // Uint8Array
let explored = null;    // Uint8Array
let state = null;       // /api/state 返回值
let busy = false;       // 防止 LLM 调用并发

// 走路动画状态：玩家从 (fromX,fromY) 滑向 (toX,toY)，进度 0..1
// 服务端 player 始终是"目标格"；动画只是 UI 平滑，不影响逻辑。
let anim = { fromX: 0, fromY: 0, toX: 0, toY: 0, t0: 0, dur: STEP_MS };
let stepInFlight = false;
const moveQueue = []; // 一次按住按键，按节奏一格一格地执行

// 日志面板
function logEntry(html, cls = '') {
  const log = $('#log');
  const div = document.createElement('div');
  div.className = 'entry ' + cls;
  div.innerHTML = html;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

// === 渲染 ===
function resizeCanvas() {
  const wrap = $('#map-wrap');
  canvas.width = wrap.clientWidth;
  canvas.height = wrap.clientHeight;
  draw();
}
window.addEventListener('resize', resizeCanvas);

function draw() {
  if (!mapInfo || !state) return;
  const W = canvas.width;
  const H = canvas.height;
  ctx.fillStyle = '#000';
  ctx.fillRect(0, 0, W, H);

  // 相机：以"玩家正在前往的目标格"为锚点，但应用 0..1 的滑动进度
  const elapsed = performance.now() - anim.t0;
  const p = Math.min(1, elapsed / anim.dur);
  // easeInOutQuad，让起步与到位略缓，更像走路
  const e = p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2;
  const px = anim.fromX + (anim.toX - anim.fromX) * e;
  const py = anim.fromY + (anim.toY - anim.fromY) * e;

  const cx = Math.floor(W / 2);
  const cy = Math.floor(H / 2);
  // 视野范围（多渲染一圈避免边缘空白）
  const viewCols = Math.ceil(W / TILE_SIZE) + 2;
  const viewRows = Math.ceil(H / TILE_SIZE) + 2;
  const x0 = Math.floor(px) - Math.floor(viewCols / 2);
  const y0 = Math.floor(py) - Math.floor(viewRows / 2);

  for (let dy = 0; dy <= viewRows; dy++) {
    for (let dx = 0; dx <= viewCols; dx++) {
      const wx = x0 + dx;
      const wy = y0 + dy;
      if (wx < 0 || wy < 0 || wx >= mapInfo.width || wy >= mapInfo.height) continue;
      const idx = wy * mapInfo.width + wx;
      const t = tiles[idx];
      const expl = explored[idx];

      // 屏幕坐标：相机锁定 (px, py) 到屏幕中心
      const sx = Math.floor(cx + (wx - px) * TILE_SIZE - TILE_SIZE / 2);
      const sy = Math.floor(cy + (wy - py) * TILE_SIZE - TILE_SIZE / 2);

      if (expl === 0) {
        ctx.fillStyle = '#000';
        ctx.fillRect(sx, sy, TILE_SIZE, TILE_SIZE);
        continue;
      }

      ctx.fillStyle = TERRAIN_COLOR[t] ?? '#444';
      ctx.fillRect(sx, sy, TILE_SIZE, TILE_SIZE);

      // 远视野（只见过、没走过）盖一层雾
      if (expl === 1) {
        ctx.fillStyle = 'rgba(0, 0, 0, 0.45)';
        ctx.fillRect(sx, sy, TILE_SIZE, TILE_SIZE);
      }
    }
  }

  // 地标
  ctx.font = `${Math.floor(TILE_SIZE * 0.7)}px sans-serif`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  for (const lm of mapInfo.landmarks) {
    const idx = lm.y * mapInfo.width + lm.x;
    if (explored[idx] === 0) continue;
    const sx = cx + (lm.x - px) * TILE_SIZE;
    const sy = cy + (lm.y - py) * TILE_SIZE;
    if (sx < -TILE_SIZE || sx > W + TILE_SIZE || sy < -TILE_SIZE || sy > H + TILE_SIZE) continue;
    ctx.fillText(landmarkSymbol(lm.id), sx, sy);
  }

  // 建造物
  for (const b of state.builtThings) {
    const idx = b.y * mapInfo.width + b.x;
    if (explored[idx] === 0) continue;
    const sx = cx + (b.x - px) * TILE_SIZE;
    const sy = cy + (b.y - py) * TILE_SIZE;
    if (sx < -TILE_SIZE || sx > W + TILE_SIZE || sy < -TILE_SIZE || sy > H + TILE_SIZE) continue;
    ctx.fillText('🏠', sx, sy);
  }

  // 地面物品堆（有物品的格子显示小箱子）
  const groundCells = new Set();
  for (const g of (state.nearbyGroundItems ?? [])) {
    groundCells.add(`${g.x},${g.y}`);
  }
  ctx.font = `${Math.floor(TILE_SIZE * 0.55)}px sans-serif`;
  for (const key of groundCells) {
    const [gx, gy] = key.split(',').map(Number);
    const idx = gy * mapInfo.width + gx;
    if (explored[idx] === 0) continue;
    const sx = cx + (gx - px) * TILE_SIZE;
    const sy = cy + (gy - py) * TILE_SIZE;
    if (sx < -TILE_SIZE || sx > W + TILE_SIZE || sy < -TILE_SIZE || sy > H + TILE_SIZE) continue;
    // 小箱子偏移到格子右下角，避免遮挡地形
    ctx.fillText('📦', sx + TILE_SIZE * 0.25, sy + TILE_SIZE * 0.3);
  }
  ctx.font = `${Math.floor(TILE_SIZE * 0.7)}px sans-serif`;

  // 作物地块
  ctx.font = `${Math.floor(TILE_SIZE * 0.55)}px sans-serif`;
  for (const c of (state.cropPlots ?? [])) {
    const idx = c.y * mapInfo.width + c.x;
    if (explored[idx] === 0) continue;
    const sx = cx + (c.x - px) * TILE_SIZE;
    const sy = cy + (c.y - py) * TILE_SIZE;
    if (sx < -TILE_SIZE || sx > W + TILE_SIZE || sy < -TILE_SIZE || sy > H + TILE_SIZE) continue;
    const emoji = c.stage === 2 ? '🌾' : c.stage === 1 ? '🌱' : '🌿';
    ctx.fillText(emoji, sx - TILE_SIZE * 0.25, sy - TILE_SIZE * 0.25);
  }
  ctx.font = `${Math.floor(TILE_SIZE * 0.7)}px sans-serif`;

  // 动物
  for (const a of state.animalsNear) {
    const sx = cx + (a.x - px) * TILE_SIZE;
    const sy = cy + (a.y - py) * TILE_SIZE;
    ctx.fillText(animalSymbol(a.species), sx, sy);
  }

  // 玩家：始终在屏幕正中（因为相机锁定 px/py）
  ctx.font = `${Math.floor(TILE_SIZE * 1.1)}px sans-serif`;
  ctx.fillText('🧍', cx, cy);

  // 走路动画未完成 → 下一帧继续
  if (p < 1) requestAnimationFrame(draw);
}

function landmarkSymbol(id) {
  const M = {
    wreck: '🚣', fresh_spring: '💧', coconut_grove: '🌴', rocky_beach: '🪨',
    cliff_top: '🗻', abandoned_camp: '⛺', cave: '🕳️', mangrove: '🌫️',
    lookout_hill: '⛰️', deep_jungle_clearing: '🌲', shipwreck_far: '⚓',
    message_in_bottle: '📜', bone_pile: '💀', banana_grove: '🍌',
    tide_pool: '🪸', old_tree: '🌳', cliff_shelter: '🏕️', salt_flat: '🧂',
    fire_pit: '🔥', cliff_path: '↗️',
  };
  return M[id] ?? '❓';
}

function animalSymbol(species) {
  return { parrot: '🦜', monkey: '🐒', dog: '🐕' }[species] ?? '🐾';
}

// === HUD ===
const STAT_LABELS = { hp: '体力', hunger: '饿', thirst: '渴', fatigue: '累' };

// 物品 id → 中文名称映射表（从 item_map.js 自动加载）
// 如需添加新物品，请修改 backend/src/survivalsands/items.py 并运行：
//   python3 scripts/generate_item_map.py
// 如果某个物品ID在 ITEM_ZH 中找不到，会走 humanizeItem 兜底逻辑
function humanizeItem(id) {
  if (ITEM_ZH[id]) return ITEM_ZH[id];
  // 未知 id：把下划线换空格，方便 debug；玩家也能勉强读
  return id.replace(/_/g, ' ');
}

// 清洗 LLM narration：替换偶尔漏出来的英文 snake_case 物品 id
function cleanNarration(text) {
  if (!text) return text;
  return text.replace(/\b[a-z][a-z0-9_]*_[a-z0-9_]+\b/g, (m) => humanizeItem(m));
}

const SKILL_ZH = { crafting: '制作', foraging: '采集', fishing: '捕鱼', hunting: '狩猎', cooking: '烹饪' };
function humanizeSkill(id) { return SKILL_ZH[id] ?? id; }

function renderHud() {
  const p = state.player;
  const lm = mapInfo.landmarks.find((l) => l.id === state.currentLandmarkId);
  const t = tiles[p.y * mapInfo.width + p.x];

  $('#scene-title').textContent =
    (lm ? lm.name : '荒野') + ` · ${TERRAIN_NAME[t]}`;
  $('#scene-desc').innerHTML = sceneDescription(state, lm, t);

  const bar = (cur, kind, invert = false) => {
    const pct = Math.max(0, Math.min(100, cur));
    const shown = invert ? 100 - pct : pct;
    return `<span class="stat-bar"><span class="k">${STAT_LABELS[kind]}</span>
      <span class="bar ${kind}"><div style="width:${shown}%"></div></span></span>`;
  };

  $('#hud').innerHTML = `
    <span><span class="k">第</span>${state.day}<span class="k">天 ·</span>${zhTime(state.time)} · ${zhWeather(state.weather)}</span>
    <span><span class="k">坐标</span>(${p.x}, ${p.y})</span>
    ${bar(p.hp, 'hp')}
    ${bar(p.hunger, 'hunger', true)}
    ${bar(p.thirst, 'thirst', true)}
    ${bar(p.fatigue, 'fatigue', true)}
    <span style="margin-left:auto"><button id="btn-reset">重置</button></span>
  `;
  $('#btn-reset')?.addEventListener('click', async () => {
    if (!confirm('确定要重置游戏？所有进度会丢失。')) return;
    await fetch('/api/reset', { method: 'POST' });
    await refreshAll();
    logEntry('世界已重置。', 'system');
  });

  const invHint = '<span style="color:#666;margin-left:auto">点这里或按 I 看详情</span>';
  $('#inv').id = 'inv'; // (no-op, just clarity)
  $('#inv').innerHTML = (p.inventory.length
    ? p.inventory.map((s) => `<span class="item">${escapeHtml(humanizeItem(s.id))} ×${s.qty}</span>`).join('')
    : '<span style="color:#666">背包是空的</span>') + invHint;
  // 让整行可点击打开背包详情
  $('#inv').onclick = openPack;
  // 添加 hover 样式（CSS 里没法选中带 hover 的 #inv，直接 inline 兜底）
  $('#inv').style.cursor = 'pointer';

  // 背包开着时跟着 state 实时刷新
  if (isPackOpen()) renderPack();
}

function sceneDescription(state, lm, terrain) {
  const parts = [];
  if (lm) {
    // 优先使用 LLM 生成的"踏入此地"独家描述；没有就退回静态 blurb
    const text = state.currentLandmarkArrival ?? landmarkBlurb(lm.id);
    const pending = state.arrivalPending && !state.currentLandmarkArrival;
    parts.push(
      `<strong>${lm.name}。</strong>` +
        (pending ? '<em style="color:#888">（你环顾四周……）</em>' : escapeHtml(cleanNarration(text))),
    );
  } else {
    parts.push(`你脚下是<em>${TERRAIN_NAME[terrain]}</em>。`);
  }
  if (state.animalsNear.length) {
    parts.push(
      '附近：' +
        state.animalsNear
          .map((a) => `${animalSymbol(a.species)} ${a.name}（${trustHint(a.trust)}）`)
          .join('，'),
    );
  }
  // 地面物品（3 格内）
  const ground = state.nearbyGroundItems ?? [];
  if (ground.length) {
    const grouped = {};
    for (const g of ground) grouped[g.id] = (grouped[g.id] || 0) + g.qty;
    const line = Object.entries(grouped)
      .map(([id, qty]) => `${escapeHtml(humanizeItem(id))}×${qty}`)
      .join('、');
    parts.push(`<span style="color:#c4a84a">📦 地面：${line}</span>`);
  }
  // 附近农田（5 格内）
  const crops = (state.cropPlots ?? []).filter(
    (c) => Math.abs(c.x - state.player.x) <= 5 && Math.abs(c.y - state.player.y) <= 5,
  );
  if (crops.length) {
    const CROP_ZH = { seeds: '种子', banana_seedling: '香蕉幼苗' };
    const STAGE_ZH = { 0: '萌芽中', 1: '生长中', 2: '可收获 🌾' };
    const lines = crops.map((c) => {
      const name = CROP_ZH[c.crop_type] ?? c.crop_type;
      const stage = STAGE_ZH[c.stage] ?? '';
      const water = c.watered_count ? `浇水${c.watered_count}次` : '';
      const fert = c.fertilized ? '已施肥' : '';
      const extra = [water, fert].filter(Boolean).join('·');
      return `${name}[${stage}]${extra ? ' ' + extra : ''}`;
    });
    parts.push(`<span style="color:#7aaa55">🌱 农田：${lines.join('，')}</span>`);
  }
  return parts.join('<br><br>');
}

const LM_BLURB = {
  wreck: '小船的残骸半埋在沙里。这是你漂上来的地方。',
  fresh_spring: '一股清泉从岩石间渗出。可以直接饮用。',
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
};
function landmarkBlurb(id) { return LM_BLURB[id] ?? ''; }

function trustHint(t) {
  if (t < 10) return '警惕地';
  if (t < 40) return '有点防备';
  if (t < 70) return '不再躲你';
  return '亲近';
}
function zhTime(t) {
  return ({ dawn: '黎明', morning: '上午', noon: '正午', afternoon: '下午', dusk: '黄昏', night: '夜晚' })[t] ?? t;
}
function zhWeather(w) {
  return ({ clear: '晴', cloudy: '多云', rain: '雨', storm: '风暴' })[w] ?? w;
}
function escapeHtml(s) {
  return s.replace(/[<>&"]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' }[c]));
}

// === 死亡黑幕 ===
function handleGameOver(newState) {
  if (!newState.gameOver || !newState.deathNarration) return;
  const overlay = $('#death-overlay');
  const narrationEl = $('#death-narration');
  const countdown = $('#death-countdown');
  narrationEl.textContent = newState.deathNarration;
  overlay.classList.add('visible');
  requestAnimationFrame(() => overlay.classList.add('dark'));

  let secs = 8;
  countdown.textContent = `${secs} 秒后重生……`;
  const timer = setInterval(() => {
    secs--;
    if (secs > 0) {
      countdown.textContent = `${secs} 秒后重生……`;
    } else {
      clearInterval(timer);
      overlay.classList.remove('dark');
      setTimeout(() => {
        overlay.classList.remove('visible');
        refreshAll();
      }, 1200);
    }
  }, 1000);
}

// === 网络 ===
async function refreshAll() {
  mapInfo = await (await fetch('/api/map')).json();
  tiles = base64ToBytes(mapInfo.tilesB64);
  explored = base64ToBytes(mapInfo.exploredB64);
  state = await (await fetch('/api/state')).json();
  // 把相机锚点同步到玩家当前位置（否则首屏会以 (0,0) 为中心，画面全黑）
  anim = {
    fromX: state.player.x, fromY: state.player.y,
    toX: state.player.x, toY: state.player.y,
    t0: performance.now(), dur: 1,
  };
  renderHud();
  draw();
  maybePollArrival();
}

// 在某个地标上停留且后端正在生成描述时，轮询拉一次 state
let arrivalPollTimer = null;
function maybePollArrival() {
  if (arrivalPollTimer) {
    clearTimeout(arrivalPollTimer);
    arrivalPollTimer = null;
  }
  if (!state) return;
  if (!state.arrivalPending) return;
  if (state.currentLandmarkArrival) return;
  arrivalPollTimer = setTimeout(async () => {
    try {
      const fresh = await (await fetch('/api/state')).json();
      const wasPending = state.arrivalPending && !state.currentLandmarkArrival;
      state = fresh;
      handleGameOver(state);
      renderHud();
      // 描述刚到位 → 在 log 里轻提一下
      if (wasPending && state.currentLandmarkArrival) {
        const lm = mapInfo.landmarks.find((l) => l.id === state.currentLandmarkId);
        if (lm) logEntry(
          `<span class="system">${escapeHtml(lm.name)} —— ${escapeHtml(cleanNarration(state.currentLandmarkArrival))}</span>`,
        );
      } else if (state.arrivalPending) {
        // 还没好，再等一轮
        maybePollArrival();
      }
    } catch (e) {
      // 网络错误就放弃，下次进入或动作时再有机会拿到
    }
  }, 1500);
}

function base64ToBytes(b64) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}

// 把一次按键请求放进队列；没有动画在跑时立刻取一个执行
function queueMove(dx, dy, running) {
  // 同一个方向重复按住不要无限堆，最多排 1 个待执行
  if (moveQueue.length === 0 || moveQueue[moveQueue.length - 1].dx !== dx || moveQueue[moveQueue.length - 1].dy !== dy) {
    moveQueue.push({ dx, dy, dur: running ? RUN_STEP_MS : STEP_MS });
  }
  if (!stepInFlight) takeNextStep();
}

async function takeNextStep() {
  if (busy) return;
  const next = moveQueue.shift();
  if (!next) return;
  stepInFlight = true;
  // 启动动画：从当前 player（服务端权威）滑向 player+next
  const fromX = state.player.x;
  const fromY = state.player.y;
  const toX = fromX + next.dx;
  const toY = fromY + next.dy;
  anim = { fromX, fromY, toX, toY, t0: performance.now(), dur: next.dur };
  requestAnimationFrame(draw);

  let r;
  try {
    r = await fetch('/api/move', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ dx: next.dx, dy: next.dy }),
    }).then((r) => r.json());
  } catch (e) {
    stepInFlight = false;
    return;
  }
  if (r && r.ok && r.state) {
    state = r.state;
    handleGameOver(state);
    maybePollArrival();
  } else if (r && r.ok === false && r.reason) {
    // 撞墙/边界：把动画拉回原地（视觉上"踏空一步"），并清空连按队列
    anim = { fromX, fromY, toX: fromX, toY: fromY, t0: performance.now(), dur: 120 };
    moveQueue.length = 0;
    requestAnimationFrame(draw);
  }
  renderHud();

  // 等动画播完再走下一步——让节奏稳定
  const remain = anim.dur - (performance.now() - anim.t0);
  setTimeout(() => {
    // 动画结束时才更新探索图，保证格子和小人同步亮起
    if (r && r.ok && r.exploredB64) explored = base64ToBytes(r.exploredB64);
    stepInFlight = false;
    if (moveQueue.length > 0) takeNextStep();
  }, Math.max(0, remain));
}

// 当前在跑的动作请求的 AbortController（点击中止/按 ESC 时调用 .abort()）
let currentActionAbort = null;

function abortCurrentAction(reason = '已中止') {
  if (!currentActionAbort) return false;
  currentActionAbort.abort(reason);
  currentActionAbort = null;
  return true;
}

async function submitAction(text) {
  if (busy) return;
  if (!text.trim()) return;
  if (text === '/reset') {
    await fetch('/api/reset', { method: 'POST' });
    await refreshAll();
    logEntry('世界已重置。', 'system');
    return;
  }

  // 启发式：动作里若提到附近的某只动物，走 /api/animal
  const targeted = state.animalsNear.find(
    (a) =>
      text.includes(a.name) ||
      text.includes(a.species === 'parrot' ? '鹦鹉' : a.species === 'monkey' ? '猴' : '狗'),
  );

  busy = true;
  setBusyUI(true);
  const t0 = Date.now();
  logEntry(`<span class="you">› ${escapeHtml(text)}</span>`);
  const thinking = document.createElement('div');
  thinking.className = 'entry system';
  thinking.textContent = '（沉吟片刻... 按 ESC 或点"中止"取消）';
  $('#log').appendChild(thinking);
  $('#log').scrollTop = $('#log').scrollHeight;

  const ctrl = new AbortController();
  currentActionAbort = ctrl;

  try {
    const url = targeted ? '/api/animal' : '/api/action';
    const body = targeted
      ? { animal: targeted.id, action: text }
      : { action: text };
    const resp = await fetch(url, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
      signal: ctrl.signal,
    });
    const r = await resp.json();
    thinking.remove();
    if (r.error) {
      logEntry(`<span class="err">出错了：${escapeHtml(r.error)}</span>`);
    } else {
      const ms = r.costMs ?? Date.now() - t0;
      logEntry(
        `<div class="narration">${escapeHtml(cleanNarration(r.narration ?? ''))}</div>
         <div class="meta">${ms}ms${r.ok === false ? ' · 不可行' : ''}</div>`,
      );
      if (r.state) {
        state = r.state;
        handleGameOver(state);
        renderHud();
        draw();
      }
    }
  } catch (e) {
    thinking.remove();
    if (e && (e.name === 'AbortError' || ctrl.signal.aborted)) {
      // 把刚误发的内容回填到输入框，方便玩家继续编辑
      if ($('#input').value === '') $('#input').value = text;
      logEntry(`<span class="system">已中止（输入已回填到输入框，可继续编辑）</span>`);
    } else {
      logEntry(`<span class="err">网络错误：${escapeHtml(String(e))}</span>`);
    }
  }
  currentActionAbort = null;
  busy = false;
  setBusyUI(false);
}

function setBusyUI(b) {
  const btn = $('#btn-abort');
  if (btn) btn.style.display = b ? 'inline-block' : 'none';
}

// === 输入 ===
$('#input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    const text = e.target.value;
    e.target.value = '';
    submitAction(text);
  } else if (e.key === 'Escape') {
    e.preventDefault();
    if (busy) abortCurrentAction();
    else e.target.value = ''; // 没在等待 → ESC 清空输入框
  }
});

// 全局快捷键：ESC 中止/关背包，I 切换背包
window.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    if (isPackOpen()) {
      e.preventDefault();
      closePack();
      return;
    }
    if (busy) {
      e.preventDefault();
      abortCurrentAction();
      return;
    }
  }
  // I/i 切换背包——但不能在输入框里触发（玩家在打字）
  if ((e.key === 'i' || e.key === 'I') && document.activeElement !== $('#input')) {
    e.preventDefault();
    if (isPackOpen()) closePack();
    else openPack();
  }
});

// 哪些方向键正按住
const heldDirs = new Set();
let autoMoveTimer = null;
let lastStepAt = 0; // 上一步触发的时间戳，用于硬性节流

function scheduleAutoMove() {
  if (autoMoveTimer) return; // 已经有调度在跑
  const now = performance.now();
  const stepDelay = heldRunning ? RUN_STEP_MS : STEP_MS;
  const elapsed = now - lastStepAt;
  // 距离上一步至少 stepDelay 才允许下一步——保证一次按键不会触发 2 步
  const wait = Math.max(0, stepDelay - elapsed);
  autoMoveTimer = setTimeout(() => {
    autoMoveTimer = null;
    if (heldDirs.size === 0) return;
    const dir = Array.from(heldDirs).pop();
    const [dx, dy] = dir.split(',').map(Number);
    lastStepAt = performance.now();
    queueMove(dx, dy, heldRunning);
    if (heldDirs.size > 0) scheduleAutoMove();
  }, wait);
}
function stopAutoMove() {
  if (autoMoveTimer) clearTimeout(autoMoveTimer);
  autoMoveTimer = null;
}

let heldRunning = false;

window.addEventListener('keydown', (e) => {
  if (document.activeElement === $('#input')) return; // 在输入框里时让 WASD 当字符用
  if (isPackOpen()) return; // 背包打开时锁住移动
  let dx = 0, dy = 0;
  switch (e.key.toLowerCase()) {
    case 'w': case 'arrowup':    dy = -1; break;
    case 's': case 'arrowdown':  dy = 1; break;
    case 'a': case 'arrowleft':  dx = -1; break;
    case 'd': case 'arrowright': dx = 1; break;
    case 'shift': heldRunning = true; return;
    default: return;
  }
  e.preventDefault();
  if (e.repeat) return; // 操作系统重复触发的我们自己控制节奏
  const key = `${dx},${dy}`;
  if (heldDirs.has(key)) return; // 已经在按了，不要重复触发
  heldDirs.add(key);
  scheduleAutoMove();
});
window.addEventListener('keyup', (e) => {
  let dx = 0, dy = 0;
  switch (e.key.toLowerCase()) {
    case 'w': case 'arrowup':    dy = -1; break;
    case 's': case 'arrowdown':  dy = 1; break;
    case 'a': case 'arrowleft':  dx = -1; break;
    case 'd': case 'arrowright': dx = 1; break;
    case 'shift': heldRunning = false; return;
    default: return;
  }
  heldDirs.delete(`${dx},${dy}`);
});

// 让画布默认获得"键盘焦点"以外的方式：点击地图区域时把焦点从输入框拿走
$('#map').addEventListener('click', () => $('#map').focus());

// 中止按钮
$('#btn-abort')?.addEventListener('click', () => abortCurrentAction());

// === 背包面板 ===
let itemCatalog = null; // {id: {zh, category, notes}}
const CATEGORY_LABEL = {
  food: '食物', water: '水', fuel: '燃料', material: '原料', tool: '工具', misc: '杂物',
};
const CATEGORY_ORDER = ['food', 'water', 'fuel', 'material', 'tool', 'misc'];

async function fetchItemCatalog() {
  if (itemCatalog) return itemCatalog;
  try {
    const r = await fetch('/api/items').then((r) => r.json());
    itemCatalog = {};
    for (const it of r.items) {
      itemCatalog[it.id] = it;
    }
  } catch (e) {
    itemCatalog = {}; // 拉不到也别炸；展示时退化
  }
  return itemCatalog;
}

function renderPack() {
  const body = $('#pack-body');
  const summary = $('#pack-summary');
  const inv = state?.player?.inventory ?? [];
  if (inv.length === 0) {
    body.innerHTML = '<div class="pack-empty">背包空空如也。<br>试试在场景里搜寻、采集、或是动手做点什么。</div>';
    summary.textContent = '';
    return;
  }
  const totalQty = inv.reduce((s, x) => s + x.qty, 0);
  const totalKinds = inv.length;
  summary.textContent = `· ${totalKinds} 种 / 共 ${totalQty} 件`;

  // 按 category 分桶；不在 catalog 里的归为 misc 并标"未知"
  const byCat = {};
  for (const stack of inv) {
    const def = itemCatalog[stack.id];
    const cat = def?.category ?? 'misc';
    (byCat[cat] ||= []).push({ stack, def });
  }

  const html = CATEGORY_ORDER
    .filter((c) => byCat[c]?.length)
    .map((c) => {
      const items = byCat[c]
        .map(({ stack, def }) => {
          const zh = def?.zh ?? humanizeItem(stack.id);
          const notes = def?.notes
            ? `<div class="notes">${escapeHtml(def.notes)}</div>`
            : '';
          // 瓶中信专属"阅读"按钮
          const readBtn = stack.id === 'bottle_message'
            ? `<button class="btn-read-bottle" onclick="readBottleMessage(event)">阅读</button>`
            : '';
          return `<div class="pack-item">
            <div class="name">${escapeHtml(zh)}</div>
            <div class="qty">×${stack.qty}</div>
            ${notes}
            ${readBtn}
          </div>`;
        })
        .join('');
      return `<div class="pack-cat">
        <h3>${CATEGORY_LABEL[c] ?? c}</h3>
        ${items}
      </div>`;
    })
    .join('');
  body.innerHTML = html;
}

async function openPack() {
  await fetchItemCatalog();
  renderPack();
  $('#pack-overlay').classList.add('open');
}
function closePack() {
  $('#pack-overlay').classList.remove('open');
}
function isPackOpen() {
  return $('#pack-overlay').classList.contains('open');
}

$('#pack-close').addEventListener('click', closePack);
// 点 overlay 空白处也关闭
$('#pack-overlay').addEventListener('click', (e) => {
  if (e.target.id === 'pack-overlay') closePack();
});

(async () => {
  resizeCanvas();
  await refreshAll();
  fetchItemCatalog(); // 后台拉，不等
  logEntry('你睁开眼睛。咸涩的海风扑面而来。', 'system');
  logEntry('用 <strong>WASD</strong> 走动，下方输入框描述你想做什么。按 <strong>I</strong> 查看背包。', 'system');
})();

// === 瓶中信阅读 ===
async function readBottleMessage(e) {
  e.stopPropagation();
  closePack();
  if (busy) return;
  busy = true;
  setBusyUI(true);
  logEntry('<span class="you">› 阅读瓶中信</span>');
  const thinking = document.createElement('div');
  thinking.className = 'entry system';
  thinking.textContent = '（展开那张皱巴巴的纸条……）';
  $('#log').appendChild(thinking);
  $('#log').scrollTop = $('#log').scrollHeight;
  try {
    const r = await fetch('/api/action', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ action: '我读瓶中信' }),
    }).then((r) => r.json());
    thinking.remove();
    if (r.narration) {
      logEntry(
        `<div class="narration bottle-letter">${escapeHtml(cleanNarration(r.narration))}</div>`,
      );
    }
    if (r.state) {
      state = r.state;
      renderHud();
      draw();
    }
  } catch (err) {
    thinking.remove();
    logEntry(`<span class="err">读取失败：${escapeHtml(String(err))}</span>`);
  }
  busy = false;
  setBusyUI(false);
}
