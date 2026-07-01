// 自动生成，请勿手动修改。运行 scripts/generate_item_map.py 重新生成
// 物品 id → 中文名称映射表

const ITEM_ZH = {
  // 食物
  coconut: '椰子',
  coconut_meat: '椰肉',
  small_fish: '小鱼',
  fish_raw: '生鱼',
  fish_cooked: '熟鱼',
  crab: '螃蟹',
  clam: '蛤蜊',
  shellfish: '贝类',
  banana: '香蕉',
  wild_fruit: '野果',
  berries: '浆果',
  seeds: '种子',
  nuts: '坚果',
  meat_raw: '生肉',
  meat_cooked: '熟肉',
  egg: '蛋',

  // 水
  coconut_water: '椰汁',
  fresh_water: '淡水',
  water_in_shell: '装水的椰壳',

  // 燃料
  coconut_fiber: '椰壳纤维',
  dry_leaf: '干树叶',
  tinder: '火绒',
  firewood: '柴火',

  // 原料
  coconut_shell: '椰子壳',
  seashell: '贝壳',
  stone: '石头',
  large_stone: '大石头',
  pebble: '小石子',
  wood: '木头',
  wood_plank: '木板',
  driftwood: '浮木',
  stick: '树枝',
  long_branch: '长树枝',
  vine: '藤蔓',
  rope: '绳子',
  leaf: '树叶',
  mud: '泥土',
  clay: '黏土',
  cloth: '布条',
  iron_nail: '铁钉',
  iron_scrap: '铁片',

  // 工具
  sharp_stone: '锐石',
  rusty_knife: '锈刀',
  bone_knife: '骨刀',
  spear: '矛',
  club: '木棒',
  fishing_line: '鱼线',
  fishing_hook: '鱼钩',
  torch: '火把',
  cup: '杯子',
  bowl: '碗',
  basket: '篮子',
  glass_bottle: '玻璃瓶',

  // 杂物
  salt_water: '咸水',
  salt: '盐',
  feather: '羽毛',
  bone: '骨头',
  bottle_message: '瓶中信',

  // 农业
  banana_seedling: '香蕉幼苗',

};

// 为了兼容，如果 game.js 期望的是 ITEM_ZH 对象
// 确保在加载 game.js 之前加载此文件
