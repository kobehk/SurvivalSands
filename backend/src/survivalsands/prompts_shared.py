"""三个 LLM 调用层（judge / animals / arrival）共用的 prompt 片段。

设计原则：每条规则只在一处定义，按场景组合注入。
"""

from __future__ import annotations

from .items import item_catalog_for_prompt

# ============================================================
# 通用：narration 必须用中文 + 不漏 snake_case
# 三个场景（judge / animals / arrival）都需要
# ============================================================
CHINESE_NARRATION_RULE = "narration 必须全部用自然中文，严禁出现英文物品 id（如 fresh_water、rusty_knife）——英文 id 只能出现在结构化字段里。提到物品用「椰子壳」「锈刀」这类中文名。"


# ============================================================
# 物品使用约束：narration 只能描写真实存在的物品
# 仅用于 judge 和 animals（arrival 是环境描写，不涉及"使用"）
# ============================================================
ITEM_USE_RULE = "narration 里描写「使用某物品」时，该物品必须真实存在于玩家背包或当前地形的环境物中——不能凭空写「你掏出小刀」。"


# ============================================================
# 物品命名规范——给 judge 用（需要产出/消耗任意类型的物品）
# 包含完整物品清单（约 55 项）。缓存为模块级常量避免重复计算。
# ============================================================
_ITEM_CATALOG_CACHE: str | None = None


def item_id_rule_full() -> str:
    global _ITEM_CATALOG_CACHE
    if _ITEM_CATALOG_CACHE is None:
        _ITEM_CATALOG_CACHE = item_catalog_for_prompt()
    return f"""
物品命名规范（重要）：
- 产出/消耗物品时，**优先使用下列已知物品 id**：
{_ITEM_CATALOG_CACHE}

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
GIFT_ITEM_HINT = """赠礼物品须是动物自然可接触的小型物：feather/seashell/bone/berries/wild_fruit/seeds/nuts/coconut_meat/banana。
禁止赠送玩家自制工具（rusty_knife、spear 等）、大件物品（wood_plank）或加工品（rope、tinder）。"""


# 兼容旧调用（项目其它地方曾用 item_id_rule()）
def item_id_rule() -> str:
    return item_id_rule_full()
