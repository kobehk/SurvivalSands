"""三个 LLM 调用层（judge / animals / arrival）共用的 prompt 片段。

设计原则：每条规则只在一处定义，按场景组合注入。
"""

from __future__ import annotations

from .items import item_catalog_for_prompt

# ============================================================
# 通用：narration 必须用中文 + 不漏 snake_case
# 三个场景（judge / animals / arrival）都需要
# ============================================================
CHINESE_NARRATION_RULE = """
旁白（narration）写作约束：
- narration 是给玩家看的中文叙事，必须**全部用自然中文**
- 严禁在 narration 里出现英文物品 id（如 coconut_shell、rusty_iron_flakes、fresh_water）。
  英文 id 只能出现在结构化字段（consume_items / produce_items / animal_gives 的 item_id 等）里
- 提到物品时用自然中文：「椰子壳」、「锈刀」、「干燥的火绒」，不要用 snake_case
- 不要在叙事里建议玩家用某个特定的英文 id，那破坏沉浸感
""".strip()


# ============================================================
# 物品使用约束：narration 只能描写真实存在的物品
# 仅用于 judge 和 animals（arrival 是环境描写，不涉及"使用"）
# ============================================================
ITEM_USE_RULE = """
关于「使用物品」的真实性：
- narration 里描写「使用某物品」时，**必须真实存在**于：
    (a) 玩家背包（情境里给出），或
    (b) 当前所在地形/地标按常理就有的环境物（沙滩有沙、丛林有树枝、海边有海水）
- 不要凭空给玩家「加」工具或材料——背包是空的就不能写"你掏出小刀"
""".strip()


# ============================================================
# 物品命名规范——给 judge 用（需要产出/消耗任意类型的物品）
# 包含完整物品清单（约 55 项）。Token 较大，谨慎使用。
# ============================================================
def item_id_rule_full() -> str:
    return f"""
物品命名规范（重要）：
- 产出/消耗物品时，**优先使用下列已知物品 id**：
{item_catalog_for_prompt()}

- 如果你需要表达上面清单里没有的物品（例如玩家做出新东西），可以新造 id，但必须：
  * 全小写英文 + 下划线（snake_case）
  * 名词性、单数（写 stick 不写 sticks）
  * 同一物品多次出现 id 必须一致（不要这次叫 stone 下次叫 rock）
  * 优先复用已有概念，比如玩家做了个新容器，宁可叫 coconut_cup 也不要叫 cup_v2
- 同一物品在 narration 里用对应的中文名（你看到 coconut_shell 就写「椰子壳」）
""".strip()


# ============================================================
# 动物赠礼专用：动物只能"叼/留下"小型自然物
# 给 animals 用，比 item_id_rule_full 简短得多（省 ~700 tokens/次）
# ============================================================
GIFT_ITEM_HINT = """
关于 animal_gives.item_id 的规范：
- 动物只能赠送它能在自然中**接触到的小型物品**——以下是合理候选：
  * feather（羽毛）：鹦鹉/猴子可能掉/带来的
  * seashell（贝壳）：海边活动的动物可能叼来的
  * bone（骨头）：狗会感兴趣的
  * berries（浆果）/wild_fruit（野果）/seeds（种子）/nuts（坚果）：果食性动物可能从树上带下来
  * coconut_meat（椰肉）/banana（香蕉）：能开椰子的猴子可能掰碎一小块
- **不要**让动物赠送：
  * 玩家自制工具（rusty_knife、spear、torch、bowl 等）——动物拿不到也不会用
  * 大件物品（wood_plank、long_branch）——动物搬不动
  * 加工品（fish_cooked、tinder、rope）——动物没能力制作
- 同一物品在 narration 里用中文（你看到 feather 就写「羽毛」）
""".strip()


# 兼容旧调用（项目其它地方曾用 item_id_rule()）
def item_id_rule() -> str:
    return item_id_rule_full()
