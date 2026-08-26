export type MuseumDetail = {
  id: string;
  name: string;
  subtitle: string;
  color: string;
  note: string;
};

export type MuseumModelAsset = {
  url: string;
  sourceLabel: string;
  sourceUrl: string;
  scale: number;
  rotation?: [number, number, number];
  position?: [number, number, number];
  exposure?: number;
};

export type MuseumCatalogItem = {
  id: string;
  name: string;
  type: string;
  accent: string;
  defaultOrganelle: string;
  modelAsset: MuseumModelAsset;
  thumbnail: string;
  era: string;
  dynasty: string;
  museum: string;
  museumAbroad: boolean;
  intro: string;
  story?: string;
  qa?: Array<{ q: string; a: string }>;
  origin: string;
  organelles: MuseumDetail[];
};

export const museumCatalog: MuseumCatalogItem[] = [
  {
    id: "owlZun",
    name: "猫头鹰尊",
    type: "商代青铜酒器",
    accent: "#5a7a4a",
    defaultOrganelle: "body",
    modelAsset: {
      url: "/museum/models/owl_zun_wine_vessel_13th-12th_century_bce.glb",
      sourceLabel: "Minneapolis Institute of Art",
      sourceUrl: "https://sketchfab.com/3d-models/ca77ae1351ca4b1c9a7d403e09e1c4af",
      scale: 8,
      rotation: [0, 0, 0],
      exposure: 1.1
    },
    thumbnail: "/museum/thumbnails/owlZun.jpg",
    era: "商",
    dynasty: "商代晚期 · 约公元前13-12世纪",
    museum: "美国 · 明尼阿波利斯艺术博物馆",
    museumAbroad: true,
    intro: "猫头鹰尊取猫头鹰之形铸造，是商代青铜礼器中罕见的写实动物造型，鸮在当时被视为通天神鸟。",
    story: "三千多年前的某个夜晚，商朝的工匠正在为一场盛大的祭祀做准备。他没有铸造常见的方鼎或圆尊，而是选择了一只猫头鹰的形象——在那个崇尚鬼神的年代，这种昼伏夜出、目光如炬的猛禽，被认为能在黑暗中看见凡人看不见的东西，是沟通生死、连接天地的神鸟。\n\n于是这只青铜鸮就这样站立了三千年：昂首挺胸，双翅收拢，浑身布满狰狞的饕餮纹。它曾盛满祭祀的美酒，见证过商王对祖先与神灵的虔诚。而今天，它静静站在大洋彼岸的博物馆里，依然用那双圆睁的眼睛，凝视着每一个走近它的人。",
    qa: [
      {
        q: "为什么商朝人偏偏选猫头鹰，而不是别的鸟？",
        a: "在商代，猫头鹰（鸮）是被崇拜的神鸟，而非后世认为的不祥之物。它夜间活动、双目如炬，被认为能洞察幽冥、沟通天地。商人尚鬼神，自然把这种神秘的猛禽奉为通灵的象征。"
      },
      {
        q: "这只青铜鸮到底是用来做什么的？",
        a: "它是一件盛酒的礼器（尊），但不是日常喝酒用的——而是专门用于祭祀。商人相信通过献酒可以与祖先、神灵沟通，越是重要的祭祀，礼器越讲究。"
      },
      {
        q: "为什么猫头鹰从「神鸟」变成了「不祥之鸟」？",
        a: "商代尊鸮，但到了周代以后，礼制和观念逐渐改变，加上猫头鹰夜鸣的习性，民间渐渐把它和死亡、灾祸联系起来。同一种鸟，在不同时代被赋予了截然相反的文化含义。"
      }
    ],
    origin: "河南安阳·殷墟出土",
    organelles: [
      {
        id: "body",
        name: "器身",
        subtitle: "鸮形主体",
        color: "#5a7a4a",
        note: "器身呈猫头鹰站立状，昂首挺胸，双翅并拢贴于身侧。鸮在商代被视为神鸟，具有沟通天地的象征意义。"
      },
      {
        id: "lid",
        name: "器盖",
        subtitle: "可拆卸鸮首",
        color: "#7a9a5a",
        note: "猫头鹰的头部即为器盖，可以拆卸。盖上装饰有精细的羽毛纹路，展现了商代工匠对自然观察的细致入微。"
      },
      {
        id: "pattern",
        name: "纹饰",
        subtitle: "饕餮与云雷纹",
        color: "#4a6a3a",
        note: "器身遍布繁密的饕餮纹和云雷纹，层次分明。这种复杂的纹饰体系是商代晚期青铜器的典型特征。"
      }
    ]
  },
  {
    id: "sanxingdui",
    name: "三星堆青铜面具",
    type: "古蜀青铜器",
    accent: "#2a7a6a",
    defaultOrganelle: "face",
    modelAsset: {
      url: "/museum/models/sanxingdui-3-mask.glb",
      sourceLabel: "Sketchfab",
      sourceUrl: "https://sketchfab.com/3d-models/a899126df9f546528a09871305f5214e",
      scale: 0.9,
      rotation: [0, 0, 0],
      exposure: 1.1
    },
    thumbnail: "/museum/thumbnails/sanxingdui.jpg",
    era: "商",
    dynasty: "商代 · 约公元前12-11世纪",
    museum: "中国 · 三星堆博物馆",
    museumAbroad: false,
    intro: "三星堆青铜面具造型奇诡，与中原青铜器风格迥异，揭示了一个失落的古蜀文明，至今充满未解之谜。",
    story: "1986年的夏天，四川广汉的两个砖厂工人在挖土时，一锄头下去，挖出了一个改写中国历史的洞——三星堆祭祀坑。当青铜面具从泥土中显露时，所有人都愣住了：突出的眼球、招风的大耳、神秘的微笑，这副面孔不属于任何已知的中原文明。\n\n几千年前，在远离黄河流域的成都平原，曾有一个高度发达的古蜀王国。他们崇拜眼睛、铸造神树、留下了与商周截然不同的青铜文明，然后又毫无征兆地消失了。没有文字记载，没有去向之谜的答案。这副面具沉默地凝视了三千年，至今没有人能完全读懂它眼神里的秘密。",
    qa: [
      {
        q: "为什么三星堆的眼睛要做得那么夸张？",
        a: "学界推测这与古蜀先王「蚕丛纵目」的传说有关——传说古蜀第一代王蚕丛的眼睛是凸出的。突出的眼球可能象征着超凡的视力，能看见凡人看不见的神灵世界。"
      },
      {
        q: "三星堆和中原的商朝是什么关系？",
        a: "这正是最大的谜。三星堆与商朝大致同期，部分器物（如青铜尊、玉璋）能看到中原文化影响，但面具、神树、大立人等核心造型完全是本土独创，风格迥异。两者既有交流又高度独立。"
      },
      {
        q: "古蜀文明后来去哪了？",
        a: "至今没有定论。三星堆繁荣后突然衰落，没有留下文字，去向成谜。有人猜测是洪水、战争或迁徙。它像一个突然亮起又熄灭的文明之光，留给后人无尽的想象。"
      }
    ],
    origin: "四川广汉·三星堆遗址",
    organelles: [
      {
        id: "face",
        name: "面部",
        subtitle: "纵目巨耳",
        color: "#2a7a6a",
        note: "面具最震撼之处是突出的眼球（纵目）和夸张的大耳。学者推测这可能与古蜀先王蚕丛「纵目」的传说有关，象征超凡的视听能力。"
      },
      {
        id: "ears",
        name: "双耳",
        subtitle: "招风巨耳",
        color: "#4a9a8a",
        note: "面具的双耳向两侧极度夸张地展开，呈招风状。这种对眼、耳的强调，可能反映古蜀人对「看见」与「听见」神灵的崇拜。"
      },
      {
        id: "craft",
        name: "铸造工艺",
        subtitle: "古蜀青铜术",
        color: "#1a5a4a",
        note: "三星堆青铜器采用分铸法，再以铆接、嵌铸等方式组合，工艺水平极高，说明古蜀拥有独立而成熟的青铜铸造体系。"
      }
    ]
  },
  {
    id: "shengding",
    name: "青铜鼎",
    type: "春秋礼器",
    accent: "#6d5a3a",
    defaultOrganelle: "body",
    modelAsset: {
      url: "/museum/models/shengding_food_vessel_around_575_bce.glb",
      sourceLabel: "Minneapolis Institute of Art",
      sourceUrl: "https://sketchfab.com/3d-models/8f45c5ab58794f4faca0c242f89fdf22",
      scale: 5,
      rotation: [0, 0, 0],
      exposure: 1.1
    },
    thumbnail: "/museum/thumbnails/shengding.jpg",
    era: "春秋",
    dynasty: "春秋时期 · 约公元前575年",
    museum: "美国 · 明尼阿波利斯艺术博物馆",
    museumAbroad: true,
    intro: "鼎是中国古代最重要的礼器，象征国家政权与王权威严，「问鼎中原」一词正源于此。",
    story: "公元前606年，楚庄王率军北上，陈兵周王室的边境，派人去问九鼎的大小轻重。这一问，问出了千古名句「问鼎中原」——因为九鼎是天子权力的象征，问鼎，就是觊觎天下。\n\n在那个年代，鼎不只是煮肉的锅。它是最高规格的礼器，是国家与王权的化身。天子九鼎、诸侯七鼎、大夫五鼎，鼎的数量直接对应身份等级，谁也不能僭越。一件青铜鼎静静矗立，三足撑地，双耳朝天，承载的不是食物，而是一整套维系了数百年的礼制秩序。",
    qa: [
      {
        q: "鼎到底是锅还是礼器？",
        a: "两者都是。鼎最初是煮肉的炊具，但在商周时期逐渐演变为祭祀和礼仪用器。越是重要的场合，用鼎越讲究。它从「实用器」升级成了「身份和权力的象征」。"
      },
      {
        q: "「一言九鼎」「问鼎中原」都和它有关吗？",
        a: "是的。因为鼎象征国家政权，所以衍生出大量成语：「问鼎」指图谋天下，「一言九鼎」形容说话分量重，「鼎力相助」表示全力支持。鼎早已融入汉语的血脉。"
      },
      {
        q: "为什么鼎是三只脚？",
        a: "三足是最稳定的支撑结构——三点确定一个平面，不会晃。这样鼎能稳稳架在火上加热。「鼎足而立」这个成语正是来自它的三足造型，比喻三方势力均衡对峙。"
      }
    ],
    origin: "中原地区·诸侯国铸造",
    organelles: [
      {
        id: "body",
        name: "鼎身",
        subtitle: "圆腹容器",
        color: "#6d5a3a",
        note: "鼎身为圆形深腹，用于烹煮牛羊等祭品。鼎的大小和数量直接反映拥有者的身份等级。"
      },
      {
        id: "legs",
        name: "三足",
        subtitle: "承重支撑",
        color: "#8a7a5a",
        note: "三足鼎立的结构让鼎可以直接架在火上加热，是最早的「炊具」之一。足部造型从商代的锥足演变为春秋的蹄足。"
      },
      {
        id: "ears",
        name: "双耳",
        subtitle: "提举把手",
        color: "#5a4a2a",
        note: "双耳对称立于鼎口两侧，用于穿插横杠搬运。大型鼎重达数百公斤，需要多人协力抬举。"
      }
    ]
  },
  {
    id: "terracotta",
    name: "兵马俑",
    type: "秦代陶俑",
    accent: "#8a5a4a",
    defaultOrganelle: "head",
    modelAsset: {
      url: "/museum/models/terracotta_warrior.glb",
      sourceLabel: "Terracotta Warrior 3D Scan",
      sourceUrl: "https://sketchfab.com/3d-models/8fd9421a512745ddbe6abb31c1425017",
      scale: 2.6,
      rotation: [0, 0, 0],
      exposure: 1.1
    },
    thumbnail: "/museum/thumbnails/terracotta.jpg",
    era: "秦",
    dynasty: "秦代 · 约公元前210年",
    museum: "中国 · 秦始皇帝陵博物院",
    museumAbroad: false,
    intro: "兵马俑是秦始皇的地下军队，被誉为「世界第八大奇迹」，每一尊俑的面容都独一无二。",
    story: "公元前246年，13岁的嬴政即位，就开始为自己修建陵墓。三十多年后，他统一了六国，成为始皇帝，而他的地下军队也已初具规模——数千名陶土武士，按真实军阵列队，面朝东方，守卫着这位千古一帝的永眠。\n\n最令人震撼的不是数量，而是细节：每一尊俑的脸都不一样。有的年轻，有的沧桑，有的紧抿嘴唇，有的若有所思。学者相信，工匠是以真实的秦军将士为原型，一个一个塑造出来的。两千年后，当我们与一尊兵马俑对视，看见的或许正是某个真实存在过的秦代士兵的脸。",
    qa: [
      {
        q: "兵马俑真的每一个都不一样吗？",
        a: "是的。已出土的数千尊俑中，面容、发型、表情、身高各不相同，没有两个完全一样。这种「千人千面」的写实程度，在古代雕塑中极为罕见，很可能是以真人为原型塑造的。"
      },
      {
        q: "兵马俑原本是彩色的吗？",
        a: "是的！它们出土时身上有鲜艳的彩绘——红、绿、紫、蓝。但接触空气后，颜料在几分钟内迅速氧化卷曲脱落。我们现在看到的灰褐色，并不是它本来的样子。"
      },
      {
        q: "为什么兵马俑都朝向东方？",
        a: "秦国位于西方，统一前的六国都在东方。让军队面朝东方，既是为了防范东方六国的亡魂，也象征始皇帝对东方疆土的永久掌控——即使在地下，也要镇守天下。"
      }
    ],
    origin: "陕西西安·秦始皇陵",
    organelles: [
      {
        id: "head",
        name: "头部",
        subtitle: "千人千面",
        color: "#8a5a4a",
        note: "兵马俑最令人惊叹之处在于，每一尊俑的五官、表情、发型都各不相同。学者认为这些可能是以真实士兵为原型塑造的。"
      },
      {
        id: "armor",
        name: "铠甲",
        subtitle: "军事装备",
        color: "#7a4a3a",
        note: "铠甲的样式和精细程度反映了秦军严格的等级制度。将军俑的铠甲最为华丽，普通士兵则相对简朴。"
      },
      {
        id: "hands",
        name: "双手",
        subtitle: "握持兵器",
        color: "#9a6a5a",
        note: "俑的双手呈握持状，原本持有真实的青铜兵器。部分出土的青铜剑经过两千多年仍然锋利如新。"
      }
    ]
  },
  {
    id: "tangHorse",
    name: "唐三彩马",
    type: "唐代彩陶",
    accent: "#a8742a",
    defaultOrganelle: "body",
    modelAsset: {
      url: "/museum/models/tang_dynasty_ceramic_horse.glb",
      sourceLabel: "sharkbitestudios (Sketchfab)",
      sourceUrl: "https://sketchfab.com/3d-models/3eca558da9374f518c58748e4ba76d15",
      scale: 1.6,
      rotation: [0, 0, 0],
      exposure: 1.15
    },
    thumbnail: "/museum/thumbnails/tangHorse.jpg",
    era: "唐",
    dynasty: "唐代 · 公元7-9世纪",
    museum: "（私人复刻 · 原型为各地馆藏唐三彩）",
    museumAbroad: false,
    intro: "唐三彩是唐代盛行的低温彩釉陶器，以黄、绿、白三色为主，色彩绚烂，是盛唐气象的鲜活写照。",
    story: "盛唐的长安，是当时世界上最繁华的城市。来自西域的商队牵着骏马、骆驼，沿着丝绸之路络绎而来。唐人爱马，尤爱这些来自西域的高大良驹——它们是身份、力量与开放胸襟的象征。\n\n于是工匠把这份热爱烧进了陶土里。唐三彩马膘肥体壮，黄褐的釉色像阳光下的皮毛，绿色的鞍鞯华丽夺目。釉料在窑火中自然流淌交融，每一匹马的色彩都独一无二。它不是冷冰冰的陪葬品，而是一个自信、开放、生机勃勃的时代，留给我们最鲜活的一抹色彩。",
    qa: [
      {
        q: "唐三彩真的只有三种颜色吗？",
        a: "不是。「三彩」是虚指，意思是「多彩」。实际常见黄、绿、白、褐、蓝等多色。其中蓝色最名贵，因为钴料要从西域进口，所以有「三彩加蓝，价值连城」的说法。"
      },
      {
        q: "唐三彩是用来做什么的？",
        a: "主要是陪葬用的明器（冥器），随墓主人下葬。因为是低温釉陶，质地较脆、不防水，并不适合日常使用。它反映的是唐人「事死如事生」的观念——把生前的繁华带入地下。"
      },
      {
        q: "为什么唐朝人这么爱马？",
        a: "马在唐代既是军事力量（骑兵），也是身份象征和审美对象。盛唐国力强盛、对外开放，骏马承载着这个时代自信豪迈的精神。唐三彩马的膘肥体壮，正是盛唐气象的缩影。"
      }
    ],
    origin: "洛阳·长安·唐代墓葬",
    organelles: [
      {
        id: "body",
        name: "马身",
        subtitle: "膘肥体壮",
        color: "#a8742a",
        note: "唐三彩马体态丰满健硕，反映了唐人以肥为美、崇尚力量的审美。马的姿态或静立或嘶鸣，神态生动。"
      },
      {
        id: "glaze",
        name: "三彩釉",
        subtitle: "黄绿白交融",
        color: "#c89a4a",
        note: "三彩釉在烧制时会自然流淌交融，形成斑驳绚烂的效果。「三彩」是虚指，实际可有黄、绿、白、褐、蓝等多色。"
      },
      {
        id: "saddle",
        name: "鞍鞯",
        subtitle: "马具装饰",
        color: "#7a9a5a",
        note: "马背上的鞍鞯往往单独施以绿釉，与马身的黄褐釉形成对比。鞍具的华丽程度也反映了主人的身份地位。"
      }
    ]
  },
  {
    id: "buddha",
    name: "永乐佛像",
    type: "明代鎏金铜佛",
    accent: "#8a6a2a",
    defaultOrganelle: "body",
    modelAsset: {
      url: "/museum/models/chinese_amoghasiddhi_buddha_1403_-_1424_ce.glb",
      sourceLabel: "The MET (Metropolitan Museum of Art)",
      sourceUrl: "https://sketchfab.com/3d-models/33699be99fd64375bf0371c0e0c12f70",
      scale: 16,
      rotation: [0, 0, 0],
      exposure: 1.15
    },
    thumbnail: "/museum/thumbnails/buddha.jpg",
    era: "明",
    dynasty: "明代 · 永乐年间（1403-1424）",
    museum: "美国 · 大都会艺术博物馆",
    museumAbroad: true,
    intro: "永乐宫廷造像融合汉藏艺术风格，鎏金工艺精湛，是明代佛教艺术的巅峰之作。",
    story: "明成祖朱棣登基后，为了笼络西藏、巩固边疆，在皇宫里设立了专门的造像作坊，铸造最精美的佛像，作为礼物赐予西藏的高僧大德。这便是「永乐宫廷造像」——明代佛教艺术的巅峰。\n\n这尊不空成就佛结跏趺坐，面容慈悲安详，五叶宝冠、璎珞臂钏繁复精美，通体鎏金，六百年后依然金光灿烂。它身上既有汉地的端庄圆润，又有藏传佛教的华丽庄严，是两种文化在一尊佛像上的完美交融，也是一段政治与信仰交织的历史的见证。",
    qa: [
      {
        q: "为什么佛像底座刻着「大明永乐年施」？",
        a: "这六个字是断代的关键证据，说明它是明成祖永乐年间（1403-1424）由宫廷「施造」的。「施」是布施、施舍之意，表明这是皇家造像，常用于赏赐西藏高僧。"
      },
      {
        q: "「汉藏融合」体现在哪里？",
        a: "佛像的面容、衣纹偏向汉地的柔和端庄，而繁复的宝冠、璎珞、台座样式则源自藏传佛教。永乐宫廷把两种风格糅合在一起，形成了独特的「永宣造像」风格。"
      },
      {
        q: "为什么明朝皇帝要造佛像送西藏？",
        a: "这是一种政治智慧。明朝通过册封藏传佛教领袖、赏赐精美佛像，建立与西藏的友好关系，巩固对边疆的治理。一尊佛像，承载的是宗教、艺术和政治的多重意义。"
      }
    ],
    origin: "北京·宫廷造办",
    organelles: [
      {
        id: "body",
        name: "佛身",
        subtitle: "不空成就佛",
        color: "#8a6a2a",
        note: "不空成就佛是五方佛之一，代表「成就一切事业」。此像结跏趺坐，右手施无畏印，面容慈悲安详。"
      },
      {
        id: "crown",
        name: "宝冠璎珞",
        subtitle: "装饰系统",
        color: "#aa8a4a",
        note: "五叶宝冠、臂钏、璎珞等装饰极为繁复精美，每一处细节都经过工匠精心錾刻，展现了永乐宫廷造像的最高工艺水平。"
      },
      {
        id: "base",
        name: "莲花座",
        subtitle: "仰覆莲台",
        color: "#6a5a2a",
        note: "莲花座是佛像的基座，象征佛从污泥中超脱的清净本性。永乐造像的莲瓣饱满有力，尖端略微上翘。"
      }
    ]
  },
  {
    id: "porcelainVase",
    name: "青花瓷瓶",
    type: "清代瓷器",
    accent: "#3a5a8a",
    defaultOrganelle: "body",
    modelAsset: {
      url: "/museum/models/baluster_vase_from_a_five-piece_garniture.glb",
      sourceLabel: "Rijksmuseum",
      sourceUrl: "https://sketchfab.com/3d-models/76a3f7bf75d049458dfaa48aa342e0b8",
      scale: 8,
      rotation: [0, 0, 0],
      exposure: 1.2
    },
    thumbnail: "/museum/thumbnails/porcelainVase.jpg",
    era: "清",
    dynasty: "清代 · 康熙年间",
    museum: "荷兰 · 阿姆斯特丹国家博物馆",
    museumAbroad: true,
    intro: "青花瓷以钴蓝料在白瓷胎上绘制纹饰，蓝白相映、典雅大方，是中国瓷器走向世界的代表。",
    story: "在景德镇的御窑厂，一件青花瓷的诞生要经过七十二道工序。匠人用一支笔蘸着钴蓝料，在素白的瓷胎上勾勒花卉，再罩上透明釉，送进1300度的窑火。出窑的那一刻，蓝与白在釉下交融，温润如玉。\n\n这抹中国蓝曾惊艳了整个世界。沿着海上丝绸之路，青花瓷远销欧洲，成为王公贵族争相收藏的珍宝，甚至改变了荷兰代尔夫特蓝陶、日本伊万里瓷的审美。这件瓶子如今安静地立在阿姆斯特丹的博物馆里——它本身，就是一部中国瓷器征服世界的历史。",
    qa: [
      {
        q: "青花瓷的蓝色是怎么来的？",
        a: "来自一种叫「钴」的矿物颜料。匠人用钴料在白瓷胎上绘画，高温烧制后钴呈现出稳定深沉的蓝色。不同产地的钴料呈色略有差异，进口的「苏麻离青」尤其浓艳。"
      },
      {
        q: "为什么这件青花瓷在荷兰？",
        a: "明清时期，青花瓷通过海上贸易大量外销欧洲，是当时最抢手的奢侈品。荷兰东印度公司曾大批订购。这件瓶子很可能就是当年外销欧洲的珍品，最终入藏阿姆斯特丹国家博物馆。"
      },
      {
        q: "青花瓷对世界有什么影响？",
        a: "影响极深远。它催生了荷兰的代尔夫特蓝陶、日本的伊万里瓷，欧洲贵族以收藏中国瓷器为荣。「China」一词在英文里既指中国，也指瓷器——足见瓷器是中国留给世界的文化符号。"
      }
    ],
    origin: "景德镇·御窑厂",
    organelles: [
      {
        id: "body",
        name: "瓶身",
        subtitle: "棒槌瓶形制",
        color: "#3a5a8a",
        note: "此瓶属于五件套陈设瓷之一，棒槌瓶造型挺拔端庄。瓶身通体以钴蓝绘制花卉纹饰，蓝白相映，典雅大方。"
      },
      {
        id: "glaze",
        name: "青花釉色",
        subtitle: "钴蓝与白釉",
        color: "#2a4a7a",
        note: "钴蓝料在高温下呈现出深沉而稳定的蓝色，配合白色瓷胎，形成鲜明对比。不同产地的钴料呈色各有特点。"
      },
      {
        id: "pattern",
        name: "纹饰",
        subtitle: "缠枝花卉",
        color: "#4a6a9a",
        note: "瓶身纹饰分为多层，以缠枝花卉为主题，辅以如意云头、蕉叶纹等边饰，构图严谨而富有韵律。"
      }
    ]
  },
  {
    id: "censer",
    name: "青铜瑞兽香炉",
    type: "明清铜炉",
    accent: "#5a5048",
    defaultOrganelle: "beast",
    modelAsset: {
      url: "/museum/models/chinese_censer.glb",
      sourceLabel: "Sketchfab",
      sourceUrl: "https://sketchfab.com/3d-models/d961057973114029b5d92a943ef421cd",
      scale: 4.5,
      rotation: [0, 0, 0],
      exposure: 1.1
    },
    thumbnail: "/museum/thumbnails/censer.jpg",
    era: "明清",
    dynasty: "明清时期",
    museum: "传世铜炉 · 各地收藏",
    museumAbroad: false,
    intro: "香炉是中国传统香事文化的核心器具，瑞兽踞顶、龙形耳、镂空炉盖，集铸造工艺与吉祥寓意于一身。",
    story: "在中国古代文人的书房里，焚香是一件雅事。读书、抚琴、会客之前，先点一炉香，看青烟从镂空的炉盖中袅袅升起，盘旋、消散——心也随之静下来。\n\n这尊香炉的炉盖顶端，蹲坐着一只名叫狻猊的瑞兽，传说是龙的第五个儿子，生性喜爱烟火，所以总爱待在香炉上。它张着嘴，让香烟从口中升腾而出。三只兽足、两只龙耳，整体仿照上古青铜鼎的形制——这是明清文人「仿古慕雅」的审美：既要古意，又要精致。一炉香里，藏着中国人千年的生活美学。",
    qa: [
      {
        q: "炉顶上蹲着的是什么动物？",
        a: "是狻猊（suān ní），传说为「龙生九子」中的第五子。它生性喜静、好烟火，所以常被铸在香炉、佛座上。它张口的造型，正好让香烟从口中飘出，既是装饰也有功能。"
      },
      {
        q: "古人为什么这么爱焚香？",
        a: "焚香在中国是一种延续千年的生活美学。它能静心、驱秽、营造氛围，读书、抚琴、品茶、礼佛、会客都要焚香。香炉因此成为文人书房「文房清供」的重要陈设。"
      },
      {
        q: "炉盖为什么要做成镂空的？",
        a: "既是装饰，也是功能。镂空的孔隙让香烟能缓缓溢出，形成「香雾缭绕」的意境。如果炉盖是密封的，香烟就散不出来了。美观与实用在这里完美结合。"
      }
    ],
    origin: "厅堂·书房·寺庙",
    organelles: [
      {
        id: "beast",
        name: "炉顶瑞兽",
        subtitle: "狻猊踞顶",
        color: "#5a5048",
        note: "炉盖顶端蹲坐的瑞兽是狻猊，传说为龙之第五子，喜烟好坐，因此常被铸于香炉之上。它张口的姿态正好让香烟从口中袅袅升起。"
      },
      {
        id: "lid",
        name: "镂空炉盖",
        subtitle: "出香透烟",
        color: "#7a6e60",
        note: "炉盖采用镂空透雕，缠枝卷草的纹样间留出孔隙，焚香时香烟便从镂空处缓缓溢出，形成「香雾缭绕」的意境。"
      },
      {
        id: "legs",
        name: "兽足龙耳",
        subtitle: "三足双耳",
        color: "#4a4038",
        note: "香炉的三足作兽首状，两侧的炉耳铸成龙形，整体形制仿照上古青铜鼎，体现了明清文人「仿古慕雅」的审美追求。"
      }
    ]
  }
];

export function getMuseumItemById(id: string) {
  return museumCatalog.find((item) => item.id === id) ?? museumCatalog[0];
}

// 把以 / 开头的绝对路径转成带 base 前缀的路径，兼容 GitHub Pages 子路径部署
export function museumAsset(path: string) {
  const base = import.meta.env.BASE_URL.replace(/\/$/, "");
  return path.startsWith("/") ? base + path : path;
}
