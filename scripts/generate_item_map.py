#!/usr/bin/env python3
"""从 items.py 自动生成前端的物品映射表 public/item_map.js

使用方法：
    python scripts/generate_item_map.py

这会自动更新 public/item_map.js，然后 game.js 引入这个文件即可。
"""

from __future__ import annotations

import os
import sys
import re

# 添加 backend/src 到路径，以便导入 items 模块
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
BACKEND_SRC = os.path.join(PROJECT_ROOT, "backend", "src")
sys.path.insert(0, BACKEND_SRC)

from survivalsands.items import ITEMS  # noqa: E402


def generate_item_map_js(output_path: str) -> None:
    """生成 item_map.js 文件"""
    # 按分类组织，方便阅读
    categories_order = ["food", "water", "fuel", "material", "tool", "misc"]
    category_labels = {
        "food": "食物",
        "water": "水",
        "fuel": "燃料",
        "material": "原料",
        "tool": "工具",
        "misc": "杂物",
    }
    
    # 按分类分组
    by_category: dict[str, list[tuple[str, str]]] = {}
    for item in ITEMS:
        by_category.setdefault(item.category, []).append((item.id, item.zh))
    
    # 生成 JS 内容
    lines = [
        "// 自动生成，请勿手动修改。运行 scripts/generate_item_map.py 重新生成",
        "// 物品 id → 中文名称映射表",
        "",
        "const ITEM_ZH = {",
    ]
    
    for cat in categories_order:
        items = by_category.get(cat, [])
        if not items:
            continue
        lines.append(f"  // {category_labels[cat]}")
        for item_id, zh in items:
            lines.append(f"  {item_id}: '{zh}',")
        lines.append("")
    
    lines.append("};")
    lines.append("")
    lines.append("// 为了兼容，如果 game.js 期望的是 ITEM_ZH 对象")
    lines.append("// 确保在加载 game.js 之前加载此文件")
    
    content = "\n".join(lines) + "\n"
    
    # 写入文件
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    
    print(f"✅ 已生成 {output_path}")
    print(f"   共 {len(ITEMS)} 个物品映射")


def main():
    output_path = os.path.join(PROJECT_ROOT, "public", "item_map.js")
    generate_item_map_js(output_path)


if __name__ == "__main__":
    main()
