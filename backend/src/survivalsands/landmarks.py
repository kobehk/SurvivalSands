"""地标：岛上手写的"特殊地点"，每个有独特描述、可玩内容、坐标范围。

程序化生成阶段把每个地标"落"到合适地形的格子上。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .search import LootEntry, SearchStage
from .terrain import Island, Terrain, tile_at


@dataclass
class LandmarkDef:
    id: str
    name: str
    description: str
    features: list[str]
    preferred_terrains: list[Terrain]
    radius: int
    priority: int
    near_terrain: Terrain | None = None
    arrival_context: str | None = None
    # 多阶段搜索表（可选）
    search_stages: list[SearchStage] = field(default_factory=list)
    # 功能标签（和 BuiltThing.tags 同语义）
    tags: list[str] = field(default_factory=list)


@dataclass
class PlacedLandmark:
    """LandmarkDef + 坐标。坐标在 place_landmarks 时由地形决定。"""

    id: str
    name: str
    description: str
    features: list[str]
    preferred_terrains: list[Terrain]
    radius: int
    priority: int
    x: int
    y: int
    near_terrain: Terrain | None = None
    arrival_context: str | None = None
    search_stages: list[SearchStage] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


LANDMARK_DEFS: list[LandmarkDef] = [
    LandmarkDef(
        id="wreck",
        name="小船残骸",
        description="一具被海水冲上岸的小船残骸半埋在沙里，断裂的木板上还挂着几条破布。这是你漂流过来时的船。",
        features=["可以搜寻物资", "能取下木板和铁钉", "附近沙地里偶尔挖到东西"],
        preferred_terrains=[Terrain.BEACH],
        radius=3,
        priority=100,
        arrival_context="这是玩家自己漂流过来的船的残骸。如果情境里第 1 天上午、玩家身上还带着海水的咸味，说明他刚醒不久，是踏上岛的第一个地点；可以暗示玩家狼狈的状态、衣服上的海水痕迹、以及看到自己的船变成这样的复杂情绪。如果已经过了几天，玩家是从别处探索回来再次见到这艘船——把感受调整为「重逢」或「凝视过往」，不要再写「刚醒来」。无论何时都不要替玩家下结论。",
        search_stages=[
            SearchStage(
                name="表面翻找",
                description="徒手在断裂的木板间、破布堆里、半埋的沙土上翻拣。容易拿到的小东西。",
                pool=[
                    LootEntry("cloth", weight=4, qty_min=1, qty_max=2),
                    LootEntry("iron_nail", weight=3, qty_min=1, qty_max=2),
                    LootEntry("driftwood", weight=3, qty_min=1, qty_max=2),
                    LootEntry("rope", weight=2),
                    LootEntry("seashell", weight=2),
                ],
                per_search_count=(2, 3),
                required_tools=[],
                time_minutes=10,
                fatigue=3,
            ),
            SearchStage(
                name="撬开船舱",
                description="用锐石/铁钉/木棒撬开钉死的船板和卡住的舱门，搜船舱内部。会找到水手随身带的小工具或私人物品。",
                pool=[
                    LootEntry("rusty_knife", weight=3),
                    LootEntry("fishing_line", weight=3),
                    LootEntry("fishing_hook", weight=2),
                    LootEntry("glass_bottle", weight=1),
                    LootEntry("iron_scrap", weight=3, qty_min=1, qty_max=2),
                    LootEntry("bottle_message", weight=1),  # 罕见剧情物
                ],
                per_search_count=(1, 2),
                required_tools=["sharp_stone", "rusty_knife", "club"],
                time_minutes=45,
                fatigue=12,
            ),
            SearchStage(
                name="彻底拆解",
                description="把整艘船拆光，取走龙骨、桅杆、所有木板。耗时极长，体力消耗大，结束后这里只剩沙地。",
                pool=[
                    LootEntry("wood_plank", weight=5, qty_min=4, qty_max=8),
                    LootEntry("long_branch", weight=3, qty_min=1, qty_max=3),
                    LootEntry("iron_nail", weight=3, qty_min=3, qty_max=8),
                    LootEntry("rope", weight=2, qty_min=1, qty_max=2),
                    LootEntry("cloth", weight=2, qty_min=1, qty_max=3),
                ],
                per_search_count=(3, 4),
                required_tools=["sharp_stone", "rusty_knife"],
                tool_strict=True,  # 拆龙骨需要真撬具/切割工具
                time_minutes=300,
                fatigue=40,
                consumes_landmark=True,
            ),
        ],
    ),
    LandmarkDef(
        id="fresh_spring",
        name="淡水泉",
        description="一股清澈的泉水从岩石间渗出，汇成一个小池塘。水面倒映着天空。",
        features=["可以直接饮用", "可以装水（需要容器）", "水边的泥土很软"],
        preferred_terrains=[Terrain.HILLS, Terrain.GRASS],
        near_terrain=Terrain.RIVER,
        radius=2,
        priority=90,
    ),
    LandmarkDef(
        id="coconut_grove",
        name="椰子林",
        description="一片高大的椰子树林。地上散落着掉落的椰子，有些还很新鲜。树冠很高，攀爬有风险。",
        features=["椰子可以采集", "需要破壳取椰肉和椰汁", "抬头看可能有野生鹦鹉"],
        preferred_terrains=[Terrain.JUNGLE],
        radius=3,
        priority=80,
    ),
    LandmarkDef(
        id="rocky_beach",
        name="岩石海滩",
        description="岩石裸露的海岸线，浪花拍打着布满藤壶的礁石。退潮时礁石间露出的水洼里有小鱼。",
        features=["退潮时可以捉小鱼", "礁石上能采到贝类", "潮汐会随时间变化"],
        preferred_terrains=[Terrain.BEACH],
        radius=3,
        priority=70,
    ),
    LandmarkDef(
        id="cliff_top",
        name="崖顶",
        description="岛上最高的一处海崖。风很大，下面是翻涌的海浪。视野极佳，能看到整个海岸线。",
        features=["可以瞭望远处的船", "夜里很冷", "攀爬需要小心"],
        preferred_terrains=[Terrain.MOUNTAIN, Terrain.CLIFF, Terrain.HILLS],
        radius=2,
        priority=85,
        arrival_context="这是岛上的至高点——玩家第一次能看到岛的全貌、海平线、远方有没有任何文明的迹象。是高峰时刻，描述应该有空间感和纵深感（风、视野、自己渺小、海平线远方）。",
        search_stages=[
            SearchStage(
                name="崖边礁缝和鸟窝",
                description="沿着崖顶边缘小心走一圈，检查礁石裂缝和海鸟的巢——海鸟经常在这里做窝。",
                pool=[
                    LootEntry("egg", weight=5, qty_min=1, qty_max=3),
                    LootEntry("feather", weight=4, qty_min=2, qty_max=5),
                    LootEntry("pebble", weight=2, qty_min=2, qty_max=4),
                    LootEntry("seashell", weight=2, qty_min=1, qty_max=3),
                ],
                per_search_count=(2, 3),
                required_tools=[],
                time_minutes=20,
                fatigue=8,
            ),
        ],
    ),
    LandmarkDef(
        id="abandoned_camp",
        name="废弃营地",
        description="一处被遗弃的简易营地。有过燃烧痕迹，几根烧黑的木桩立在地上，旁边是一个倒塌的草棚。已经很久没人来过了。",
        features=["可能有遗留物资", "能看出有人在此生活过", "营地下方藏着东西？"],
        preferred_terrains=[Terrain.GRASS, Terrain.HILLS],
        radius=2,
        priority=95,
        arrival_context="这强烈暗示岛上**曾经**有过别人——这是玩家以为自己是孤身一人之后的第一个不安信号。可以让描述带一丝悬念：那个人是谁？还在岛上吗？但不要直接给出答案。",
        search_stages=[
            SearchStage(
                name="围着营地走一圈",
                description="表面查看：火堆灰烬里、倒塌的草棚下、明显能看到的地方。",
                pool=[
                    LootEntry("dry_leaf", weight=3, qty_min=2, qty_max=4),
                    LootEntry("firewood", weight=3, qty_min=1, qty_max=3),
                    LootEntry("stick", weight=3, qty_min=2, qty_max=4),
                    LootEntry("rope", weight=2),
                    LootEntry("cloth", weight=2),
                ],
                per_search_count=(2, 3),
                required_tools=[],
                time_minutes=10,
                fatigue=3,
            ),
            SearchStage(
                name="挪开木桩与草棚",
                description="清理倒塌的草棚和烧黑的木桩，搜底下藏的东西。",
                pool=[
                    LootEntry("bone_knife", weight=2),
                    LootEntry("rusty_knife", weight=2),
                    LootEntry("clay", weight=3, qty_min=1, qty_max=2),
                    LootEntry("torch", weight=1),
                    LootEntry("salt", weight=2),
                    LootEntry("bottle_message", weight=1),
                ],
                per_search_count=(1, 2),
                required_tools=["club", "sharp_stone", "long_branch"],
                time_minutes=40,
                fatigue=10,
            ),
            SearchStage(
                name="挖掘营地下方",
                description="在原本火堆和草棚的位置往下挖。营地的主人可能藏了重要的东西。",
                pool=[
                    LootEntry("bone", weight=3, qty_min=1, qty_max=2),
                    LootEntry("rusty_knife", weight=2),
                    LootEntry("iron_scrap", weight=2, qty_min=1, qty_max=3),
                    LootEntry("glass_bottle", weight=2),
                    LootEntry("bottle_message", weight=2),  # 重要剧情物
                ],
                per_search_count=(1, 2),
                required_tools=["sharp_stone", "long_branch", "club"],
                time_minutes=120,
                fatigue=25,
                consumes_landmark=True,
            ),
        ],
    ),
    LandmarkDef(
        id="cave",
        name="山洞",
        description="一处嵌在山壁里的洞穴入口。洞口被藤蔓半遮住，里面黑漆漆的，能感受到一股凉意。",
        features=["里面可能有东西栖息", "可以躲雨避寒", "深处需要火把"],
        preferred_terrains=[Terrain.MOUNTAIN, Terrain.HILLS],
        radius=1,
        priority=75,
        tags=["shelter"],
        arrival_context="山洞是岛上少有的真正庇护所——第一次进去的感受应该强调黑暗、凉意、以及某种「这里藏着东西」的直觉。不要直接告诉玩家里面有什么，但可以暗示洞壁上的痕迹、气味或声音。",
        search_stages=[
            SearchStage(
                name="洞口附近查看",
                description="在洞口几步之内、还有光亮的地方摸索——地面的东西、洞壁缝隙里的小玩意。",
                pool=[
                    LootEntry("feather", weight=3, qty_min=1, qty_max=3),
                    LootEntry("bone", weight=3, qty_min=1, qty_max=2),
                    LootEntry("pebble", weight=2, qty_min=2, qty_max=4),
                    LootEntry("clay", weight=3, qty_min=1, qty_max=2),
                    LootEntry("tinder", weight=2, qty_min=1, qty_max=2),
                ],
                per_search_count=(2, 3),
                required_tools=[],
                time_minutes=10,
                fatigue=3,
            ),
            SearchStage(
                name="借着火把深入",
                description="举着火把走进黑暗处——洞壁上有老营地痕迹，角落里有人类留下的遗物。需要光源（火把）。",
                pool=[
                    LootEntry("rusty_knife", weight=2),
                    LootEntry("bone_knife", weight=1),
                    LootEntry("cloth", weight=3, qty_min=1, qty_max=2),
                    LootEntry("rope", weight=2),
                    LootEntry("iron_scrap", weight=2, qty_min=1, qty_max=2),
                    LootEntry("bottle_message", weight=1),
                ],
                per_search_count=(1, 2),
                required_tools=["torch"],
                tool_strict=True,
                time_minutes=60,
                fatigue=15,
            ),
        ],
    ),
    LandmarkDef(
        id="mangrove",
        name="红树林沼泽",
        description="一片潮湿的沼泽，红树根盘根错节地伸进浑浊的水里。空气闷热，蚊虫飞舞。",
        features=["可能有螃蟹和小鱼", "泥土松软陷脚", "可能有蛇"],
        preferred_terrains=[Terrain.SWAMP],
        radius=3,
        priority=60,
        search_stages=[
            SearchStage(
                name="蹚水翻找",
                description="踩进浑浊的沼泽水里，在红树根之间拨找——退潮时常有螃蟹躲在这里。",
                pool=[
                    LootEntry("crab", weight=5, qty_min=1, qty_max=2),
                    LootEntry("clam", weight=3, qty_min=1, qty_max=3),
                    LootEntry("mud", weight=3, qty_min=2, qty_max=3),
                    LootEntry("vine", weight=3, qty_min=1, qty_max=3),
                    LootEntry("stick", weight=2, qty_min=1, qty_max=2),
                ],
                per_search_count=(2, 3),
                required_tools=[],
                time_minutes=20,
                fatigue=8,
            ),
            SearchStage(
                name="挖掘根部淤泥",
                description="用工具深挖红树根下的淤泥——那里积存了各种冲入沼泽的东西。",
                pool=[
                    LootEntry("clay", weight=4, qty_min=2, qty_max=3),
                    LootEntry("iron_scrap", weight=2, qty_min=1, qty_max=2),
                    LootEntry("bone", weight=2, qty_min=1, qty_max=2),
                    LootEntry("seashell", weight=3, qty_min=2, qty_max=4),
                ],
                per_search_count=(2, 3),
                required_tools=["long_branch", "stick", "bone"],
                time_minutes=40,
                fatigue=18,
            ),
        ],
    ),
    LandmarkDef(
        id="lookout_hill",
        name="了望丘",
        description="一座视野开阔的小丘陵。从这里能看到下方大片的丛林和海岸线。",
        features=["视野开阔", "没有遮蔽", "风很大"],
        preferred_terrains=[Terrain.HILLS],
        radius=2,
        priority=60,
    ),
    LandmarkDef(
        id="deep_jungle_clearing",
        name="密林空地",
        description="丛林深处一片意外的空地。中央有一棵巨大的、似乎被雷劈过的枯树。地面铺满落叶。",
        features=["可能有特殊动物经过", "枯树可能有树洞", "阳光从空地透下来"],
        preferred_terrains=[Terrain.DEEP_JUNGLE],
        radius=2,
        priority=70,
        search_stages=[
            SearchStage(
                name="落叶堆里翻找",
                description="拨开厚厚的落叶堆，查看地面——长期积累的落叶是天然储藏室。",
                pool=[
                    LootEntry("dry_leaf", weight=4, qty_min=3, qty_max=5),
                    LootEntry("seeds", weight=3, qty_min=2, qty_max=4),
                    LootEntry("nuts", weight=3, qty_min=1, qty_max=3),
                    LootEntry("berries", weight=2, qty_min=1, qty_max=2),
                    LootEntry("vine", weight=2, qty_min=1, qty_max=3),
                ],
                per_search_count=(2, 3),
                required_tools=[],
                time_minutes=15,
                fatigue=4,
            ),
            SearchStage(
                name="检查枯树树洞",
                description="绕到枯树后面，检查低处的树洞——雷击劈开的空腔可能藏着东西，也可能住着动物。",
                pool=[
                    LootEntry("egg", weight=3, qty_min=1, qty_max=3),
                    LootEntry("feather", weight=3, qty_min=2, qty_max=4),
                    LootEntry("bone", weight=2, qty_min=1, qty_max=2),
                    LootEntry("wild_fruit", weight=2, qty_min=1, qty_max=3),
                    LootEntry("tinder", weight=2, qty_min=1, qty_max=2),
                ],
                per_search_count=(1, 2),
                required_tools=[],
                time_minutes=20,
                fatigue=6,
            ),
        ],
    ),
    LandmarkDef(
        id="shipwreck_far",
        name="远处的沉船",
        description="退潮时能看到礁石间露出半截桅杆——是另一艘沉船。涨潮时它沉没在浅水里。",
        features=["可以游过去探索（危险）", "可能有贵重物资", "附近水里有鱼群"],
        preferred_terrains=[Terrain.SHALLOW_WATER, Terrain.BEACH],
        radius=2,
        priority=80,
        arrival_context="这是一艘不同于玩家自己那艘船的另一艘沉船，暗示这片海域并不是第一次出事。退潮时才能靠近，充满危险感——描述可以强调潮汐、礁石上的海藻、和隐约可见的船身轮廓。",
        search_stages=[
            SearchStage(
                name="退潮时徒手摸索",
                description="趁退潮在礁石间拨找——船体周围散落着被海水冲出来的杂物。必须在浅水里蹚着走。",
                pool=[
                    LootEntry("rope", weight=3, qty_min=1, qty_max=2),
                    LootEntry("cloth", weight=3, qty_min=1, qty_max=2),
                    LootEntry("iron_nail", weight=3, qty_min=2, qty_max=4),
                    LootEntry("driftwood", weight=3, qty_min=1, qty_max=3),
                    LootEntry("seashell", weight=2, qty_min=2, qty_max=4),
                    LootEntry("fishing_hook", weight=2),
                ],
                per_search_count=(2, 3),
                required_tools=[],
                time_minutes=30,
                fatigue=12,
            ),
            SearchStage(
                name="撬开舱门残骸",
                description="用工具把半开着的舱门撬开，伸手进去够——水下部分依然浸泡着，里面的东西被海水浸过。",
                pool=[
                    LootEntry("rusty_knife", weight=3),
                    LootEntry("glass_bottle", weight=2),
                    LootEntry("iron_scrap", weight=3, qty_min=1, qty_max=3),
                    LootEntry("fishing_line", weight=2),
                    LootEntry("bottle_message", weight=2),
                    LootEntry("salt", weight=2, qty_min=1, qty_max=2),
                ],
                per_search_count=(1, 2),
                required_tools=["sharp_stone", "rusty_knife", "iron_scrap"],
                time_minutes=60,
                fatigue=22,
            ),
        ],
    ),
    LandmarkDef(
        id="message_in_bottle",
        name="漂流瓶",
        description="一只漂流瓶搁浅在沙滩上。里面似乎有一张卷起的纸条。",
        features=["可以打开看", "是别的落难者留下的？", "玻璃瓶本身也有用"],
        preferred_terrains=[Terrain.BEACH],
        radius=1,
        priority=70,
        arrival_context="一个温暖一点的「有过别人」暗示——在大海上的某个地方有/有过另一个像玩家一样的人。可以让描述带一点孤独中的微妙连接感（但纸条具体写什么由后续动作决定，这里不要剧透）。",
    ),
    LandmarkDef(
        id="bone_pile",
        name="骸骨堆",
        description="一堆白骨——看不出是人是兽，旁边还有几片破布和一把锈刀。",
        features=["这里曾发生过什么", "锈刀也许还能用", "让人不寒而栗"],
        preferred_terrains=[Terrain.JUNGLE, Terrain.DEEP_JUNGLE],
        radius=1,
        priority=65,
        arrival_context="另一个「岛上有过别人」的强烈线索，且更黑暗——某人在这里死了。描述要克制、不要血腥，但要让玩家感到一阵凉意。可以暗示死亡发生的方式（病？野兽？还是别的？），但不要给出确定答案。",
        search_stages=[
            SearchStage(
                name="检查表面",
                description="表面拣视，能看到的几样东西。",
                pool=[
                    LootEntry("rusty_knife", weight=4),
                    LootEntry("cloth", weight=4, qty_min=1, qty_max=2),
                    LootEntry("bone", weight=4, qty_min=1, qty_max=3),
                ],
                per_search_count=(2, 3),
                required_tools=[],
                time_minutes=5,
                fatigue=2,
            ),
            SearchStage(
                name="拨开骸骨",
                description="把白骨堆拨开搜下面。需要勇气，也需要一根趁手的工具。",
                pool=[
                    LootEntry("bone_knife", weight=3),
                    LootEntry("bone", weight=4, qty_min=2, qty_max=4),
                    LootEntry("iron_scrap", weight=2),
                    LootEntry("glass_bottle", weight=1),
                    LootEntry("bottle_message", weight=2),  # 死者的遗书
                ],
                per_search_count=(1, 2),
                required_tools=["long_branch", "club", "sharp_stone", "rusty_knife"],
                time_minutes=20,
                fatigue=8,
                consumes_landmark=True,
            ),
        ],
    ),
    LandmarkDef(
        id="banana_grove",
        name="香蕉林",
        description="一小片野生香蕉林，长着不少黄绿相间的果实。",
        features=["可以摘香蕉", "香蕉容易腐败", "附近可能有猴子"],
        preferred_terrains=[Terrain.JUNGLE],
        radius=2,
        priority=70,
    ),
    LandmarkDef(
        id="tide_pool",
        name="潮汐池",
        description="退潮在岩石间留下的小水池，里面困着各种海洋小生物。",
        features=["能徒手抓小鱼小虾", "水是咸的", "涨潮就会消失"],
        preferred_terrains=[Terrain.BEACH],
        radius=1,
        priority=55,
    ),
    LandmarkDef(
        id="old_tree",
        name="老树",
        description="一棵不知活了多少年的巨树，树干粗到三个人都抱不过来。低处的枝桠几乎触地。",
        features=["可以攀爬", "可以作为方位标记", "树洞里可能有东西"],
        preferred_terrains=[Terrain.JUNGLE, Terrain.DEEP_JUNGLE, Terrain.GRASS],
        radius=1,
        priority=65,
        search_stages=[
            SearchStage(
                name="低处枝桠和树洞",
                description="绕着巨树走一圈，检查低处的树洞和根部——老树总是藏着东西。",
                pool=[
                    LootEntry("egg", weight=3, qty_min=1, qty_max=2),
                    LootEntry("nuts", weight=3, qty_min=1, qty_max=3),
                    LootEntry("wild_fruit", weight=2, qty_min=1, qty_max=2),
                    LootEntry("feather", weight=3, qty_min=1, qty_max=3),
                    LootEntry("vine", weight=3, qty_min=2, qty_max=4),
                    LootEntry("tinder", weight=2, qty_min=1, qty_max=2),
                ],
                per_search_count=(2, 3),
                required_tools=[],
                time_minutes=15,
                fatigue=4,
            ),
            SearchStage(
                name="攀上低枝俯瞰",
                description="爬上最低的那根粗枝，站上去能看到不少——也能够到上面树冠里藏的东西。",
                pool=[
                    LootEntry("egg", weight=4, qty_min=2, qty_max=4),
                    LootEntry("coconut", weight=2, qty_min=1, qty_max=2),
                    LootEntry("wild_fruit", weight=3, qty_min=1, qty_max=3),
                    LootEntry("long_branch", weight=2, qty_min=1, qty_max=2),
                ],
                per_search_count=(1, 2),
                required_tools=[],
                time_minutes=25,
                fatigue=10,
            ),
        ],
    ),
    LandmarkDef(
        id="cliff_shelter",
        name="崖底小屋",
        description="靠着崖壁的一个天然凹陷，可以遮风挡雨。地上有几块平整的石头，像是被人摆放过。",
        features=["天然庇护所", "可以生火", "避雨好地方"],
        preferred_terrains=[Terrain.CLIFF, Terrain.HILLS],
        radius=1,
        priority=75,
        tags=["shelter"],
        arrival_context="这里是岛上最好的天然庇护所，但石头的摆放方式暗示曾经有人专门在这里生活过——不是随机的，是刻意的。描述重点放在「曾有人在这里留下生活痕迹」的感受：凹陷背后的烟熏黑迹，石头的摆放角度，某种人工改造的痕迹。",
        search_stages=[
            SearchStage(
                name="查看石头摆放和地面",
                description="仔细看石头的缝隙和地面灰烬——人刻意摆放石头往往是为了藏东西或做记号。",
                pool=[
                    LootEntry("firewood", weight=3, qty_min=1, qty_max=3),
                    LootEntry("dry_leaf", weight=3, qty_min=2, qty_max=4),
                    LootEntry("tinder", weight=3, qty_min=1, qty_max=2),
                    LootEntry("pebble", weight=2, qty_min=2, qty_max=4),
                    LootEntry("clay", weight=2, qty_min=1, qty_max=2),
                ],
                per_search_count=(2, 3),
                required_tools=[],
                time_minutes=10,
                fatigue=3,
            ),
            SearchStage(
                name="挪开石头搜底部",
                description="把那几块明显被人摆过的石头挪开，看看底下藏着什么——值得搬动的东西通常被压在石头下面。",
                pool=[
                    LootEntry("rusty_knife", weight=2),
                    LootEntry("bone_knife", weight=1),
                    LootEntry("salt", weight=3, qty_min=1, qty_max=2),
                    LootEntry("glass_bottle", weight=2),
                    LootEntry("iron_nail", weight=2, qty_min=1, qty_max=3),
                    LootEntry("bottle_message", weight=2),
                ],
                per_search_count=(1, 2),
                required_tools=[],
                time_minutes=30,
                fatigue=10,
                consumes_landmark=True,
            ),
        ],
    ),
    LandmarkDef(
        id="salt_flat",
        name="盐池",
        description="海边一处低洼，海水积在这里被太阳晒过留下白色的盐结晶。",
        features=["可以收集盐", "盐能腌制食物", "走路硌脚"],
        preferred_terrains=[Terrain.BEACH],
        radius=2,
        priority=60,
    ),
    LandmarkDef(
        id="fire_pit",
        name="黑色焦痕",
        description="地上一圈烧黑的痕迹，似乎以前有人在这里生过火。周围有几根半烧的木头。",
        features=["有过火堆痕迹", "说明有人来过", "可以重新利用"],
        preferred_terrains=[Terrain.GRASS, Terrain.BEACH, Terrain.HILLS],
        radius=1,
        priority=50,
    ),
    LandmarkDef(
        id="cliff_path",
        name="悬崖小径",
        description="一条沿海崖蜿蜒的危险小径。一边是岩壁，一边是几十米下的海浪。",
        features=["通往崖顶的捷径", "雨天极危险", "路上能拣到鸟蛋"],
        preferred_terrains=[Terrain.HILLS, Terrain.CLIFF],
        radius=2,
        priority=60,
    ),
]


def place_landmarks(island: Island) -> list[PlacedLandmark]:
    """把地标"放置"到岛上：每个 def 找一个匹配的格子。"""
    placed: list[PlacedLandmark] = []
    sorted_defs = sorted(LANDMARK_DEFS, key=lambda d: -d.priority)

    for d in sorted_defs:
        candidates: list[tuple[int, int, int]] = []  # (x, y, score)
        for y in range(2, island.height - 2):
            for x in range(2, island.width - 2):
                t = tile_at(island, x, y)
                if t not in d.preferred_terrains:
                    continue
                if d.near_terrain is not None:
                    near = False
                    for dy in range(-3, 4):
                        for dx in range(-3, 4):
                            if tile_at(island, x + dx, y + dy) == d.near_terrain:
                                near = True
                                break
                        if near:
                            break
                    if not near:
                        continue
                # 与已放置地标保持距离
                too_close = False
                for p in placed:
                    if (p.x - x) ** 2 + (p.y - y) ** 2 < (max(p.radius, d.radius) + 5) ** 2:
                        too_close = True
                        break
                if too_close:
                    continue
                # 偏好海岸线
                coastal = 0
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    nt = tile_at(island, x + dx, y + dy)
                    if nt in (Terrain.OCEAN, Terrain.SHALLOW_WATER, Terrain.RIVER):
                        coastal += 1
                candidates.append((x, y, coastal))
        if not candidates:
            continue
        candidates.sort(key=lambda c: -c[2])
        x, y, _ = candidates[0]
        placed.append(
            PlacedLandmark(
                id=d.id,
                name=d.name,
                description=d.description,
                features=d.features,
                preferred_terrains=d.preferred_terrains,
                radius=d.radius,
                priority=d.priority,
                x=x,
                y=y,
                near_terrain=d.near_terrain,
                arrival_context=d.arrival_context,
                search_stages=d.search_stages,
                tags=d.tags,
            )
        )
    return placed


def landmark_at(landmarks: list[PlacedLandmark], x: int, y: int) -> PlacedLandmark | None:
    for lm in landmarks:
        if (lm.x - x) ** 2 + (lm.y - y) ** 2 <= lm.radius * lm.radius:
            return lm
    return None


def nearest_landmarks(
    landmarks: list[PlacedLandmark], x: int, y: int, n: int
) -> list[PlacedLandmark]:
    return sorted(
        landmarks, key=lambda lm: math.hypot(lm.x - x, lm.y - y)
    )[:n]
