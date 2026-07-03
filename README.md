# SurvivalSands

AI 原生小岛生存游戏。验证「确定性世界状态 + LLM 导演层」是否好玩。

核心设定：**玩家独自漂流到岛上**。鲁滨逊式的孤独是核心张力 —— 前期没有人类 NPC，只有动物相伴。

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.14 + FastAPI + uvicorn + SQLite |
| 前端 | Vue 3 + TypeScript + Vite + Three.js + Pinia |
| LLM | DeepSeek（OpenAI 兼容协议，关闭 thinking 模式 + 强制 tool_choice） |
| 地形 | opensimplex 噪声 + 径向衰减，程序化生成 200×120 岛屿（11 种地形） |
| 依赖管理 | uv（Python）、npm（前端） |

## 启动

```bash
# 前提：确保已安装 Python 3.14+、Node.js 20+、uv

# 1. 配置环境变量（仓库根目录）
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY

# 2. 安装前端依赖
cd frontend && npm install && cd ..

# 3. 启动后端
cd backend
uv run python server.py

# 4. 启动前端开发服务器（新终端）
cd frontend
npm run dev

# 5. 浏览器打开前端 dev server 地址（默认 http://localhost:5173）
```

生产构建（可选）：

```bash
npm run build          # 前端构建到 public/
cd backend && uv run python server.py   # 访问 http://localhost:3000
```

## 操作

- **WASD** 移动（按住 Shift 跑步）
- **输入框打字 + 回车** → LLM 判定自由动作
- **ESC** 中止当前 LLM 调用
- 提到附近动物名（如「鹦鹉」）时，自动走动物互动路径

## 架构

```
frontend/
  App.vue                  # 根组件（地图 + 面板 + 浮层）
  main.ts                  # 入口
  stores/game.ts           # Pinia store：状态管理 + API 调用
  components/
    MapCanvas.vue           # Three.js 3D 场景 + Canvas 2D 地图
    ScenePanel.vue          # Three.js 场景面板
    ActionInput.vue         # 自由动作输入框
    ActionLog.vue           # 旁白日志
    StatusBar.vue           # 玩家状态 HUD
    EnvStatus.vue           # 环境状态
    PackOverlay.vue         # 背包浮层
    DeathOverlay.vue        # 死亡画面
    StatBar.vue             # 状态条组件
  composables/
    useCanvas.ts            # Three.js 渲染逻辑
    useInput.ts             # 键盘输入处理

backend/
  server.py                 # FastAPI 路由 + 静态文件托管
  world.py                  # World 状态机 + WorldDelta + try_move + 探索图
  terrain.py                # 程序化地形生成（200×120，11 种地形，确定性 seed）
  landmarks.py              # 20 个手写地标 + 程序化落位 + arrival_context
  items.py                  # 55+ 物品白名单（id ↔ 中文名 ↔ 分类）
  judge.py                  # 玩家自由动作 → LLM 判定 + 消耗/产出/旁白
  animals.py                # 动物互动 + 物种行为 + trust 阈值 + 游荡
  arrival.py                # 玩家踏入新地标时的独家描述
  weather.py                # 天气系统
  death.py                  # 死亡机制
  bottle.py                 # 漂流瓶系统
  search.py                 # 搜索机制
  session.py                # 粘合层 + SQLite 持久化 + 异步 arrival 任务
  llm.py                    # DeepSeek 封装（thinking off + force tool_choice）
  prompts_shared.py         # 共享 prompt 片段（中文规则 + 物品规则）
```

## 关键设计

- **确定性核心 + LLM 导演**：World 状态由 Python 维护，LLM 只产出 `WorldDelta`，runtime 校验后才 mutate。AI Dungeon 的「全 LLM 管状态」会漂移，这里不会。
- **物品 id 白名单**：55+ 高频物品的 id 全部固定，喂给 LLM 让它优先复用而非自由发明。`items.py` 是唯一数据源。
- **判定层不重复 arrival 描述**：玩家在地标内做动作时，prompt 里只喂硬编码 description，不喂 LLM 生成的 200 字独家描述（每次省 ~300 token）。
- **arrival 异步生成**：玩家踏入新地标 → fire-and-forget 后台任务 → 几秒后下次拉 state 自动拿到独家描述。前端轮询 1.5s 检查。
- **动物物种行为**：鹦鹉/猴子/狗各有独立的 `behavior` 描述 + `trust_thresholds`，prompt 从 `SPECIES_TRAITS` 派生而非硬编码。
- **批量移动**：按住方向键时移动指令在客户端累积，松键时一次发送批量请求，大幅减少 HTTP 往返和 IO 开销。

## 添加新物品

在 `backend/items.py` 的 `ITEMS` 列表中添加新物品定义即可。前端通过 `/api/items` 接口动态获取物品列表。
