# SurvivalSands · Week-1 文字版骨架

AI 原生小岛生存游戏 · 第 1 周 MVP。验证「确定性世界状态 + LLM 导演层」是否好玩。

核心设定：**玩家独自漂流到岛上**。鲁滨逊式的孤独是核心张力——前期没有人类 NPC，AI 含量通过两个方向承接：
- **B. 动物 AI**（已实现）：会逐渐熟悉玩家的动物，有 trust/fear/hunger 状态。不会说话，通过行为表达。
- **E. 后期解锁的「星期五」**（接口预留）：触发某个剧情条件后才会出现。

## 技术栈

- **后端**：Python 3.14 + FastAPI + uvicorn + SQLite
- **前端**：原生 HTML + Canvas + 原生 JS（`public/`）
- **LLM**：DeepSeek（OpenAI 兼容协议，关闭 thinking 模式 + 强制 tool_choice）
- **地形**：opensimplex 噪声 + 径向衰减程序化生成 200×120 岛屿
- **依赖管理**：uv

## 启动

```bash
# 1. 在仓库根目录创建 .env：
cat > .env <<EOF
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_MODEL=deepseek-v4-flash
PORT=3000
DB_PATH=./game.db
EOF

# 2. 生成前端物品映射表（从 items.py 自动生成）
npm run build:items
# 或直接使用：python3 scripts/generate_item_map.py

# 3. 启动后端
cd backend
uv run python -m survivalsands.server

# 4. 浏览器打开 http://localhost:3000
```

## 操作

- **WASD 走动**（按住 Shift 跑步）
- **输入框打字 + 回车** → LLM 判定你的自由动作
- **ESC** 中止当前 LLM 调用
- 提到附近动物名（如「鹦鹉」/「红冠」）时，自动走动物互动路径

## 架构

```
public/
  index.html, game.js   # Canvas 地图 + 状态 HUD + 旁白日志 + 输入框
  item_map.js            # 自动生成：物品 id → 中文映射（勿手动修改）
backend/
  src/survivalsands/
    terrain.py          # 程序化地形生成（200×120，11 种地形，确定性 seed）
    landmarks.py        # 20 个手写地标 + 程序化落位 + arrival_context
    items.py            # 55+ 物品白名单（id ↔ 中文名 ↔ 分类）→ 唯一数据源
    world.py            # World 状态机 + WorldDelta + try_move + 探索图
    llm.py              # DeepSeek 封装（thinking off + force tool_choice）
    prompts_shared.py   # 共享 prompt 片段（中文规则 + 物品规则）
    judge.py            # 玩家自由动作 → 判定 + 消耗/产出/旁白
    animals.py          # 动物互动 + 物种行为 + trust 阈值 + 游荡
    arrival.py          # 玩家踏入新地标时的独家描述
    session.py          # 粘合层 + SQLite 持久化 + 异步 arrival 任务
    server.py           # FastAPI 路由 + 静态托管
scripts/
  generate_item_map.py  # 从 items.py 自动生成 public/item_map.js
```

## 关键设计

- **确定性核心 + LLM 导演**：World 状态由 Python 维护，LLM 只产出 `WorldDelta`，runtime 校验后才 mutate。AI Dungeon 的"全 LLM 管状态"会漂移，这里不会。
- **物品 id 白名单**：55+ 高频物品的 id 全部固定，喂给 LLM 让它优先复用而非自由发明。**前端映射表自动生成**：`items.py` 是唯一数据源，`scripts/generate_item_map.py` 会自动生成 `public/item_map.js`，无需手动同步。
- **判定层不重复 arrival 描述**：玩家在 wreck 做动作时，prompt 里只喂硬编码 description，不喂 LLM 生成的 200 字独家描述（每次省 ~300 token）。
- **arrival 异步生成**：玩家踏入新地标 → fire-and-forget 后台任务 → 几秒后下次拉 state 自动拿到独家描述。前端轮询 1.5s 检查。
- **动物物种行为**：鹦鹉/猴子/狗 各有独立的 `behavior` 描述 + `trust_thresholds`，prompt 从 SPECIES_TRAITS 派生而非硬编码。

### 添加新物品

只需在 `backend/src/survivalsands/items.py` 的 `ITEMS` 列表中添加新物品定义，然后运行：

```bash
npm run build:items
# 或
python3 scripts/generate_item_map.py
```

前端映射表会自动更新，无需手动修改 `game.js`。

## 已知限制（先不做）

- 没有向量记忆 / reflection / planning 层
- 动物只有 1 只（红冠鹦鹉）；没有「星期五」；没有动态事件
- 单存档、单玩家
- 60000 格地图中只有 ~20 个手写地标，其他靠地形多样性 + 战争迷雾撑探索感

## 成本估算（DeepSeek v4-flash）

- 每次动作判定 ≈ ¥0.005
- 每次动物互动 ≈ ¥0.005
- 每个新地标的 arrival 描述 ≈ ¥0.005，整局 20 个 ≈ ¥0.1
- 玩 1 小时 ≈ ¥0.4
