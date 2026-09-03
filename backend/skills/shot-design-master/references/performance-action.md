# 表演、情绪与动作设计

**铁律：不要写「悲伤、愤怒、害怕、感动」。** 模型执行不了抽象情绪，只能执行可观察的面部肌肉、眼神、呼吸和肢体。

---

## 一、情绪具象化公式

```text
[景别/运镜] + [人物身份与外观一致性] + [情绪阶段] + [面部表情细节] + [眼神]
+ [嘴部/下颌] + [身体反应] + [动作节奏] + [光影氛围] + [稳定性约束]
```

英文对应：

```text
[shot type and camera movement], [character identity and consistent appearance], [emotional state],
[specific facial muscles], [eye expression], [mouth and jaw details], [body reaction],
[slow subtle motion], [lighting and mood], [stability constraints]
```

---

## 二、情绪 → 微表情对照表

| 情绪 | 面部表情 | 眼神 | 身体反应 | 适合镜头 |
|---|---|---|---|---|
| 隐忍难过 | 眉心轻轻收紧，嘴唇抿成一条线，鼻翼微微颤动 | 眼眶泛红，视线下垂，强忍泪水 | 肩膀僵住，手指攥紧衣角 | 近景、侧脸特写、慢推 |
| 崩溃痛哭 | 眉毛上扬并内收，脸颊湿润，嘴角下压 | 泪水滑落，眼神失焦 | 胸口起伏，身体微微发抖 | 大特写、手持微晃 |
| 压抑愤怒 | 眉头紧锁，下颌绷紧，鼻翼扩张 | 目光死死盯住对方 | 指节发白，呼吸变重 | 低角度近景、缓慢推近 |
| 爆发愤怒 | 牙关紧咬，嘴唇张开，额头青筋微显 | 眼睛睁大，视线锐利 | 身体前倾，拳头猛然握紧 | 快速推近、中近景 |
| 惊恐害怕 | 眉毛抬高，眼睛睁大，嘴唇微张 | 瞳孔放大，视线快速闪动 | 后退半步，肩膀缩起 | 主观镜头、特写、手持 |
| 震惊错愕 | 嘴唇微张，脸部肌肉僵住，眉毛停在半抬状态 | 眼神定住，短暂停顿 | 身体静止，呼吸停顿一拍 | 静止近景、突然切特写 |
| 心虚慌乱 | 嘴角轻微抽动，吞咽，下巴回缩 | 眼神躲闪，不敢直视 | 手指摩擦袖口，身体微偏 | 中近景、过肩镜头 |
| 冷漠疏离 | 面部放松但无笑意，嘴角平直 | 眼神平静空洞，看向远处 | 身体保持距离，动作克制 | 中景、侧面构图、冷光 |
| 失望麻木 | 眉眼下垂，脸部失去力量，嘴唇微微分开 | 眼神涣散，视线越过对方 | 肩膀慢慢垮下 | 慢拉远、窗边侧脸 |
| 温柔心动 | 眉眼放松，嘴角轻轻上扬，脸颊微红 | 眼神柔软，短暂偷看后移开 | 手指轻轻停顿，呼吸变浅 | 柔光近景、慢推 |
| 克制爱意 | 嘴角想笑又压下，眼睫轻颤 | 目光停留一秒后躲开 | 手指收紧又松开 | 过肩近景、手部特写 |
| 欣慰释然 | 眉头慢慢舒展，嘴角自然上扬 | 眼里含泪但带笑 | 长长呼出一口气，肩膀放松 | 暖光近景、慢拉远 |
| 嫉妒酸涩 | 嘴角僵硬，笑容不达眼底 | 目光停在对方身上，迅速移开 | 手指捏紧杯沿 | 侧脸特写、前景遮挡 |
| 不甘屈辱 | 下颌紧绷，嘴唇抿紧，眼眶泛红 | 眼神倔强，含泪不落 | 背脊挺直，拳头藏在身侧 | 低角度近景、慢推 |
| 疑惑警觉 | 眉头单侧微挑，眼睛微眯 | 视线扫过细节，停顿 | 头部轻微偏转 | 中近景、缓慢横移 |
| 阴冷威胁 | 嘴角极轻微上扬，笑意冰冷 | 眼神压低，直视镜头 | 身体几乎不动，压迫感强 | 低角度特写、硬光 |
| 虚伪假笑 | 嘴角上扬但眼周无变化，笑容僵硬 | 眼神冷淡，停留过久 | 颈部僵住，动作过分礼貌 | 正面近景、静止镜头 |
| 疲惫绝望 | 眼皮沉重，脸色苍白，嘴唇干涩 | 眼神空洞，无聚焦 | 身体靠墙下滑，动作迟缓 | 暗光中景、慢拉远 |
| 冷静决断 | 面部肌肉松弛下来，呼吸放缓一拍 | 目光聚焦一点不再游移 | 肩线放平，手掌摊开又握实 | 中近景、缓慢推近 |
| 爽 / 反杀 | 嘴角单侧扬起，眉峰压低 | 眼神自下而上抬起直视对方 | 肩背舒展，下巴微抬 | 低角度近景、快速推近 |

### 情绪稳定性约束（每条含人脸的提示词都挂）

```text
consistent face, natural facial anatomy, subtle micro expressions, realistic eyes, fluid motion,
no flickering, no face distortion, no extra teeth, no deformed mouth, no unnatural smile,
no crossed eyes, no changing hairstyle, no changing outfit
```

---

## 三、台词、音色与口型

### 3.1 台词写法

```text
{角色/代号}用{音色描述}，{语速与情绪}说道 {台词原文}
```

- 台词原文必须用 `{}` 花括号包裹——模型据此判断口型与配音内容。
- 一条台词只绑**一个**说话人、**一种**语言。多语言场景分条写，不要混进一段。

### 3.2 音色描述模板

```text
{音区}、{音质}的{年龄}{性别}声
```

> 示例：`偏低沉厚、冷得无情绪的三十五岁男声`、`中低声区、偏冷带颗粒感的二十一岁女声`

### 3.3 语速与情绪

| 状态 | 写法 |
|---|---|
| 冷静宣判 | `语速平缓、毫无起伏地` |
| 压抑愤怒 | `压着嗓子一字一句` |
| 崩溃 | `声音发抖、气息断续` |
| 试探 | `尾音上扬、语速偏慢` |
| 爆发 | `音量陡然拔高、语速加快` |
| 虚弱 | `气声、几乎听不清` |

### 3.4 口型与字幕

- 口型同步要求：`口型与台词严格同步，不要出现空口型或错位`。
- 默认**不出字幕**：`保持无字幕，避免生成任何文字或字幕`。
- 台词长度换算：每 10 字约 2 秒，用来核对镜头时长够不够。

---

## 四、动作戏设计

### 4.0 先过七原则（戏剧层，决定观众有没有感觉）

技术全对但观众无感的打戏，问题一定在这七条：
**Clarity 清晰**（谁打谁、打中哪，最高优先级，其余六条让位于它）、
**Geography 场景几何**（左右站位与距离始终可追踪）、
**Stakes 赌注**（输了会怎样）、**Motivation 动机**（每招都是人物驱动）、
**Choreography 编排**（有创意有节奏，不是「轻微换姿势」）、
**Vulnerability 脆弱**（角色被真实威胁）、**Consequences 后果**（衣袂破损、喘息加重、重心崩溃）。

Stakes 与 Motivation 写进场次说明，不进提示词；其余五条必须落成可见画面。详见 [附 §3.0](#30-动作戏七原则写任何一场打戏之前先过一遍)。

### 4.1 拆镜原则

所有打斗/对抗按 **出招 → 受击** 拆成多镜，不要一镜打完。

标准五镜动作链：

```text
起势（蓄力/架势）→ 出招（攻击轨迹）→ 受击（受力反馈）→ 反应（踉跄/格挡）→ 结果（站位重置/胜负）
```

段落骨架（对打段落通用四段）：

```text
起势段（1-2 镜）→ 进攻段（约 1/3）→ 防御反击段（约 1/3）→ 收势段（1-2 镜）
```

**片段拆分硬参数**（超了必崩，没有例外）：

| 参数 | 值 |
|---|---|
| 每段时长 | **2–4 秒，只做 1 个动作单元** |
| 动作单元 | 蓄力/起手 → 挥出 → 撞击打点 → 受击反馈，四选一，不要串起来 |
| 禁止 | 单段生成 8–12 秒完整连招；动作进行中的复杂 360° 大旋转镜头 |
| 一致性 | 每段上传角色参考图并开形象锁；全段统一风格词，**不混搭水墨 / 赛璐珞 / 写实** |

> 双人对练每镜都要写全 A（主动）与 B（被动）以及两人距离朝向；腾空/跌落一个 15 秒段落最多 2 镜。

### 4.2 打击感五件套（必写，五类缺一不可）

**打击感 ≠ 光效。** 只写「他打了他」模型给不出重量；只加剑气火花画面依然「软」。
**约束单位是一次打击（跨出招—受击—环境三镜链），不是一镜。** 五类必须在同一次打击里全部出现，但不得挤进同一镜——缺任何一类，力量感都塌：

| # | 类型 | 必写元素 |
|---|---|---|
| 1 | **蓄力势能** | 重心下压、肌肉紧绷、关节蓄力、身体扭转 |
| 2 | **接触冲击** | 环形冲击波、火花、冲击帧、画面短震 |
| 3 | **受击反馈** | 头部猛甩、身体弓形后弹、手臂上扬、步伐擦地 |
| 4 | **环境破坏** | 碎石飞溅、尘土炸开、地面裂纹、断木横飞 |
| 5 | **镜头反馈** | 撞击瞬间镜头剧烈震动、1 帧白闪冲击帧、速度线爆发；慢动作**按回合分配**——只给终结击（0.25x / 0.5s），中间回合一律不降速 |

**分摊方式**——一镜只担一到两类（**挤进同一镜会顶穿 §四点五 的运动幅度 ≤ 4 上限，肢体必崩**）：

```text
出招镜 → ① 蓄力          受击镜 → ② 接触冲击 + ③ 受击反馈
环境镜 → ④ 环境破坏       全程   → ⑤ 镜头反馈（优先后期做，零生成风险）
```

**受力反馈词表**：

| 类型 | 写法 |
|---|---|
| 重心 | `重心沉降，脚下扬起尘土` |
| 命中 | `拳拳到肉的面部形变，颊部肌肉被冲击带出波纹` |
| 被击退 | `被击退滑地，鞋底在地面擦出痕迹` |
| 冲击波 | `气浪掀起碎石与衣摆` |
| 落地 | `落地瞬间膝盖屈曲卸力，肩部前倾` |
| 武器 | `刀锋切过空气带出细微风声，刃面反光扫过面部` |

完整中英词库见 [附 §3.2](#32-打击感五件套必写五类缺一不可)。

### 4.3 攻防轮转规则

```text
攻防规则：{A}率先出手，{B}先格挡或让开再行反制。
全片两人都要有主动出招、防御化解、格挡和反击，
任何一方不得连续挨打超过一个回合。
每个回合（约 3 镜、4-6 秒）完成一次进攻—化解—反击的完整轮转；
15 秒段落 = 2 个完整回合 + 1 记终结击。
```

### 4.4 硬性约束

- 严格锁定角色左右站位，防止 180° 越轴。
- 慢动作**只用在最后一击命中**的一瞬间（0.25x，持续 0.5 秒），不要全程慢放；中间回合用正常速度 + 冲击帧。
- 剪辑卡点：**终结击**命中瞬间插 0.5 秒慢动作；中间回合的每次命中只插 1 帧白闪、不降速。位移与蓄力段保持正常速度或快切，靠**快慢交替**制造张力。
- 写实题材禁用超能力、禁用夸张慢动作拖尾、避免血腥特写。
- 高风险动作镜**成片上**控制在 1.5–2.5 秒（层③剪辑时长）；**生成请求仍按 ≥ 4 秒下单再裁短**，直接拿 2 秒下单会被平台 400 拒。
- 每条打戏提示词结尾挂：`画面稳定流畅，无闪烁跳帧，无五官变形，无肢体畸形，人物不换脸，光影统一，24fps`。
- 负面词：`动作发虚, 肢体扭曲, 武器形变, 镜头莫名切换, floating motion, rubber limbs, merged bodies, intersecting limbs, no-impact fight`。

### 4.5 完整打戏模板

见 [prompt-contracts.md](prompt-contracts.md) §7 动作戏契约；五种题材的可粘贴正/负向提示词见 [附 §3.11.3](#3113-五种题材的正负向提示词可直接粘贴)。

---

## 四点五、AI 动作戏安全方案（打斗 / 追逐 / 坠落）

> **先认清底层限制**：扩散模型逐帧去噪，两帧之间位移过大时模型「猜不准」中间发生了什么。
> 所以**运动幅度越大越容易崩**。正确做法不是让模型学会高速运动，而是**重新设计动作本身**。
>
> 下面这套方案与 §四「出招-受击拆分」并不冲突：拆分解决**戏剧节奏**，本节解决**生成稳定性**。
> 两者冲突时，**以本节为准**——拍不出来的镜头再有节奏也没用。

### 五策略安全公式

```text
[降速设计] + [单动作单镜] + [暗示代替展示] + [特效加分] + [声音补位]
```

### 帧率单一口径（先定这个，再谈慢动作）

全片**只有 24fps 一个交付帧率**。它已经写死在 §3.11.5 / §3.13 的防崩坏后缀里，属于制作单常量，逐镜提示词不得改写、不得省略。
`60fps` 降级为**素材帧率（capture frame rate）**，只在这一镜确实要升格时才出现。

| 镜头类型 | 帧率怎么写 | 为什么 |
|---|---|---|
| 常规动作镜（不升格） | 正文一个帧率数字都不写，只靠后缀里的 `24fps` | 多写一个数字就多一次时间基竞争 |
| 需要升格的镜头（终结击、坠落、拳锋破雨） | 正文写 `shot at 60fps for slow-motion, delivered at 24fps`，后缀的 `24fps` 照挂 | 一句话里把「拍摄」和「交付」分成两个角色，模型不必猜哪个是最终帧率 |
| 参考视频素材入参 | 24–60fps 照收，不受本条约束 | 那是输入侧的解码规格，不是输出侧的交付规格 |

**禁止把 `24fps` 与 `60fps` 裸写进同一串**（例如正文 `slow motion, 60fps` 配后缀 `光影统一，24fps`）：
两个孤立的帧率数字对模型是两个互斥的时间基，采样时会在二者之间摇摆，**输出忽快忽慢的变速段落、动作中段突然抽帧**。
`60fps` 必须永远带着 `for slow-motion, delivered at 24fps` 一起出现——带上这半句它才是修饰语，裸写就是第二个目标值。

> [models-failures.md](models-failures.md) 里「只有当提示词或制作单确立了 24fps 时才可假设该帧率」的告诫依然成立，
> **本节就是那份制作单**：本项目已把 24fps 确立为常量，帧锚点（30 秒 = 720 帧）可直接按 24fps 换算。

#### 策略① 降速设计：把「快动作」变成「慢美学」

不要写 `fast action`，直接写 `slow motion, cinematic slow motion`。慢动作不只更稳，叙事力量也更强。
帧率按上面的「帧率单一口径」写，不要在这里塞 `60fps`。

| 高速动作（易崩） | 低速替代方案（稳定） | 叙事效果 |
|---|---|---|
| 快速打斗 | 对峙 + 慢动作出拳 | 张力更强 |
| 快速追逐 | 缓慢跟踪 + 距离变化 | 压迫感 |
| 快速坠落 | 慢动作坠落 + 面部特写 | 情感冲击 |
| 快速跑动 | 固定镜头 + 人物从远处走来 | 期待感 |

#### 策略② 单动作单镜：一个镜头只做一件事

一个镜头里同时发生多件事 = 多个运动向量 = 模型被混淆。

| 多动作（易崩） | 单动作（稳定） |
|---|---|
| 奔跑 + 挥拳 + 躲闪 | 镜头1 奔跑 / 镜头2 挥拳 / 镜头3 躲闪 |
| 摔倒 + 翻滚 + 爬起来 | 镜头1 摔倒 / 镜头2 翻滚 / 镜头3 爬起来 |

**拆分法则：🟢 低危动作（对峙、慢动作、影子暗示）一个 5 秒镜头 = 一个动作。5 秒 × 2 的可控度远高于 10 秒 × 1。**
🟡🔴 的动作镜不适用——按 §3.1 每段 2–4 秒一个动作单元切，5 秒会让帧间位移累积到崩。

#### 策略③ 暗示代替展示：让观众脑补

电影史上最经典的暴力场景，恰恰是观众没看到的那些。

| 展示动作（易崩） | 暗示动作（稳定） | 叙事效果 |
|---|---|---|
| 两人打斗 | 地上晃动的影子 + 撞击声 + 物品掉落 | 观众脑补 = 更可怕 |
| 角色被攻击 | 面部反应 + 音效 + 血迹溅到墙上 | 恐惧感翻倍 |
| 车辆撞击 | 车内视角震动 + 玻璃碎裂声 + 黑场 | 冲击力更强 |

> **影子暗示是 AI 动作戏的王牌**：影子本身就是模糊、变形、不完美的——这恰好把模型的「不完美」变成了风格。

#### 策略④ 特效加分：粒子是动作戏的遮瑕膏

模型在特效渲染上的表现远好于精确动作。火星、灰尘、水花、碎屑既好看，又能掩盖快速动作中的微小瑕疵。

**但「粒子多」和「特效多」是两个维度，别一起松也别一起紧**：同一类粒子的**密度可以拉满**（火星铺满整屏也不崩）；
**粒子类别必须择一**，**改变画面物理读法的叙事特效更是一镜只准一种**。这一镜该选哪一个、同镜禁止叠加哪些，
见 [附 §3.10](#310-冷兵器与能量光影特效) 的「意图 → 特效选型决策表」。

#### 策略⑤ 声音补位：一半的动作戏在声音里

一个 5 秒动作镜头至少配 **3 层声音**：撞击声 + 环境音 + 呼吸声。

| 声音 | 作用 |
|---|---|
| 撞击声 | 拳拳到肉的感觉 |
| 呼吸声 | 增强临场感 |
| 环境音（雨/风/街道） | 建立空间真实感 |
| 心跳声 | 最直接的情绪放大器 |
| 慢动作静音 + 心跳 | 时间凝固的震撼 |

> 撞击声必须对齐拳头击中的**那一帧**，误差不超过 2 帧。

### 五种动作场景的完整提示词

**1 对峙（动作戏的安全牌，几乎零运动幅度）**

```text
两个角色在暴雨中对峙，面对面站立，雨水从两人脸上流下，衣服湿透紧贴身体，
伦勃朗光从侧面打来照亮两人的半边脸，眼神中充满杀意，但身体一动不动，
固定机位，运动幅度2，电影级画质，8K
```

**2 慢动作出拳**

```text
slow motion, shot at 60fps for slow-motion, delivered at 24fps, cinematic slow motion,
主角缓慢挥出一记右拳，面部肌肉在出拳的瞬间紧绷，
拳锋划破雨滴，水花在空中近乎静止，
运动幅度3，电影级运动美学，8K
```

**3 影子暗示打斗（王牌）**

```text
一面被一盏孤灯照亮的斑驳墙面，两个剧烈晃动的影子在墙上搏斗，
一个影子挥拳，另一个影子向后踉跄，真实的灯光投射效果，画面中不出现真人，
film noir 悬疑氛围，固定机位，8K
```

**4 追逐（让摄影机替角色跑）**

```text
手持摄影，摄影机在狭窄的巷道中快速移动，画面晃动但保留主体辨识度，
前方的人影在巷子尽头转弯消失，运动幅度4，真实临场追击感，8K
```

**5 坠落（慢动作 + 空中姿态，不拍落地过程）**

```text
slow motion, shot at 60fps for slow-motion, delivered at 24fps, 仰拍视角，一个人影从高处缓缓坠落，
身体在空中近乎静止，衣袂缓慢飘动，背景是灰暗的天空，没有参照物，
运动幅度3，诗意化的坠落美学，8K
```

**火星特效打斗**

```text
slow motion, 一记重拳击中，撞击处迸发出无数火星，火星在空中缓慢飘散，暗红色微光，
dense orange sparks only, no dust, no debris, 运动幅度3，电影级特效，8K
```

### 剧本阶段就标危险等级

| 等级 | 场景 | 处理 |
|---|---|---|
| 🟢 安全 | 对峙、慢动作、影子暗示 | 直接生成 |
| 🟡 中等 | 追逐、手持跟随 | 运动幅度降到 4 |
| 🔴 危险 | 快速打斗、复杂肢体交互 | 拆成多个单动作镜头，或改设计方案 |

> **在剧本阶段就把 🔴 改成 🟢，才是 AI 动作戏的终极思维**——不是等生成失败再想办法。

分镜表里每个动作镜头都要标注：模型、运动幅度、时长、特殊关键词。

```text
SH05 | 慢动作挥拳       | 运动幅度3 | 5s | slow motion, 60fps升格→24fps交付
SH06 | 拳头击中的火星特效 | 运动幅度2 | 3s | particle sparks impact
SH07 | 对手倒下的面部反应 | 运动幅度1 | 3s | subtle facial shock
```

### 动作戏翻车急救表

| 现象 | 原因 | 急救 |
|---|---|---|
| 慢动作画面仍撕裂 | 运动幅度太高 | 降到 2–3，并加 `extremely slow motion` |
| 影子暗示里影子不动 | 提示词不够具体 | 加 `shadows struggling violently, one shadow punching another` |
| 手持追拍画面太抖 | 运动幅度设太高 | 从 5 降到 4，加 `stable handheld, slight shake only` |
| 特效粒子挡住主体 | 粒子描述过重 | 加 `subtle particle effects, main subject clearly visible` |
| 声音和画面不同步 | 未以帧对齐 | 撞击声对齐击中那一帧，误差 ≤ 2 帧 |

### 速查卡

```text
① 降速设计：慢动作，交付恒为 24fps；升格镜才写 60fps→24fps，运动幅度 ≤ 4
② 单动作单镜：一镜一动作，5秒 × 2
③ 暗示代替：拍影子 / 面部反应 / 后果
④ 特效加分：火星 / 灰尘 / 水花择一，一镜一主叙事特效
⑤ 声音补位：3 层音效，画面不够声音凑

⚠️ 运动幅度决不超过 7
⚠️ 不要一个镜头里塞两个动作
⚠️ 打斗场面首选影子暗示
⚠️ 所有动作场景加慢动作关键词
```

> 动作戏的本质不是「快」，是「紧张感」——而紧张感不依赖运动速度。

---

## 五、群演与背景人物

- 背景人物只写**行为类别**，不写长相：`背景数名路人各自行走交谈，不看向镜头，不抢主体注意力`。
- 明确禁止背景人物复制：`背景人物各不相同，不出现重复面孔`。
- 群演不参与主线动作，避免模型把注意力从主体上移开。

---

# 附：完整词典与扩展条目

> 上文为速查版（分镜阶段按预算截断时优先保留）；以下为完整版。

> 本节是**表演层**的权威规范：情绪具象化、台词与口型、动作戏拆解、群演约束。
> 上游输入：`ShotMotionContract` 的 `subject_action` / `expression` / `start_state` / `end_state` 字段。
> 下游输出：图像提示词的「可观察表情」段 + 视频提示词的「时间轴动作」段。
>
> **一句话总纲：AI 不理解情绪，只理解肌肉；不理解招式，只理解受力。**

---

## 0. 本节铁律（写任何一条表演提示词前先过一遍）

| # | 铁律 | 违反后果 |
|---|------|----------|
| 1 | 禁止抽象情绪词（悲伤/愤怒/害怕/激动），一律转写为可观察的**面部肌肉 + 眼神 + 嘴部 + 下颌 + 呼吸 + 肢体** | 角色面瘫、"死人脸" |
| 2 | 默认表情强度 **L2（内敛/可读）**，L4 全片只用一次 | 情绪疲劳、卡通夸张脸 |
| 3 | 表情必须**不对称 + 渐进 + 联动**，单侧先动、留 1–2 秒过渡、至少写一对联动 | 完美对称假脸、情绪瞬间切换 |
| 4 | **一个切片 = 一个核心变化 + 一个联动细节**，超过这个量模型必乱 | 画面混乱、五官漂移 |
| 5 | 每个镜头只推进**一个情绪阶段**，不要一条提示词写完整情绪转折 | 情绪断层、跳切感 |
| 6 | 台词 = 文本 + 语速 + 情绪 + 停顿 + 重音，缺一不可 | "念稿"式平淡配音 |
| 7 | 画外音/内心独白必须追加 `禁止：画面中角色出现说话口型` | 独白时嘴巴乱动 |
| 8 | 动作戏禁止抽象动词（飞踢/激烈格斗/降龙十八掌），一律写**受力过程与环境负反馈** | 假人比划、身体漂浮 |
| 9 | 动作单镜**成片** **1.5–2.5 秒**（层③；请求仍 ≥ 4 秒后裁），分镜拆分率 > 80%，绝不让 AI 在一镜里完成"A 打中 B 且 B 倒地" | 穿模率高达 90% |
| 10 | 慢动作**只用于最后一击**；中间回合用正常速度 + 冲击帧 | 全程慢动作 = 没有力量感 |
| 11 | 任一方**不得连续挨打超过一个回合**，第二回合必须出现反击/格挡/闪避 | 单方面殴打，观众情绪流失 |
| 12 | 群演只做**低幅循环动作**，不看镜头、不与主角肢体接触、面部不清晰 | 克隆脸、复制粘贴人群、肢体穿模 |

---

## 一、情绪具象化

### 1.1 禁用词清单（写实风格中严禁出现）

> 以下词汇会导致 AI 生成夸张、僵硬或不自然的表情。

**中文禁忌：**

```text
极度悲伤 / 极度愤怒 / 极度恐惧（→ 改为具体的面部动作描写）
突然大笑 / 突然大哭（→ 改为渐进过渡 + 触发点描写）
脸上露出XX的表情（→ 废话句式，改为具体的肌肉动作）
表情丰富 / 表情夸张（→ 抽象废话，用分区描写替代）
```

**English bans：**

```text
extremely sad / extremely angry / extremely scared（→ replace with specific muscular actions）
suddenly burst into laughter / suddenly crying（→ use gradual transition + trigger）
facial expression showing XX（→ vague, replace with specific muscle actions）
expressive face / exaggerated expression（→ abstract, use zonal description）
```

### 1.2 AI 表情四大陷阱与解法

| 陷阱 | 表现 | 为什么假 | 正确做法 |
|------|------|----------|----------|
| **完美对称表情** | 两侧嘴角同时同幅度上扬、两侧眉毛同步运动 | 真人面部永远不完全对称，左右脸有 1-3mm 的时差和幅度差 | 描写时指定单侧动作：`左侧嘴角微微上扬` / `left corner of the mouth lifting slightly` |
| **情绪瞬间切换** | 上一帧面无表情，下一帧满脸泪水 | 真人肌肉从静止到最大收缩需要 0.3-1.5 秒的过渡 | 使用渐进词：`逐渐`/`缓缓`/`一点点`，至少留 1-2 秒的情绪过渡 |
| **夸张卡通式表情** | 嘴巴大张、眉毛飞天、眼睛圆瞪 | 写实风格中，真人表情幅度远小于动画 | 使用克制修饰词：`微微`/`轻轻`/`不易察觉地`/`slightly`/`barely` |
| **面瘫式静态面部** | 连续数秒面部完全不动，仿佛冷冻 | 即使在"平静"状态，真人也有微小的呼吸起伏、眨眼、微表情波动 | 添加活体呼吸感：`轻微呼吸起伏`/`偶尔眨眼`/`subtle breathing rhythm` |

**自然表情三条黄金准则：**

1. **不对称性（Asymmetry）**——左右脸的表情幅度和时序应有微妙差异。指定"左侧眉头先蹙"比"皱眉"更真实
2. **渐进性（Graduality）**——所有表情变化都需要过渡时间。2 秒钟的变化 > 瞬间切换。描写"从 A 逐渐过渡到 B"
3. **联动性（Co-movement）**——面部表情从不孤立发生。眼神变化时呼吸也会变、唇部动作时颌部也会动。至少写一对联动

### 1.3 情绪提示词通用公式

**中文公式：**

```text
[景别/镜头] + [人物身份与外观一致性] + [情绪阶段] + [面部表情细节] + [眼神] + [嘴部/下颌] + [身体反应] + [动作节奏] + [光影氛围] + [稳定性约束]
```

**英文公式：**

```text
[shot type and camera movement], [character identity and consistent appearance], [emotional state], [specific facial muscles], [eye expression], [mouth and jaw details], [body reaction], [slow subtle motion], [lighting and mood], [stability constraints]
```

**通用稳定性约束（每条含人脸的提示词都要挂）：**

```text
consistent face, natural facial anatomy, subtle micro expressions, realistic eyes, fluid motion, no flickering, no face distortion, no extra teeth, no deformed mouth, no unnatural smile, no crossed eyes, no changing hairstyle, no changing outfit
```

**皮肤基底（表情的地基，先真实皮肤再写表情）：**

```text
Realistic skin texture with visible pores, subsurface scattering, micro-imperfections
Sweat glistening on skin surface
```

### 1.4 面部七区微表情词库（Facial Micro-Expression Atlas）

> **核心方法论：** 将面部拆解为 7 个独立区域，每个区域有各自的"词根"。组合不同区域的词根，即可描绘出任何复杂情绪——就像拼乐高一样精准。

#### 1.4.1 眼部（Eyes）— 80% 的情绪信息由此传达

| 动作描写（中文） | 英文提示词 | 传达情绪 | 强度 |
|------------------|------------|----------|------|
| 瞳孔轻微收缩 | pupils contracting slightly | 警觉/紧张 | L1 |
| 眼神忽地一颤 | gaze trembling for a split second | 内心动摇 | L2 |
| 目光向右下方飘移 | gaze drifting to the lower right | 犹豫/回忆 | L1 |
| 强迫自己拉回视线 | forcing gaze back | 意志力对抗 | L2 |
| 眼底浮起一抹痛楚 | a flash of pain surfacing in the eyes | 压抑的痛苦 | L2 |
| 眼眶边缘泛起湿意 | moisture gathering at the rim of the eyes | 即将流泪 | L2 |
| 眼皮不住轻颤 | eyelids trembling uncontrollably | 强忍情绪 | L3 |
| 泪光已清晰可见 | tears clearly glistening | 情绪外溢 | L3 |
| 视线脆弱而挣扎 | gaze vulnerable and struggling | 矛盾/崩溃边缘 | L3 |
| 双眼猛然合上 | eyes squeezing shut | 情绪断路/逃避 | L3 |
| 泪水无声滑落 | tears sliding down silently | 悲伤溢出 | L3 |
| 再度睁开时目光涣散 | reopening with unfocused gaze | 放空/接受 | L2 |

**补充词根（可自由拼接）：** 眼眶泛红、眼睫轻颤、泪水在眼眶打转、视线下垂、眼神躲闪、瞳孔放大、眼神失焦、眼睛微眯、直视不眨眼、笑意不达眼底

#### 1.4.2 眉部（Brows）

| 动作描写（中文） | 英文提示词 | 传达情绪 | 强度 |
|------------------|------------|----------|------|
| 眉心浅蹙旋即展开 | brow furrowing briefly then smoothing | 一闪而过的不安 | L1 |
| 眉头微微皱起又马上展开 | brows knitting slightly then immediately relaxing | 压抑的情绪波动 | L1 |
| 单侧眉梢轻挑 | one eyebrow lifting subtly | 怀疑/审视 | L1 |
| 眉头渐渐拧紧 | brows gradually tightening | 痛苦/困惑加深 | L2 |
| 眉间出现两道浅浅竖纹 | faint vertical lines forming between the brows | 持续的忧虑 | L2 |
| 眉头猛地上扬 | brows shooting upward | 惊讶/震惊 | L3 |

**补充词根：** 眉毛内侧上扬、单侧眉峰微挑、眉头压低、眉尾下垂、眉毛短暂抽动

#### 1.4.3 唇部（Lips & Mouth）

| 动作描写（中文） | 英文提示词 | 传达情绪 | 强度 |
|------------------|------------|----------|------|
| 唇角不易察觉地抽动 | an almost imperceptible twitch at the corner of the lips | 内心波动的泄漏 | L1 |
| 嘴唇张开一丝缝隙 | lips parting by a sliver | 欲言又止 | L1 |
| 欲言又止，最终无声合拢 | lips parting as if to speak, then closing silently | 压抑/放弃表达 | L2 |
| 唇角往下抿紧 | corners of the mouth pressing downward | 强忍哭意 | L2 |
| 下唇轻微颤动 | lower lip trembling slightly | 即将失控 | L2 |
| 嘴角微微上扬但眼神未笑 | mouth curving up while eyes remain unsmiling | 苦笑/假笑 | L2 |
| 嘴唇微启，吸入一口凉气 | lips parting slightly, drawing a sharp breath | 震惊/疼痛 | L2 |
| 咬住下唇 | biting down on the lower lip | 克制/犹豫 | L2 |
| 唇瓣颤抖着分开 | lips trembling apart | 崩溃临界 | L3 |

**补充词根：** 嘴唇抿成一条线、嘴角下压、牙关紧咬、吞咽动作、假笑僵住、笑容慢慢消失

#### 1.4.4 鼻部（Nose）

| 动作描写（中文） | 英文提示词 | 传达情绪 | 强度 |
|------------------|------------|----------|------|
| 鼻翼轻微煽动 | nostrils flaring slightly | 压抑的愤怒/紧张 | L1 |
| 鼻尖微微泛红 | tip of the nose reddening faintly | 隐忍的悲伤 | L2 |
| 鼻梁上浮现细微皱纹 | fine wrinkles forming on the bridge of the nose | 嫌恶/抗拒 | L2 |
| 深深吸气鼻翼扩张 | deep inhale expanding the nostrils | 情绪积蓄 | L2 |

#### 1.4.5 颌部与喉部（Jaw & Throat）

| 动作描写（中文） | 英文提示词 | 传达情绪 | 强度 |
|------------------|------------|----------|------|
| 下颌微微绷着 | jaw clenching slightly | 克制/紧张 | L1 |
| 喉结轻轻滚动 | Adam's apple bobbing gently | 咽下话语/紧张吞咽 | L1 |
| 下巴轻颤 | chin quivering lightly | 即将失控 | L2 |
| 咬紧牙关，颌线绷紧 | jaw locking tight, jawline tensing | 极度克制 | L3 |
| 喉结剧烈上下滚动 | Adam's apple bobbing visibly | 强烈吞咽/恐惧 | L3 |

#### 1.4.6 额部（Forehead）

| 动作描写（中文） | 英文提示词 | 传达情绪 | 强度 |
|------------------|------------|----------|------|
| 额头浮现细密汗珠 | fine beads of sweat forming on the forehead | 紧张/压力 | L1 |
| 额纹随眉部动作一闪而过 | forehead lines flashing with brow movement | 短暂的情绪波动 | L1 |
| 太阳穴青筋隐约浮起 | veins faintly pulsing at the temples | 压抑的愤怒 | L2 |
| 汗珠沿鬓角缓缓滑下 | sweat rolling slowly down the temple | 持续紧张/高温 | L2 |

#### 1.4.7 面颊（Cheeks）

| 动作描写（中文） | 英文提示词 | 传达情绪 | 强度 |
|------------------|------------|----------|------|
| 面颊肌肉几不可见地收紧 | cheek muscles tightening almost imperceptibly | 内在紧张 | L1 |
| 眼角鱼尾纹随微笑浮现 | crow's feet appearing with a faint smile | 真诚的微笑（杜兴微笑） | L2 |
| 泪痕沿面颊留下一道湿痕 | a wet trail left by a tear down the cheek | 已经哭过 | L2 |
| 面颊因愤怒微微涨红 | cheeks flushing faintly with anger | 压抑的怒意 | L2 |

#### 1.4.8 肢体反应（Body，与面部联动使用）

```text
指节发白、手指攥紧衣角、肩膀微微发抖、身体僵住、后退半步、胸口起伏、呼吸变浅、背脊挺直、手指轻敲桌面、身体慢慢垮下
```

| 情绪 | 身体动作提示词（English） |
|------|--------------|
| 紧张 | `fidgeting with hands, shifting weight between feet, shoulders slightly raised and tense` |
| 愤怒 | `leaning forward aggressively, clenched fists at sides, chest expanding with heavy breath` |
| 悲伤 | `shoulders slumped forward, head slightly bowed, arms wrapped around self` |
| 喜悦 | `open posture, slight bounce in movement, hands gesturing freely, chest lifted` |
| 惊讶 | `stepping back slightly, hands rising to chest level, spine straightening suddenly` |
| 思考 | `hand touching chin, head tilting to one side, eyes looking up-left, weight on one leg` |

### 1.5 表情强度四级体系

> **核心原则：默认从 L2 开始。** 绝大多数剧情场景使用 L2（内敛/可读）即可达到自然的演员表演质感。只有在用户明确要求或叙事高潮才提升到 L3-L4。

| 等级 | 名称 | 描写密度 | 观众感知 | 适用场景 |
|------|------|----------|----------|----------|
| **L1 — 克制/微妙** | Subtle | 单个面部区域的微小变化 | 需要仔细观察才能察觉 | 悬疑、心理惊悚、间谍片、高手过招 |
| **L2 — 内敛/可读** | Restrained | 2-3 个区域的协调变化 | 观众可以明确感知但角色仍在控制 | 剧情片、文艺片、大部分商业剧集 |
| **L3 — 外显/明确** | Overt | 3-4 个区域的明显变化 | 情绪清晰外露 | 商业短剧、情绪高潮段、告白/争吵 |
| **L4 — 爆发/极端** | Explosive | 全面部+身体联动 | 极端情绪宣泄 | 叙事顶点（仅限一次性使用） |

**强度使用规则：**

1. **默认 L2**——除非用户明确说"要更强烈""要更夸张""崩溃/嘶吼"等关键词
2. **L1 用于铺垫**——在情绪爆发前的数秒，先用 L1 微妙变化做铺垫
3. **L4 用一次就够**——如果整段视频都是 L4，观众会"情绪疲劳"。L4 只出现在高潮的 2-3 秒
4. **递进而非跳跃**——L1→L2→L3 是安全路径，直接跳 L1→L4 会显得虚假

**同一场景的四级范例（角色收到坏消息）：**

```text
# L1 克制/微妙
瞳孔轻微收缩，下颌微微绷紧，手指在桌面上无意识地轻轻敲击。
Pupils contracting slightly, jaw clenching faintly, fingers tapping unconsciously on the table surface.

# L2 内敛/可读（默认推荐）
眉心浅蹙，目光缓缓下移至桌面，嘴唇抿成一条线，呼吸变得又浅又轻。
Brow furrowing slightly, gaze slowly lowering to the table surface, lips pressing into a thin line, breathing becoming shallow and quiet.

# L3 外显/明确
眉头紧锁，眼眶边缘泛红，手中的纸张被不自觉攥紧，纸面因指力发出轻微皱响。
Brows knotting, rims of the eyes reddening, the paper in hand crumpling unconsciously, a faint crackling sound from the pressed paper.

# L4 爆发/极端（慎用）
双手猛然将纸拍在桌面，椅子被带着向后刮过地面，站起身肩膀剧烈起伏，泪水终于涌出。
Hands slamming the paper onto the desk, chair scraping backward, standing up with shoulders heaving violently, tears finally breaking free.
```

### 1.6 情绪 → 微表情总查表（30 种）

> **用法：** 找到情绪行 → 取「眉/眼」「嘴/颌/鼻」「呼吸/肢体」三列拼接 → 挂上 1.3 的稳定性约束 → 按「推荐镜头」写景别与运镜。
> **强度列**为默认建议值，可按 1.5 的规则上下调。

| # | 情绪（短剧标签） | 眉 / 眼 | 嘴 / 下颌 / 鼻 | 呼吸 / 肢体 | 默认强度 | 推荐镜头 |
|---|---|---|---|---|---|---|
| 1 | **爽**（打脸/逆袭/反杀） | 眼神锐利，眼神压低直视对方，笑意不达眼底 | 嘴角极轻微上扬，冷笑 | 身体几乎不动，压迫感强；背脊挺直 | L2 | 低角度特写（low angle CU）+ 硬光 + 慢推 |
| 2 | **燃**（觉醒/热血/立誓） | 目光几度涣散又猛然拉回，再睁开时目光决绝 | 咬紧牙关、颌线绷紧，深深吸气鼻翼扩张 | 双腿颤抖但强撑站立，呼吸变成喘息；全身力量贯注于动作 | L3 | 低角度仰拍追踪（low-angle tracking）+ 边缘轮廓光（rim light） |
| 3 | **虐 / 隐忍难过** | 眉心轻轻收紧，眼眶泛红，视线下垂，强忍泪水 | 嘴唇抿成一条线，鼻翼微微颤动 | 肩膀僵住，手指攥紧衣角 | L2 | 近景、侧脸特写、慢推 |
| 4 | **崩溃痛哭** | 眉毛上扬并内收，泪水滑落，眼神失焦 | 脸颊湿润，嘴角下压 | 胸口起伏，身体微微发抖 | L4 | 大特写（ECU）+ 手持微晃 |
| 5 | **无声的崩溃** | 面部肌肉扭曲但没有声音，泪水无声涌出 | 嘴角猛然下拉；嘴巴大张但喉咙锁住发不出声 | 身体开始不由自主地轻微抖动；双手抓住头发或掩住嘴，蜷缩身体 | L3 | ECU 固定机位，让表情自己说话 |
| 6 | **压抑愤怒 / 冷怒** | 眉头紧锁，目光死死盯住对方，眼神锁定不移 | 下颌绷紧，鼻翼扩张；太阳穴青筋隐约浮起 | 指节发白，呼吸变重、变短促，语速放慢反而更具压迫感 | L2 | 低角度近景、缓慢推近 |
| 7 | **爆发愤怒** | 眼睛睁大，视线锐利，目光如锥；面部血色上涌涨红 | 牙关紧咬，嘴唇张开，额头青筋微显 | 身体前倾，拳头猛然握紧；猛然拍桌/摔物/站起 | L4 | 快速推近、中近景 |
| 8 | **甜 / 温柔心动** | 眉眼放松，眼神柔软，短暂偷看后移开 | 嘴角轻轻上扬，脸颊微红 | 手指轻轻停顿，呼吸变浅 | L2 | 柔光近景、慢推 |
| 9 | **克制爱意** | 眼睫轻颤，目光停留一秒后躲开 | 嘴角想笑又压下 | 手指收紧又松开 | L2 | 过肩近景、手部特写 |
| 10 | **羞 / 娇羞** | 偷看，慌忙移开视线；眼角出现若隐若现的笑纹 | 嘴角压不住的笑，脸颊微红 | 手指无意识摩擦书角/衣角，身体微微前倾 | L2 | 阳光逆光、柔焦近景 |
| 11 | **惊 / 震惊错愕** | 眼神定住，短暂停顿，眉毛停在半抬状态 | 嘴唇微张，脸部肌肉僵住 | 身体静止，呼吸停顿一拍 | L2 | 静止近景、突然切特写 |
| 12 | **突然的领悟** | 眼神先是空白，然后一亮；瞳孔收缩了一瞬，目光骤然定格 | 嘴唇微微张开 | 呼吸短暂停滞，正在做的动作戛然而止；身体微微前倾，手中物品被忘记 | L2 | MCU→CU 快切 |
| 13 | **恐 / 惊恐害怕** | 眉毛抬高，眼睛睁大，瞳孔放大，视线快速闪动 | 嘴唇微张，嘴角下拉；喉结剧烈上下滚动 | 后退半步，肩膀缩起，颈部后缩 | L3 | 主观镜头（POV）、特写、手持 |
| 14 | **压抑的恐惧** | 瞳孔几不可见地扩张，眼神游移不定 | 嘴唇干涩微启；额头浮现细汗 | 呼吸微微加快，身体重心不自觉后移；手指轻微颤抖，握紧身边的物体 | L2 | CU + 底光（下方打光） |
| 15 | **悔 / 悔恨自责** | 眼底浮起一抹痛楚，目光向右下方飘移，眼眶边缘泛起湿意 | 唇角往下抿紧；喉结轻轻滚动 | 双手攥紧不自觉，指节发白；长长呼出一口气 | L2 | 侧脸近景、慢推、侧窗光 |
| 16 | **决 / 犹豫的决心（decision）** | 眉心浅蹙又展开，目光飘移后强迫自己拉回；深吸一口气再猛然睁眼——泪光清晰可见但目光重新变得坚定 | 嘴唇张合欲言又止 | 手部出现极细微的颤抖，呼吸变得短促不稳；随后身体重新挺直 | L3 | 135mm ECU + 呼吸焦点游移 |
| 17 | **不甘屈辱** | 眼神倔强，含泪不落，眼眶泛红 | 下颌紧绷，嘴唇抿紧 | 背脊挺直，拳头藏在身侧 | L3 | 低角度近景、慢推 |
| 18 | **嫉妒酸涩** | 目光停在对方身上，迅速移开；笑容不达眼底 | 嘴角僵硬 | 手指捏紧杯沿 | L2 | 侧脸特写、前景遮挡 |
| 19 | **心虚慌乱** | 眼神躲闪，不敢直视 | 嘴角轻微抽动，吞咽，下巴回缩 | 手指摩擦袖口，身体微偏 | L2 | 中近景、过肩镜头 |
| 20 | **伪装的从容** | 面部刻意维持平静，但瞳孔微微震颤出卖了真实情绪；眼神在对方低头时快速飘向出口 | 嘴角挂着得体的微笑，但笑意不达眼底 | 呼吸刻意保持平稳但吸气间隔变短，手心出汗但擦在腿侧；手指在桌面下悄悄攥紧 | L1 | MS/MCU 固定机位 |
| 21 | **冷漠疏离** | 眼神平静空洞，看向远处 | 面部放松但无笑意，嘴角平直 | 身体保持距离，动作克制 | L1 | 中景、侧面构图、冷光 |
| 22 | **阴冷威胁** | 眼神压低，直视镜头 | 嘴角极轻微上扬，笑意冰冷 | 身体几乎不动，压迫感强 | L2 | 低角度特写、硬光 |
| 23 | **虚伪假笑** | 眼神冷淡，停留过久，眼周无变化 | 嘴角上扬但笑容僵硬 | 颈部僵住，动作过分礼貌 | L2 | 正面近景、静止镜头 |
| 24 | **失望麻木** | 眉眼下垂，眼神涣散，视线越过对方 | 脸部失去力量，嘴唇微微分开 | 肩膀慢慢垮下 | L2 | 慢拉远、窗边侧脸 |
| 25 | **疲惫绝望** | 眼皮沉重，眼神空洞，无聚焦 | 脸色苍白，嘴唇干涩 | 身体靠墙下滑，动作迟缓 | L3 | 暗光中景、慢拉远 |
| 26 | **疲惫的坚持** | 目光涣散了一瞬又咬牙聚焦回来 | 额头汗水混着灰尘，嘴唇干裂；喉结艰难吞咽 | 手臂微颤地撑起身体，关节处布满汗渍；双腿颤抖但强撑站立 | L2 | MS 手持 + 顶光 |
| 27 | **欣慰释然 / 复杂的释然** | 眉头慢慢舒展，泪光在眼中摇晃但带着一点温度，眼里含泪但带笑 | 嘴角同时上扬和下抿形成矛盾的弧线 | 长长呼出一口气，肩膀放松下沉，身体的紧绷一点点卸掉 | L2 | 暖光近景、慢拉远 |
| 28 | **谨慎的关怀** | 目光柔和地注视着对方，但对方一回头立刻收回，面色恢复平淡 | 唇角不易察觉地抽动 | 无意识地将手伸向对方方向，又自然地收回放在其他物体上 | L1 | OTS 近景 + 浅景深 |
| 29 | **不安的期待** | 瞳孔微微扩张，目光反复扫向某个方向，眉心微拧 | 嘴唇不自觉地被咬住 | 身体坐立不安，腿在轻轻抖动，手反复握拳松开 | L2 | MS 固定 + 前景遮挡 |
| 30 | **疑惑警觉** | 眉头单侧微挑，眼睛微眯，视线扫过细节，停顿 | 唇线平直 | 头部轻微偏转，呼吸变轻，身体僵住 | L1 | 中近景、缓慢横移 |
| 31 | **厌恶** | 眉毛内侧下压，眼睛微眯 | 上唇上提、鼻翼皱起，鼻梁上浮现细微皱纹 | 头微偏转，身体后仰 | L2 | CU 侧 45° |

#### 情绪 → 可直接粘贴的整句提示词

| 情绪 | 中文整句（粘贴到「可观察表情」段） | English one-liner |
|---|---|---|
| 爽/打脸 | `冷笑，眼神锐利，嘴角极轻微上扬，压迫感直视，身体静止不动，低角度特写，硬光阴影` | `low-angle close-up, faint cold smirk, sharp piercing gaze, body completely still, hard shadows` |
| 燃/觉醒 | `眼神几度涣散又猛然拉回，咬紧牙关颌线绷紧，深深吸气鼻翼扩张，双腿颤抖但强撑站立，全身力量贯注于动作` | `gaze flickering then snapping back into focus, jaw locking tight, deep inhale expanding the nostrils, legs trembling but holding the stance` |
| 虐/隐忍 | `眉心轻轻收紧，眼眶泛红，嘴唇抿成一条线，下唇轻微颤抖，肩膀僵住，手指攥紧衣角` | `brows gently pulled together, red watery eyes, lips pressed into a thin line, lower lip trembling slightly, shoulders stiff` |
| 崩溃痛哭 | `眉毛上扬并内收，脸颊湿润，嘴角下压，泪水滑落，眼神失焦，胸口起伏，身体微微发抖` | `inner brows raised and pulled together, cheeks wet, mouth corners pulled down, tears rolling, unfocused gaze, chest heaving` |
| 无声崩溃 | `嘴角猛然下拉，面部肌肉扭曲但没有声音，泪水无声涌出，身体开始不由自主地轻微抖动` | `mouth corners pulling down sharply, facial muscles contorting silently, tears welling up without sound` |
| 压抑愤怒 | `眉头压低，下颌逐渐绷紧，鼻翼扩张，太阳穴青筋隐约浮起，眼神锁定不移，指节发白，呼吸变重` | `brows lowering, jaw gradually tightening, nostrils flaring, veins faintly pulsing at the temples, gaze locking forward, white knuckles, heavy breathing` |
| 爆发愤怒 | `牙关紧咬，嘴唇张开，额头青筋微显，眼睛睁大视线锐利，身体前倾，拳头猛然握紧` | `eyebrows knitted together tightly forming deep vertical wrinkles, teeth gritted, intense fierce glare, body leaning forward, fists clenching` |
| 甜/心动 | `眼神柔软，嘴角轻轻上扬，脸颊微红，短暂偷看后移开，手指轻轻停顿，呼吸变浅` | `eyes softening, corners of the mouth lifting gently, cheeks slightly flushed, a brief glance then looking away, fingers pausing` |
| 克制爱意 | `嘴角想笑又压下，眼睫轻颤，目光停留一秒后躲开，手指收紧又松开` | `the corners of the mouth almost smiling but held back, eyelashes trembling slightly, gaze lingering then escaping, fingers tightening then releasing` |
| 羞/娇羞 | `偷看后慌忙移开视线，脸颊微红，嘴角压不住的笑，手指无意识摩擦书角` | `a stolen glance then hastily looking away, cheeks flushing, an uncontainable smile at the corner of the mouth` |
| 惊/震惊 | `嘴唇微张，脸部肌肉僵住，眉毛停在半抬状态，眼神定住，身体静止，呼吸停顿一拍` | `lips parting slightly, facial muscles freezing, brows halted mid-lift, gaze fixed, breathing pausing for a beat` |
| 突然领悟 | `眼神先是空白然后一亮，嘴唇微微张开，呼吸短暂停滞，身体微微前倾` | `gaze going blank then lighting up, lips parting slightly, breathing pausing momentarily, body leaning forward` |
| 恐/惊恐 | `眉毛抬高，眼睛睁大，瞳孔放大，视线快速闪动，嘴唇微张，后退半步，肩膀缩起` | `pupils dilated, eyelids wide open, mouth slightly agape, Adam's apple slowly bobbing, subtle body shivering` |
| 压抑恐惧 | `瞳孔微微扩张，嘴唇干涩微启，额头浮现细汗，手指轻微颤抖，握紧身边的物体` | `pupils dilating slightly, lips parting dry, fine sweat forming on the forehead, fingers trembling faintly` |
| 悔/悔恨 | `眼底浮起一抹痛楚，目光向右下方飘移，眼眶边缘泛起湿意，唇角往下抿紧，喉结轻轻滚动，双手攥紧指节发白` | `a flash of pain surfacing in the eyes, gaze drifting to the lower right, moisture gathering at the rim of the eyes, corners of the mouth pressing downward` |
| 决/决心 | `眉心浅蹙又展开，目光飘移后强迫自己拉回，猛然合上双眼深吸一口气，再睁开时泪光清晰可见但目光重新变得坚定，身体重新挺直` | `brow furrowing then smoothing, forcing gaze back, eyes squeezing shut with a deep breath, reopening with tears glistening yet the gaze turning resolute` |
| 不甘屈辱 | `下颌紧绷，嘴唇抿紧，眼眶泛红，眼神倔强含泪不落，背脊挺直，拳头藏在身侧` | `jaw tensed, lips pressed, rims reddening, stubborn tearful gaze refusing to spill, spine straightening, fist hidden at the side` |
| 嫉妒酸涩 | `嘴角僵硬，笑容不达眼底，目光停在对方身上迅速移开，手指捏紧杯沿` | `stiff smile that never reaches the eyes, gaze lingering on the other then snapping away, fingers gripping the cup rim` |
| 心虚慌乱 | `嘴角轻微抽动，吞咽，下巴回缩，眼神躲闪不敢直视，手指摩擦袖口，身体微偏` | `a slight twitch at the mouth corner, swallowing, chin retracting, evasive gaze, fingers rubbing the cuff` |
| 伪装从容 | `嘴角挂着得体的微笑但笑意不达眼底，眼神在对方低头时快速飘向出口，呼吸刻意保持平稳但吸气间隔变短，手指在桌面下悄悄攥紧` | `a composed polite smile that never reaches the eyes, gaze flicking to the exit when the other looks down, breathing deliberately even but shortening` |
| 冷漠疏离 | `面部放松但无笑意，嘴角平直，眼神平静空洞看向远处，身体保持距离，动作克制` | `relaxed face without a smile, mouth flat, calm hollow gaze into the distance, body keeping distance` |
| 阴冷威胁 | `嘴角极轻微上扬笑意冰冷，眼神压低直视镜头，身体几乎不动，压迫感强` | `a faint icy curl at the mouth, gaze lowered and locked on the lens, body almost motionless` |
| 虚伪假笑 | `嘴角上扬但眼周无变化，笑容僵硬，眼神冷淡停留过久，颈部僵住，动作过分礼貌` | `mouth curving up while the eyes remain unsmiling, stiff smile, cold gaze held a beat too long` |
| 失望麻木 | `眉眼下垂，脸部失去力量，嘴唇微微分开，眼神涣散视线越过对方，肩膀慢慢垮下` | `brows and eyes drooping, face losing tension, lips parting slightly, gaze unfocused past the other person, shoulders slowly collapsing` |
| 疲惫绝望 | `眼皮沉重，脸色苍白，嘴唇干涩，眼神空洞无聚焦，身体靠墙下滑，动作迟缓` | `heavy eyelids, pale complexion, dry lips, hollow unfocused gaze, body sliding down the wall` |
| 疲惫坚持 | `目光涣散了一瞬又咬牙聚焦回来，额头汗水混着灰尘，嘴唇干裂，手臂微颤地撑起身体` | `gaze losing focus for a beat then wrenched back, sweat mixed with dust on the forehead, cracked lips, arms trembling as they push the body up` |
| 欣慰释然 | `眉头慢慢舒展，嘴角自然上扬，眼里含泪但带笑，长长呼出一口气，肩膀放松` | `brows gradually smoothing, mouth lifting naturally, tears in the eyes but smiling, a long exhale, shoulders releasing` |
| 谨慎关怀 | `目光柔和地注视着对方，但对方一回头立刻收回，面色恢复平淡，无意识地将手伸向对方方向又自然地收回` | `a soft gaze resting on the other, withdrawn the instant they turn back, the hand half-reaching then returning` |
| 不安期待 | `瞳孔微微扩张，眉心微拧，嘴唇不自觉地被咬住，每隔数秒看一次某方向，手反复握拳松开` | `pupils dilating slightly, brow knitting, lip caught between the teeth, glancing in one direction every few seconds` |
| 疑惑警觉 | `眉头单侧微挑，眼睛微眯，视线扫过细节后停顿，头部轻微偏转，呼吸变轻` | `one eyebrow lifting subtly, eyes narrowing, gaze sweeping over a detail then halting, head tilting slightly` |
| 厌恶 | `眉毛内侧下压，眼睛微眯，上唇上提、鼻翼皱起，头微偏转` | `inner brows pressing down, eyes narrowing, upper lip raising, nose wrinkling, head turning away slightly` |

### 1.7 情绪弧线编排（2 秒精度时间轴）

> **微表情密集镜头的核心：** 每 2 秒一个切片，每个切片只做一个核心变化 + 一个联动细节。让情绪像水一样流动，而非像开关一样跳变。

**时间轴模板：**

```text
0-2秒：[状态建立——L1 级微妙表情 + 环境/呼吸基底]。
2-4秒：[第一波动——单个区域的 L1→L2 变化 + 一个联动细节]。
4-6秒：[波动扩散——第二个区域加入 + 矛盾/挣扎外化]。
6-8秒：[情绪积蓄——L2 持续 + 身体联动开始显现]。
8-10秒：[临界点——L2→L3 过渡 + 关键动作（如闭眼/深呼吸）]。
10-12秒：[收束/释放——情绪到达终点 + 画面趋静/渐变]。
```

**四种弧线模式：**

| 模式 | 情绪流向 | 强度走势 | 适用场景 | 核心技巧 |
|------|----------|----------|----------|----------|
| ① 渐进递增（最常用） | 平静→微波动→挣扎→积蓄→临界→释放/收束 | L1→L1→L2→L2→L3→L2/L3 | 内心挣扎、告别、痛苦的决定 | — |
| ② 反高潮收束（张力最强） | 平静→波动→加剧→即将爆发→猛然收回→强撑镇定 | L1→L2→L2→L3→L1→L1 | 克制的角色、军人/间谍、不想让别人看到脆弱 | 在观众期待 L4 爆发时突然收回到 L1，张力反而更强 |
| ③ 表面平静内心翻涌 | 面部几乎不变，只有极微小的泄漏→最后一个细节暴露真实情绪 | L1→L1→L1→L1→L1→L2 | 伪装者、社交场合强撑、"你看不出她在哭" | 全程只描写 1-2 个区域的极微变化，靠最后一个细节（如一滴泪/手指颤抖）点睛 |
| ④ 情绪过山车 | 高涨→骤落→短暂平静→再次翻涌 | L3→L1→L1→L2→L3 | 大喜大悲的反转、收到消息后的过山车反应 | 情绪骤落的瞬间（L3→L1）用"整个人停滞/空白"来表达 |

**情绪锚点法则（每切片严格遵守）：**

| 规则 | 正确做法 | 错误做法 |
|------|----------|----------|
| 核心变化唯一 | `眼神忽地一颤，瞳孔轻微收缩` | `瞳孔收缩+眉头紧锁+嘴唇颤抖+泪水涌出` |
| 联动细节具体 | `持枪的手出现极细微的抖动，枪口随之轻轻一晃` | `身体语言表现出紧张` |
| 变化有方向性 | `目光犹豫地向右下方飘移` | `目光不安地移动` |
| 与上一切片衔接 | `又强迫自己拉回，重新盯住镜头` | 无前后因果关系 |

**情绪转变的触发词：**

- 转折类：`突然`、`瞬间`、`猛然`、`骤然` — 触发快速情绪变化
- 渐变类：`逐渐`、`慢慢`、`一点点` — 触发缓慢情绪过渡
- 对比类：`从....变成....` — 触发情绪前后反差

**情绪参考素材绑定（多模态）：**

```text
情绪和表情完全参考@视频1
崩溃大叫的程度参考@视频1
姿势参考@图片2
```

### 1.8 微表情 × 镜头联动表

#### 景别 × 可描写面部区域

| 景别 | 可见面部细节 | 推荐描写区域 | 联动身体区域 |
|------|-------------|-------------|-------------|
| **ECU** 极致特写（瞳孔/唇部） | 瞳孔纹理、睫毛颤动、唇角微颤、汗珠滑动 | 单一区域的极致细节 | 无（画面仅有面部局部） |
| **CU** 特写（面部） | 全面部表情、眼神方向、嘴唇动作、皮肤质感 | 2-3 个区域协调 | 呼吸起伏、颈部 |
| **MCU** 中近景（头肩） | 面部整体轮廓、大幅表情、头部动作 | 1-2 个区域的明显变化 | 肩部、手部、上身姿态 |
| **MS** 中景（腰部以上） | 面部表情大轮廓、头部转向 | 仅整体情绪基调 | 手部、身体姿态、重心 |

> **崩坏风险提示（与景别成反比）：** 远景 ELS 100% 安全 → 全景 LS 80% → 中景 MS 60%（推荐主力景别）→ 近景 CU 40% 需要精修 → 特写 ECU 20% 必须精修或真人驱动。

#### 焦段 × 微表情效果

| 焦段 | 微表情效果 | 最佳搭配 |
|------|-----------|----------|
| **85mm** | 轻度压缩，面部柔和，适合 L2 级内敛表情 | CU 特写 + 浅景深散景 + 柔光 |
| **135mm** | 极致压缩，面部充满画面，放大一切微表情 | ECU/CU + 奶油散景 + 呼吸焦点 |
| **50mm** | 自然视角，面部不变形，适合对话中的表情 | MCU + 中等景深 + 稳定运镜 |

#### 运镜 × 微表情配合

| 运镜 | 表情配合 | 提示词范式 |
|------|----------|-----------|
| **极缓推进** | 情绪渐强——镜头推近 = 情绪压力递增 | `缓慢推进至面部特写，情绪从克制逐渐外溢` |
| **固定机位** | 让表情自己说话——镜头不动，所有变化由表情承载 | `镜头固定不动，所有叙事由面部微表情推进` |
| **手持微晃** | 增加"在场感"——仿佛另一个人在近距离注视 | `手持拍摄带有自然的呼吸起伏，增强亲密旁观感` |
| **呼吸焦点** | 焦点微微前后游移，暗示不安/紧张 | `呼吸焦点轻微游移，配合角色内心的不确定` |

#### 光影 × 微表情配合

| 光影手法 | 表情效果 | 提示词范式 |
|----------|----------|-----------|
| **侧光** | 面部一半在光一半在影，暗示矛盾/双面性 | `侧窗光将面部分为明暗两半，情绪在光影交界处渗透` |
| **底光** | 从下方打光，制造不安/恐怖感 | `微弱底光打亮下巴和鼻底，上眼眶陷入阴影` |
| **逆光剪影** | 面部细节被隐藏，只留轮廓，适合压抑的克制 | `逆光中面部细节隐入暗处，仅轮廓线可辨` |
| **柔光** | 柔化面部，适合温柔/悲伤的内敛情绪 | `柔和的散射光包裹面部，皮肤呈现温润质感` |

#### 镜头 → 情绪任务对照

| 镜头 | 适合表现 | 提示词重点 |
|---|---|---|
| 大特写 | 眼泪、嘴唇颤抖、瞳孔变化 | `eye detail, trembling lips, skin texture` |
| 侧脸近景 | 隐忍、孤独、心碎 | `side profile, red eyes, restrained tears` |
| 过肩镜头 | 对峙、心虚、关系拉扯 | `over-the-shoulder, avoiding eye contact` |
| 低角度近景 | 压迫、威胁、反击 | `low angle, sharp gaze, tense jaw` |
| 慢推近景 | 情绪升级、真相揭开 | `slow push-in, gradual expression change` |
| 慢拉远 | 失落、绝望、被抛弃 | `slow pull-back, small lonely figure` |
| 手部特写 | 克制、紧张、嫉妒 | `clenched fingers, trembling hand, white knuckles` |
| 前景遮挡 | 悬疑、窥视、隐秘情绪 | `foreground obstruction, hidden expression` |

### 1.9 情绪递进模板（中英双语，可直接粘贴）

**从平静到崩溃：**

```text
近景，角色原本保持平静，眉心逐渐收紧，眼眶慢慢泛红，嘴唇抿紧后轻轻颤抖，一滴眼泪滑落，肩膀微微发抖，动作缓慢克制，柔和侧光，浅景深，consistent face, subtle micro expressions, no flickering
```

```text
close-up shot, the character tries to stay calm, brows slowly tightening, eyes gradually turning red, lips pressed together then trembling slightly, one tear rolling down the cheek, shoulders shaking subtly, slow restrained motion, soft side lighting, shallow depth of field, consistent face, subtle micro expressions, no flickering
```

**从隐忍到愤怒爆发：**

```text
中近景慢推，角色沉默盯着对方，眉头压低，下颌逐渐绷紧，鼻翼扩张，手指慢慢攥成拳，眼神从克制变得锋利，冷色硬光，低压氛围，consistent face, natural expression, fluid motion
```

```text
medium close-up slow push-in, the character silently stares at the other person, brows lowering, jaw gradually tightening, nostrils flaring, fingers slowly clenching into a fist, eyes shifting from restraint to sharp anger, cold hard lighting, tense atmosphere, consistent face, natural expression, fluid motion
```

**从心动到克制：**

```text
柔光近景，角色短暂抬眼看向对方，眼神变得柔软，嘴角几乎要笑又压下，眼睫轻颤，手指停顿在杯沿，随后轻轻移开视线，温暖逆光，浅景深，consistent face, delicate micro expression
```

```text
soft close-up shot, the character briefly looks at the other person, eyes softening, the corners of the mouth almost smiling but held back, eyelashes trembling slightly, fingers pausing on the cup rim, then gently looking away, warm backlight, shallow depth of field, consistent face, delicate micro expression
```

**从震惊到麻木：**

```text
静止近景，角色听到真相后嘴唇微张，眼神定住，脸部肌肉僵住，几秒后眼神慢慢失焦，肩膀无力下垂，背景虚化，冷灰色调，no exaggerated expression, realistic face, no flickering
```

```text
static close-up shot, after hearing the truth, the character's lips part slightly, eyes freeze, facial muscles become still, after a few seconds the gaze slowly loses focus, shoulders dropping weakly, blurred background, cold gray tone, no exaggerated expression, realistic face, no flickering
```

### 1.10 微表情密集镜头模板（表情特写 / 心理戏）

> 专用于"表情承载叙事"的场景（无声对峙、内心挣扎、告别）。普通对白场景用第二章的对白模板。

**中文模板：**

```text
[时长]写实风格，电影级[光影质感]，色彩自然。
手持拍摄，带有自然的人类呼吸起伏和手持感。[焦段]浅景深，[景别]聚焦人物面部。
0-2秒：[状态建立——L1 级微妙表情 + 环境/呼吸基底]。
2-4秒：[第一波动——单个区域的 L1→L2 变化 + 一个联动细节]。
4-6秒：[波动扩散——第二个区域加入 + 矛盾/挣扎外化]。
6-8秒：[情绪积蓄——L2 持续 + 身体联动开始显现]。
8-10秒：[临界点——L2→L3 过渡 + 关键动作（如闭眼/深呼吸）]。
光影：[光源层 + 光行为层 + 色调层]。
音效：[极简环境音/呼吸声]。
禁止：任何文字、字幕、LOGO或水印
```

**English:**

```text
[Duration] realistic cinematography, [lighting quality], natural colors.
Handheld camera with natural breathing sway. [Focal length] shallow depth of field, [shot size] on subject's face.
0-2s: [State establishment—L1 subtle expression + environment/breathing baseline].
2-4s: [First ripple—single zone L1→L2 + one co-movement detail].
4-6s: [Ripple spreading—second zone joining + conflict/struggle externalizing].
6-8s: [Emotion building—L2 sustained + body co-movement emerging].
8-10s: [Threshold—L2→L3 transition + key action (e.g., eyes closing / deep breath)].
Lighting: [source layer + behavior layer + tone layer].
SFX: [minimal ambient / breathing].
Negative: any text, subtitles, logos or watermarks
```

**填充示例 — 持枪内心挣扎（12 秒，I2V，渐进递增弧线 L1→L2→L3→L2）：**

```text
写实风格，电影级柔和光影，色彩自然。
手持拍摄，带有自然的人类呼吸起伏和手持感。极端近景特写，135mm浅景深，前景严重虚化，聚焦人物面部。
0-2秒：保持原始构图和色彩。枪口稳稳指向镜头；眼神冷峻而克制，下颌微微绷着，轻微呼吸起伏和发丝被风吹动。
2-4秒：眼神忽地一颤，瞳孔轻微收缩，眉心浅蹙旋即展开；唇角不易察觉地抽动，持枪的手出现极细微的抖动，枪口随之轻轻一晃。
4-6秒：目光犹豫地向右下方飘移，又强迫自己拉回，重新盯住镜头，眼底浮起一抹痛楚；嘴唇张开一丝缝隙，欲言又止，最终无声合拢，喉结轻轻滚动。
6-8秒：眉头微微皱起又马上展开，眼眶边缘泛起湿意；枪口微微下沉但仍保持朝向镜头，下巴轻颤，呼吸变得短促不稳。
8-10秒：猛然合上双眼，深吸一口气，眼皮不住轻颤；再度睁开时，泪光已清晰可见，眼神脆弱而挣扎，枪口被重新持平，手臂的颤抖通过枪身隐隐透出。
10-12秒：唇角往下抿紧，强忍着即将漫出的哭意，枪口开始缓慢地、一点点降低。
光影：柔和自然侧光+皮肤次表面散射(光源层)，呼吸焦点微微游移+前景虚化过渡(光行为层)，自然温暖肤色+冷灰背景(色调层)。
音效：极轻的呼吸声、衣物布料微响、风声低吟。
禁止：任何文字、字幕、LOGO或水印
```

**短版范式（表情只是场景的一部分时，2-3 行集成即可）：**

```text
保留原始构图和色彩。
0-3秒：角色目光冷峻注视前方不动，仅呼吸起伏和发丝微动。
3-6秒：眉心浅蹙旋即展开，嘴角微微抽动，目光中闪过一丝犹豫。
6-8秒：缓慢推进至面部极致特写，眼底浮起一抹湿意，深吸一口气后面部恢复克制。
光影：自然柔光+皮肤真实质感(光源层)，浅景深前景虚化(光行为层)，自然色温(色调层)。
音效：轻微的呼吸声、环境风声。
禁止：任何文字、字幕、LOGO或水印
```

### 1.11 单元素模板库（可直接粘贴）

**单人情绪特写模板：**

```text
close-up shot, slow push-in, [角色外貌一致性描述], [情绪状态], brows [眉毛细节], eyes [眼神细节], lips [嘴部细节], jaw [下颌细节], shoulders [身体反应], slow subtle motion, cinematic lighting, shallow depth of field, photorealistic, consistent face, natural facial anatomy, no flickering, no face distortion
```

**双人对峙模板：**

```text
medium close-up, over-the-shoulder composition, [角色A] facing [角色B], tense silence, [角色A表情细节], avoiding or holding eye contact, fingers slowly clenching, cold side lighting, shallow depth of field, cinematic drama, consistent face, no extra hands, no distorted faces, no flickering
```

**哭戏模板：**

```text
extreme close-up, the character tries not to cry, inner brows raised and pulled together, red watery eyes, lower lip trembling, lips pressed tightly, one tear slowly rolling down the cheek, shoulders shaking slightly, soft side light, quiet emotional atmosphere, realistic skin texture, consistent face, no exaggerated crying, no distorted mouth
```

**愤怒模板：**

```text
low-angle close-up, slow push-in, the character suppresses anger, brows pressed down, eyes locked onto the opponent, jaw clenched, nostrils slightly flaring, white knuckles, heavy breathing, hard cold lighting, tense cinematic mood, consistent face, natural expression, no flickering
```

**心动模板：**

```text
soft close-up, warm backlight, the character briefly glances at the other person, eyes softening, subtle smile almost appearing then held back, eyelashes trembling, cheeks slightly flushed, fingers pausing gently, shallow depth of field, romantic cinematic tone, consistent face, delicate micro expressions
```

**黑化模板：**

```text
close-up shot, low-key lighting, the character's expression slowly turns cold, relaxed face with a faint controlled smile, eyes becoming sharp and unreadable, chin slightly lowered, body completely still, dark cinematic shadows, high contrast, consistent face, no exaggerated evil smile, no flickering
```

**最小可用提示词：**

```text
close-up shot, slow push-in, consistent character face, restrained sadness, brows gently pulled together, red watery eyes, lips pressed into a thin line, lower lip trembling slightly, shoulders stiff, soft side lighting, shallow depth of field, cinematic realism, subtle micro expressions, no exaggerated expression, no flickering, no face distortion
```

```text
近景慢推，角色强忍难过，眉心轻轻收紧，眼眶泛红，嘴唇抿成一条线，下唇轻微颤抖，肩膀僵住，柔和侧光，浅景深，电影感写实，细腻微表情，不要夸张表情，不要脸部变形，不要闪烁
```

### 1.12 按题材的情绪基调速查

| 题材 | 情绪关键词串（可直接粘贴） |
|---|---|
| 霸总虐恋 | `克制愤怒、强忍心痛、眼眶泛红但不落泪、下颌绷紧、冷漠表情下藏着痛苦、低声压抑、慢推近景、冷色办公室灯光` |
| 复仇爽剧 | `冷笑、眼神锐利、嘴角极轻微上扬、压迫感直视、身体静止不动、低角度特写、硬光阴影、黑金色调` |
| 家庭伦理 | `失望、委屈、欲言又止、嘴唇颤抖、眼眶湿润、手指攥紧围裙或衣角、暖色室内光、生活化中近景` |
| 悬疑反转 | `警觉、怀疑、眼睛微眯、视线扫过线索、呼吸变轻、身体僵住、前景遮挡、低照度、冷绿色调、缓慢横移镜头` |
| 校园暗恋 | `偷看、慌忙移开视线、脸颊微红、嘴角压不住的笑、手指无意识摩擦书角、阳光逆光、柔焦近景` |
| 古装权谋 | `隐忍、克制、礼貌假笑、眼神冷淡、袖中手指攥紧、微微低头但目光上挑、烛光、屏风前景、对称构图` |

### 1.13 表情负面词与故障排查

**通用负面词（英文）：**

```text
bad anatomy, distorted face, asymmetrical eyes, crossed eyes, extra teeth, deformed mouth, frozen face, plastic skin, uncanny smile, exaggerated expression, flickering, changing face, changing hairstyle, changing outfit, extra fingers, extra hands, blurred facial features
```

**中文负面约束：**

```text
不要夸张表情，不要脸部变形，不要眼睛错位，不要牙齿异常，不要嘴巴畸形，不要假笑感，不要表情僵硬，不要换脸，不要换发型，不要换服装，不要闪烁，不要多手指
```

**常见问题修正表：**

| 问题 | 修正方法 |
|---|---|
| 角色没情绪 | 把"悲伤/愤怒"改成眉、眼、嘴、下颌、手指、呼吸的细节 |
| 表情太夸张 | 加 `subtle micro expressions, restrained emotion, no exaggerated expression` |
| 哭戏假 | 写"一滴眼泪、眼眶泛红、下唇颤抖"，不要写"大哭" |
| 笑容假 / 像面具 | 区分"眼周参与的真笑（鱼尾纹）"和"眼周无变化的假笑"；确保眼轮匝肌收缩 |
| 脸变形 | 加 `natural facial anatomy, realistic eyes, no face distortion` |
| 镜头总是中景 | 把 `extreme close-up / close-up / low-angle` 放在提示词开头 |
| 情绪不连贯 | 每个镜头只推进一个情绪阶段，不要一条提示词写完整情绪转折 |
| 表情突变 | 关键帧间加中间情绪帧，用 ease-in-out；先笑容消退(8帧)→中性过渡(4帧)→悲伤浮现(12帧) |
| 眨眼不自然 | 添加随机眨眼（每 2-6 秒一次，非等间距） |
| 眼神空洞 | 后期添加眼部高光点，或在参考中加入视线引导 |
| 说话时面部僵硬 | 分层合成：先表情后口型，口型仅影响下半脸 |

**表情过渡时间规律（写时间轴时的物理下限）：**

```text
微表情（involuntary）：0.04-0.2s（1-5帧）
常规表情变化：0.5-1.0s（12-24帧）
情绪氛围转换：1.0-3.0s（24-72帧）

❌ 错误：2帧内从笑变哭（机械感）
✅ 正确：先笑容消退(8帧) → 中性过渡(4帧) → 悲伤浮现(12帧)
```

---

## 二、台词与口型

### 2.1 核心原则

1. **一句台词 = 文本 + 语速 + 情绪 + 停顿 + 重音**，缺一不可。只给文本，AI 会输出"念稿"式的平淡声音。
2. **情绪要具体、可执行**，避免抽象词。不要只写"生气"，而写"压抑的愤怒，声音发抖但音量克制"。
3. **语速服务于情绪与节奏**，不是独立参数。紧张=快，悲伤=慢，是情绪驱动语速。
4. **短剧节奏比影视快 20%–30%**。短视频用户耐心低，台词要"密、爽、钩子前置"。
5. **口语化优先**，书面语是 AI 配音的天敌。多用短句、语气词、断句。

### 2.2 台词行格式规范（平台统一写法）

| 声音类型 | 提示词写法 | 强制附加项 |
|----------|-----------|--------|
| **对白**（角色说话） | `台词（角色，情绪）："内容"` | 无额外禁止 |
| **画外音 / 内心独白** | `画外音："内容"` | **必须追加：** `禁止：画面中角色出现说话口型` |
| **旁白** | `旁白（音色描述）："内容"` | 与对白区分：客观、抽离、不带角色情绪 |
| **方言** | `台词（角色，情绪，四川口音）："内容"` | 方言写法直接嵌入台词行即可，无需额外参数 |
| **多语言** | `台词（角色A，用西班牙语，坚定）："内容"` | 各角色分别标注语言 |

**独白 vs 对白 vs 旁白（三种口吻必须分开）：**

| 类型 | 对象感 | 语气特征 | 提示写法 |
|---|---|---|---|
| 对白 | 对着另一个角色 | 有互动、有攻防 | `对话感、语气有指向` |
| 独白/内心 OS | 对自己/观众 | 私密、放松、更慢 | `内心独白、气声、放慢、贴近麦` |
| 旁白 | 全知视角 | 客观、抽离 | `旁白、沉稳、不带角色情绪` |

> 常见错误：把内心独白配成对白语气，显得"用力过猛"。内心戏要更轻、更慢、更贴。

### 2.3 语速分级表（中文普通话）

| 等级 | 字/分钟 | 适用场景 | 提示词写法 |
|---|---|---|---|
| 极慢 | 120–180 | 临终、回忆、旁白煽情、悬念铺垫 | `语速极慢，字字停顿，带哽咽感` |
| 慢速 | 180–240 | 悲伤、深情、思考、庄重宣告 | `语速放缓，情绪沉重` |
| 常速 | 240–300 | 日常对话、叙述、口播 | `正常语速，自然流畅` |
| 偏快 | 300–360 | 争吵、催促、兴奋、爽点爆发 | `语速加快，情绪上扬` |
| 极快 | 360+ | 慌乱、逃跑、连珠炮质问、搞笑 | `语速极快，急促连贯不换气` |

> **短剧默认基线：270–320 字/分钟**，比传统影视快。
> TTS 生成参数：语速 **0.9-1.0x**（过快口型跟不上）。

**语速动态变化（同一句内变速）：**

```text
前半句平稳，后半句突然加快带质问语气：
"我本来什么都不想说的——可你居然连这个都骗我？！"
```

### 2.4 情绪三层写法

写情绪时同时描述这三层，AI 输出才立体：

1. **情绪类型**：喜、怒、哀、惧、惊、厌、爱
2. **强度/克制度**：爆发 vs 压抑（同样是怒，摔门大吼 ≠ 咬牙冷笑）
3. **生理表现**：颤抖、哽咽、冷笑、气音、鼻音、喘息

| 平淡写法（差） | 立体写法（好） |
|---|---|
| 生气地说 | 压抑的愤怒，音量不高但一字一顿，尾音发冷 |
| 开心地说 | 抑制不住的雀跃，语速偏快，带笑音，句尾上扬 |
| 难过 | 强忍哭腔，声音发闷，中途有一次吸气停顿 |

**情绪声音词库：**

| 类别 | 情绪 | 声音提示词 |
|---|---|---|
| 正向 | 温柔 | `气声、轻柔、语调平缓、句尾下沉` |
| 正向 | 喜悦 | `语调上扬、带笑意、语速轻快` |
| 正向 | 兴奋 | `高音量、语速快、语气亢奋、句末拔高` |
| 正向 | 深情/告白 | `低沉磁性、放慢、真诚、微微气音` |
| 负向 | 悲伤 | `哽咽、颤音、语速慢、有停顿、鼻音重` |
| 负向 | 愤怒（爆发） | `高音量、咬字重、语速快、破音` |
| 负向 | 愤怒（隐忍） | `低音量、冷、一字一顿、尾音发抖` |
| 负向 | 恐惧 | `气息不稳、语速忽快忽慢、颤抖、音调偏高` |
| 负向 | 委屈 | `带哭腔、音量小、语调下坠、撒娇式尾音` |
| 负向 | 冷漠/嘲讽 | `平淡、冷笑、拉长音、阴阳怪气` |
| 中性 | 旁白 | `沉稳、客观、中速、清晰` |
| 中性 | 悬念铺垫 | `压低声音、放慢、制造停顿` |

**情绪标签库（用于 `台词（角色，情绪）` 的情绪位）：**

| 类别 | 标签 |
|------|------|
| 正面 | 欢快 / 温柔 / 自信 / 坚定 / 感动 / 兴奋 |
| 负面 | 愤怒 / 悲伤 / 恐惧 / 冷漠 / 颤抖 / 绝望 |
| 中性 | 平静 / 疑惑 / 思考 / 叙述 / 旁白 |

**情绪 × 语速 × 音高 × 停顿对照（TTS 参数化）：**

| 情绪 | 语速 | 音高 | 音量 | 停顿特征 |
|------|------|------|------|---------|
| 平静 | 1.0x | 基准 | 中 | 规律停顿 |
| 愤怒 | 1.1x | 偏高 | 大 | 短促、少停顿 |
| 悲伤 | 0.85x | 偏低 | 小 | 长停顿、句末拖音 |
| 紧张 | 1.05x | 略高 | 中 | 不规则碎停顿 |
| 喜悦 | 1.05x | 偏高 | 中-大 | 轻快、起伏大 |

**SSML 风格情绪标注（按工具支持调整）：**

```text
平静：<prosody rate="1.0" pitch="0">...</prosody>
愤怒：<prosody rate="1.1" pitch="+2st" volume="loud">...</prosody>
悲伤：<prosody rate="0.85" pitch="-2st" volume="soft">...</prosody>
紧张：<prosody rate="1.05"> ...<break time="0.2s"/>... </prosody>
```

### 2.5 停顿、气口、重音与语气词

**停顿标记：**

- 短停顿（0.3s 左右）：用逗号或 `,`
- 中停顿（0.5–1s）：用 `……` 或换行
- 长停顿/留白（>1s）：显式标注 `[停顿1秒]`

```text
你……[停顿]是不是早就知道了？
```

**重音标注：**

```text
是"你"让我变成这样的。   ← "你"重读
我从来【没有】怪过你。   ← 【】内重读
```

**语气词与呼吸声：**

```text
语气词：啊、吧、呢、嘛、哈、哼、唉、嗯
呼吸声标记：[吸气][叹气][冷笑一声]

[叹气] 唉……算了吧。
[冷笑] 哼，你还真敢说。
```

**气口设计（对白"像活人说话"的关键）：**

```text
- 句末换气：长句中段插入 0.15-0.2s 微停顿（模拟换气）
- 呼吸声：情绪戏可保留轻微吸气声（增强真实感）
- 避免机械匀速：重点词放慢/加重，次要词带过
- 对话留白：角色之间留 0.3-0.5s 反应间隙
- 与口型衔接：句末轻微闭口 0.2s，避免嘴部定格
- 句间停顿 0.3-0.5s，段落间 0.6-0.8s
```

**呼吸状态对照表：**

| 状态 | 呼吸提示 |
|---|---|
| 平静 | 自然，不标注 |
| 紧张/恐惧 | `急促浅呼吸、说话前吸气` |
| 剧烈运动后 | `喘息明显、说话断续、上气不接下气` |
| 悲伤压抑 | `深吸一口气再开口、中途哽住` |
| 亲密耳语 | `气声重、贴麦、几乎没有换气声` |

**音调曲线：**

- **疑问、期待、撒娇** → 句尾升调
- **陈述、失望、决绝** → 句尾降调
- **冷漠、机械、克制** → 全句平调

```text
"你真的……要走吗？"    ← 尾音升调，带不舍
"那就……这样吧。"      ← 尾音降调，认命
```

### 2.6 音色描述与一致性

**角色声音设定卡（开拍前固定，全剧复用）：**

```text
角色：[角色名]
性别/年龄：[女，25 岁]
音色：[偏低沉、微沙哑、御姐感]
基础语速：[常速偏慢]
口头禅/习惯：[句尾爱拖长音]
情绪基调：[外冷内热，克制]
```

**人声类型词库：**

| 类型 | 描述 |
|------|------|
| 旁白 | `低沉磁性男声旁白` / `温柔女声旁白` |
| 窃窃私语 | `压低声音的窃窃私语` |
| 呐喊 | `撕心裂肺的呐喊，带有声音破裂` |
| 歌唱 | `清澈女声哼唱旋律` |

**特殊音色风格：**

| 风格 | 写法（中文） | 写法（English） |
|------|------------|----------------|
| 科普解说 | `用科普节目的专业解说音色` | `Professional science documentary narration style` |
| 脱口秀 | `脱口秀式的夸张语气` | `Stand-up comedy exaggerated delivery` |
| 纪录片旁白 | `纪录片级低沉磁性旁白` | `Documentary-grade deep magnetic narration` |
| 戏曲唱腔 | `豫剧唱腔风格` / `京剧念白` | `Henan opera singing style` / `Peking opera dialogue` |
| ASMR 低语 | `ASMR式轻柔低语` | `ASMR soft whispering tone` |
| 体育解说 | `激情体育解说风格` | `Enthusiastic sports commentary style` |
| 广播电台 | `经典FM电台主持风格` | `Classic FM radio host style` |

**音色参考（Timbre Reference）：**

| 写法（中文） | 写法（English） | 适用场景 |
|------------|----------------|---------|
| `语气和音色参考@视频1` | `Voice tone and timbre reference @Video1` | 角色配音一致性 |
| `旁白音色参考@视频1中的男声` | `Narrator timbre references male voice in @Video1` | 品牌广告旁白统一 |
| `说话风格参考@视频1` | `Speaking style reference @Video1` | 特定风格解说 |

**方言与口音：**

| 方言/口音 | 中文写法 | English |
|----------|---------|---------|
| 四川话 | `用四川口音说："..."` | `Speaking in Sichuan dialect: "..."` |
| 粤语 | `用粤语说："..."` | `Speaking in Cantonese: "..."` |
| 东北话 | `用东北口音说："..."` | `Speaking in Northeast Chinese accent: "..."` |
| 台湾腔 | `用台湾腔说："..."` | `Speaking in Taiwanese Mandarin accent: "..."` |
| 日式口音 | `带日本口音的中文` | `Chinese with Japanese accent` |
| 英式口音 | `带英式口音的英语` | `Speaking in British English accent` |

**防音色漂移清单：**

```text
□ 同一角色全程用同一克隆模型 / 同一 TTS 音色 ID
□ 锁定相同的音高/语速基准（仅按情绪微调，不换音色）
□ 分集制作时记录音色配置，避免重开项目时参数丢失
□ 多角色：音色差异化（音高/音色拉开，与防串脸同思路）
```

### 2.7 对话节奏与多角色互动

**对话节奏三要素：**

1. **接话速度**：情绪越激烈，接话越快（几乎抢话）；沉默、犹豫时留白拉长。
2. **语速对比**：对话双方语速要有差异，制造张力（一个急一个稳＝压迫感）。
3. **音量落差**：一方拔高、另一方压低，比双方都吼更有戏剧性。

```text
[A-质问-语速快-音量高] 那天晚上你到底在哪？
[B-停顿0.5秒-低声-语速慢] ……你为什么突然问这个。
[A-抢话-更快] 别回避！回答我！
```

**潜台词（言外之意）——标"表面 vs 真实"：**

```text
[表面平静-实则强忍崩溃] "挺好的，你过得好就行。"
（提示：语气刻意轻松，但尾音发紧、有一瞬间气息不稳）
```

**抢白 / 打断 / 重叠：**

```text
[A] 我早就说过这件事根本不——
[B-打断-音量压过A] 够了！我不想再听你解释！
```

**多轮对话的情绪爬坡：**

```text
起：平静试探 → 承：暗流涌动 → 转：情绪爆发 → 合：爆发后的疲惫/释然
对应语速：中速 → 略快 → 极快高音量 → 骤降转慢
```

**声音表演细节（进阶）：**

| 效果 | 提示写法 |
|---|---|
| 欲言又止 | `说半句停住，[停顿]，改口` |
| 哭着说话 | `带哭腔但坚持把话说完，中间有抽气` |
| 笑着说狠话 | `语气轻笑，内容却冷，反差感` |
| 疲惫叹息式 | `每句话前先叹气，语速慢，尾音往下掉` |
| 咬牙切齿 | `音量不大但咬字极重，气从牙缝出` |

### 2.8 口型同步硬约束

> **语速在视频里不只是表演，更是时长约束。**

| 约束 | 规则 | 违反后果 |
|---|---|---|
| **先量时长再配音** | 一个镜头 3 秒，台词就得能在 3 秒内自然说完，不能硬塞 | 语速被迫失真、口型糊 |
| **口型帧率匹配** | 语速过快口型跟不上、糊嘴；过慢会有"停顿脸" | 嘴部与音频脱节 |
| **重点词卡画面重点帧** | 情绪爆发的词尽量对齐面部特写/推镜时刻 | 爽点与视觉高潮错位 |
| **静默留口型** | 角色不说话时也要有微表情/呼吸，别让脸僵死 | 面瘫脸 |
| **画外音禁口型** | 独白镜头必须写 `禁止：画面中角色出现说话口型` | 独白时嘴巴乱动 |
| **爆破音规避** | 台词设计避免连续爆破音（b/p/d/t），容易产生口型跳变 | 口型抖动 |
| **句末闭口** | 在句末添加轻微闭口动作（0.2s），避免嘴部突然定格 | 嘴部定格 |
| **对话间隙** | 对话间隙保持嘴唇自然闭合而非完全静止（添加微小呼吸动作） | 冻脸 |

```text
[镜头3秒-中速-口型清晰] "我，不会走。"   （3字一顿，卡满3秒，配坚定表情）
```

**多语言口型契约（提示词写法）：**

```text
角色[名称/@图片N]使用[目标语言]说："[exact line]"。
音色参考@音频1，仅参考[声线、年龄感、语流、情绪]，不要把参考音频当作BGM。
演绎：[低沉悬疑/克制悲伤/活泼带货等]；断句：[说明]；口型与目标语言发音同步。
字幕：[无字幕 / 仅显示目标语言字幕，准确文本为"..."]。
```

**口型工具与音频规范：**

| 特性 | Wav2Lip | MuseTalk |
|------|---------|----------|
| 精度 | 中等 | 较高 |
| 速度 | 快 | 中等 |
| 中文支持 | 一般 | 较好 |
| 面部保真 | 下颌区域可能模糊 | 保真度更高 |
| 适用场景 | 快速预览/低成本 | 最终成片 |

```bash
# 音频降噪 + 标准化（提升口型精度）
ffmpeg -i input.wav -af "highpass=f=80,lowpass=f=8000,dynaudnorm" clean.wav
```

```yaml
# MuseTalk 参数
fps: 24
face_det_batch_size: 8
audio_feature: "hubert"        # 中文效果更好
mouth_open_ratio: 1.2          # 嘴部张开比例（中文发音需要略大）
smooth_expression: true
batch_size: 4
```

```yaml
# LivePortrait 驱动参数（表情层，口型归零交给口型层）
expression_intensity: 0.7      # 表情强度（0.5-0.8 为自然区间）
lip_ratio: 0.0                 # 嘴型由口型层单独控制，此处归零
head_pose_blend: 0.3           # 头部姿态跟随（不宜过高）
eye_blink_rate: 0.15           # 眨眼频率（每秒约3-4次正常）
smooth_factor: 0.85            # 帧间平滑
face_mask_erode: 5             # 面部遮罩收缩像素（避免边缘伪影）
```

**交付给口型层前的确认清单：**

```text
□ 格式：WAV（无损，优于 MP3）
□ 采样率：与 MuseTalk/Wav2Lip 要求一致（通常 16kHz/44.1kHz）
□ 声道：单声道（对白），口型检测更稳
□ 已降噪 + 标准化（highpass/lowpass/dynaudnorm）
□ 时长与目标画面片段对齐（音频不长于画面）
□ 中文优先 hubert 特征
□ 先做干声口型，后期再混音乐（带 BGM 的音频直接做口型会干扰检测）
```

### 2.9 字幕开关规则

| 场景 | 规则 | 提示词写法 |
|---|---|---|
| **视频模型生成阶段（默认）** | **一律关闭画面内字幕**，字幕在后期竖屏排版层加 | `禁止：任何文字、字幕、LOGO或水印` |
| **多语言/需硬字幕** | 只在契约的字幕字段显式打开，并给出准确文本 | `字幕：仅显示目标语言字幕，准确文本为"..."` |
| **完全不要字幕** | 显式声明 | `无字幕。` |
| **参考素材** | 禁止从参考视频迁移字幕 | `不要迁移@视频1中的人物外貌、背景、音轨和字幕` |
| **编辑/重生成** | 字幕列入"保持不变"字段 | `画面保持：[人物、动作、字幕、构图、画质、色调]完全不变。` |

**后期竖屏字幕规范（9:16）：**

```text
- 位置：底部安全区上方（约画面下 1/4，不贴最底）
- 字号：占画面宽度，单行不超过 14-16 字
- 样式：白字 + 黑色描边/底纹（任何背景都清晰）
- 时长：与配音同步，单句停留 ≥ 1s（够读完）
- 花字：关键反转/情绪词用花字放大、变色，不超过画面 2 处
```

### 2.10 台词文本预处理规范（送给 AI 前）

```text
1. 书面语 → 口语：`因为…所以…` → `就因为这样，我才…`
2. 长句拆短：一句不超过 20–25 字，超了就断句或加停顿
3. 数字/符号口语化：`3:00` → `三点`，`%` → `百分之`，`&` → `和`
4. 多音字标注：`还(hái)钱` / `重(chóng)来` 有歧义时注音或换词
5. 英文缩写展开或注音：`CEO` → 视情况保留或写"总裁"
6. 补语气词接口：干巴巴的句子加 `啊/吧/呢` 增自然度（勿滥用）
7. 敏感谐音规避：某些词 TTS 易读错或平台屏蔽，提前换同义词
```

### 2.11 台词提示词模板

**万能公式：**

```text
[角色] + [基础音色] + [此句情绪类型] + [情绪强度/克制度] + [语速] + [生理表现] + [停顿/重音标记] + 台词文本
```

**完整示例：**

```text
[林夏][低沉沙哑][愤怒-隐忍][语速偏慢][一字一顿、尾音发抖]
"我【从来】没有……求过你。"
```

**基础对白模板（视频提示词）：**

```text
[时长]短剧片段，[风格快选组合]，
画面（0-Xs）：[具体化景别+角度]，[场景]，
[角色A描述 + 站位]，[面部朝向 + 视线焦点]，
[运镜 + 叙事动机]。
台词（角色A，[情绪]）："[台词内容]"
画面（X-Xs）：[具体化景别+角度]，
[角色B描述 + 站位]，[面部朝向 + 视线焦点]，
[运镜 + 叙事动机]。
台词（角色B，[情绪]）："[台词内容]"
音效：[环境音/物理拟声描述]。
禁止：任何文字、字幕、LOGO或水印
```

**画外音/独白模板：**

```text
[时长]短剧片段，[风格快选组合]，
画面（0-Xs）：[具体化景别+角度]，[场景]，
[角色描述 + 站位]，[面部朝向 + 视线焦点]，
[运镜 + 叙事动机]。
画外音："[独白/旁白内容]"
音效：[环境音描述]。
禁止：任何文字、字幕、LOGO或水印；画面中角色出现说话口型
```

**场景化台词模板：**

```text
# 争吵/冲突戏
[角色A-愤怒爆发-语速快-高音量] 你凭什么替我做决定？！
[角色B-隐忍-语速慢-低音量-尾音抖] 我……是为了你好。
[角色A-冷笑-拉长音] 为我好？呵。

# 深情告白戏
[男主-低沉深情-放慢-气声][停顿]
"这些年……我一直在等你回头。[停顿1秒] 现在，我不等了——我要追上去。"

# 悬念/反转戏
[旁白-压低-放慢-制造紧张] 没有人知道，那天晚上，房间里……还有第三个人。

# 搞笑/沙雕戏
[语速极快-夸张-破音] 啊啊啊我不管我不管，今天必须给我道歉！！！
```

**按题材的台词风格速查：**

| 题材 | 台词特征 | 语速基调 | 情绪关键词 |
|---|---|---|---|
| 甜宠 | 撒娇、心动、拌嘴 | 轻快 | 娇羞、宠溺、雀跃、脸红气声 |
| 复仇/逆袭 | 打脸、宣言、反转 | 偏快，爽点处骤停重音 | 隐忍→爆发、冷笑、居高临下 |
| 悬疑/惊悚 | 试探、留白、信息差 | 慢，多停顿 | 压低、气息不稳、阴冷 |
| 虐恋/悲情 | 误会、诀别、独白 | 慢 | 哽咽、颤音、克制的崩溃 |
| 家庭伦理 | 争执、劝和、说教 | 中速 | 无奈、愤懑、语重心长 |
| 搞笑/无厘头 | 吐槽、夸张、反差 | 极快 | 夸张、破音、阴阳怪气 |

### 2.12 台词质检清单

```text
- [ ] 每句是否有明确情绪，而非"念稿"？
- [ ] 语速是否随情绪起伏，而非全程一个速度？
- [ ] 多角色声音是否可区分（音色/语速/音调有差异）？
- [ ] 同一角色全剧声线是否一致？
- [ ] 关键台词（爽点/转折/金句）重音是否突出？
- [ ] 长句是否有换气停顿，没有憋气感？
- [ ] 多音字、数字、英文是否读对？
- [ ] 情绪转折处衔接是否自然，不生硬？
- [ ] 是否有"情绪太满"的段落需要留白对比？
- [ ] 台词时长是否匹配镜头与口型？
- [ ] 画外音镜头是否都挂了 `禁止：画面中角色出现说话口型`？
- [ ] 生成阶段是否都挂了 `禁止：任何文字、字幕、LOGO或水印`？
```

---

## 三、动作戏

### 3.0 动作戏七原则（写任何一场打戏之前先过一遍）

> 下面 3.1 起全是**怎么拍**；这一节是**为什么拍**。技术全对但观众无感的打戏，问题一定出在这七条里。
> 优先级最高的是 Clarity——**其余六条全部让位于它**：观众看不懂在打什么，招式再炫也是废片。

| # | 原则 | 要求 | 违反时的症状 |
|---|---|---|---|
| 1 | **Clarity 清晰** | 观众必须跟得上每一招：谁打谁、用什么打、打中哪、结果如何 | 打得很热闹，看完不知道发生了什么 |
| 2 | **Geography 场景几何** | 人物在空间中的位置始终明确（A 在左、B 在右、距离两步、面朝彼此），每招后的位置变化可追踪 | 人物「瞬移」，观众失去方位感 |
| 3 | **Stakes 赌注** | 观众要明白「这场打输了会怎样」——生死 / 尊严 / 爱人 / 觉悟 | 沦为炫技，观众不屏息 |
| 4 | **Motivation 动机** | 每一招都由角色驱动：A 为什么主攻？B 为什么徒手？两人之前发生了什么 | 为打而打，动作与人物无关 |
| 5 | **Choreography 编排** | 招式有创意、有逻辑、有节奏，符合人物与武术体系 | 「轻微换姿势」、抽象招式 |
| 6 | **Vulnerability 脆弱** | 角色要被真实威胁：失刀那一刻、倒地那一刻，双方都在极限 | 主角无敌，紧张感为零 |
| 7 | **Consequences 后果** | 打斗有真实代价：衣袂破损、喘息加重、汗水滑下、重心崩溃 | 打完衣服还是干净的，观众不信 |

**落到分镜表上**：Stakes 与 Motivation 写进场次说明（不进提示词）；Clarity / Geography 靠 3.8 的左右锚定与景别编排保证；Vulnerability / Consequences 必须逐镜写成**可见的画面**——见 3.2 五件套的第 3、4 项与「服装状态一旦变化必须被后续继承」。

**通用四段结构**（对打段落的骨架，可按时长伸缩）：

```text
起势段（1-2 镜）：亮相 / 架势 / 对峙       —— 建立 Geography 与 Stakes
进攻段（约 1/3）：抢攻 / 压制 / 连击        —— 建立 Motivation
防御反击段（约 1/3）：闪身 / 格挡 / 反制    —— 建立 Vulnerability
收势段（1-2 镜）：终结击 / 定格 / 收招      —— 交付 Consequences
```

- **双人对练**：每一镜必须同时写 A（主动）与 B（被动）两个角色，并标注两人的空间关系（距离 / 朝向），不能只写出招方。
- **腾空 / 跌落动作**：一个 15 秒段落里最多 2 镜（跨镜漂移率极高），且必须选定格清晰的瞬间（「空中下劈定格」而不是「翻滚中段」）。

---

### 3.1 动作戏总原则

> 动作场景在 AI 视频生成中是崩坏率最高的区域。必须舍弃让 AI 在单镜中完成复杂对打的幻想。

| 原则 | 具体值 | 原因 |
|---|---|---|
| 单镜时长 | **1.5–2.5 秒**，禁止长段乱动 | 多肢体高频互动的穿模率高达 90% |
| 分镜拆分率 | **> 80%**，动作戏绝不使用超过 3 秒的长镜头 | 快切节奏 + 规避穿模 |
| 抽象动词禁令 | 禁写"飞踢/激烈格斗/降龙十八掌" | AI 生成"假人比划"或身体漂浮、失去重力 |
| 同框禁令 | 不强求 AI 在同一镜中生出"A 打中 B 且 B 倒地" | 胳膊长在一起、身体融为一体 |
| 复杂度分级 | 多主体复杂互动（打斗）属最低成功率梯队 | 优先走关键帧优先或白模流水线 |
| 动作单元 | **每段 2–4 秒，只做 1 个动作单元** | 一个单元 = 蓄力/起手 → 挥出 → 撞击打点 → 受击反馈 中的一环 |
| 连招禁令 | **禁止单段生成 8–12 秒的完整连招** | 帧间位移累积过大，中段必崩 |
| 大旋转禁令 | **禁止复杂 360° 大旋转镜头** | 环绕过程中人物背面无参考，脸与服装必漂移 |
| 形象锁 | 每段都上传角色参考图并开启形象锁 | 打戏景别切换频繁，是跨镜换脸的重灾区 |
| 风格统一 | 全段统一风格词，**不混搭水墨 / 赛璐珞 / 写实** | 风格词打架会让模型在两种渲染之间摇摆，边缘糊成一团 |

> **「禁止 360° 大旋转」与 3.9 的子弹时间环绕不冲突**：被禁的是**动作进行中**的长时环绕
> （人物在动、镜头也在绕，两个运动向量叠加必崩）；子弹时间的 360 orbit 只允许用在
> **动作已被冻结**的那一瞬间（兵器相交、终结击命中），此时人物近乎静止，环绕才是安全的。
>
> **第二个允许口：非接触的单人镜**——亮相、收势、独自持械转身这类镜头，主体**半径两步内没有第二个人、
> 没有墙体桌椅遮挡**时可以环绕。此时画面里只剩镜头一个运动向量，且主体背面始终有连续空间可参考，
> 模型不必凭空补人物背面。**两人以上同框、或有任何肢体接触的镜头，一律不许环绕**：AI 要同时推算
> 两具身体的相对位置和自身的圆周轨迹，接触点会拉丝、四肢会互相吸附。

> **单镜 1.5–2.5 秒 vs 每段 2–4 秒**：前者是**逐镜生成**时的镜头时长（快切节奏）；
> 后者是**一次调用**交给模型的片段长度。一个 4 秒片段里可以含两个 2 秒镜头，但只能有一个动作单元。

**动作场景工作流：**

```text
【动作资产创作流】
姿态参考帧 (Pose Reference / controlnet_pose)
        +  物理力学反馈提示词 (重心沉降/碎石飞溅/碰撞闪烁/能动气浪)
        ↓
AI 视频动作层生成（单镜 1.5–2.5s）
        ↓ 导出动作短片（无声）
动作镜头剪辑拆分（正反打蒙太奇："出招镜" + "受击镜"）
        ↓
特效音效混合层（兵器撞击/重击/尘土爆裂）
```

### 3.2 打击感五件套（必写，五类缺一不可）

> **打击感 ≠ 光效。** 加再多剑气火花，只要缺了蓄力或受击反馈，画面依然「软」。
> **约束单位是一次打击（跨出招—受击—环境三镜链），不是一镜。** 五类必须在同一次打击里全部出现，但不得挤进同一镜。
> 缺任何一类，力量感都会塌掉。

| # | 反馈类型 | 必写元素 | 中文提示词 | English |
|---|---|---|---|---|
| 1 | **蓄力势能** | 重心下压、肌肉紧绷、关节蓄力、身体扭转 | `重心下压，膝盖微屈，肩背肌肉绷紧，腰胯反向拧转蓄力，衣摆被带向后方` | `body weight shifts downward, shoulders tense, coiling torso rotation, clothes blowing backward due to energy buildup` |
| 2 | **接触冲击** | 环形冲击波、火花、冲击帧、画面短震 | `命中瞬间迸发环形冲击波与橙色火花，插入一帧白闪，画面短促震动` | `circular shockwave burst, intense sparks ejecting, 1-frame white impact flash, sudden screen jolt` |
| 3 | **受击反馈** | 头部猛甩、身体弓形后弹、手臂上扬、步伐擦地 | `头部随冲击猛甩向一侧，身体呈弓形向后弹出，双臂因惯性上扬，双脚在地面擦出划痕` | `head snapping violently to the side, body arcing backward, arms flailing up from inertia, feet skidding and leaving deep tracks` |
| 4 | **环境破坏** | 碎石飞溅、尘土炸开、地面裂纹、断木横飞 | `脚下碎石飞溅，尘土炸开，落点地面裂开蛛网状纹路，身后木箱碎裂横飞` | `debris kicked up, dust exploding outward, spiderweb cracks spreading from the impact point, splintered wood flying` |
| 5 | **镜头反馈** | 撞击瞬间镜头剧烈震动、1 帧白闪冲击帧、速度线爆发；慢动作**按回合分配**，只给终结击 | 中间回合 `撞击瞬间镜头剧烈震动，插入 1 帧强曝光白闪，背景拉出放射状速度线`；终结击追加 `命中瞬间降速至 0.25 倍，持续 0.5 秒` | 中间回合 `violent camera shake synchronized with the blow, 1-frame white impact flash, radial speed lines flashing in background`；终结击追加 `brief 0.25x slow-motion held for 0.5s` |

> **⑤ 为什么必须按回合分配：** 五件套里只有 ⑤ 是**分回合取值**的。中间回合每一拳都降速，观众看到的是一串"绵软的慢放"，单拳的力量被平均掉（负面词 `slow motion with no force`），终结击也就没有落差可用。
> 所以中间回合的镜头反馈只留**震动 + 冲击帧 + 速度线**三样，`0.25x / 0.5s` 只写进终结击那一镜的提示词，规则见 [3.7](#37-慢动作与冲击帧使用规则)。

**与 §四点五「运动幅度 ≤ 4」怎么共存？** 约束单位是**一次打击**、不是一镜——五类必须写到，但不必也不许挤进同一镜。
正确做法是把五类摊到 3.4 的出招-受击-环境三镜链上，每镜只承担一到两类：

```text
出招镜  → ① 蓄力势能（低幅度，安全）
受击镜  → ② 接触冲击 + ③ 受击反馈（近景，只拍上半身与头部）
环境镜  → ④ 环境破坏（远景，人物细节度低，随便崩）
全程叠加 → ⑤ 镜头反馈（后期加，零生成风险）
```

⑤ 镜头反馈里的**画面短震、冲击帧、速度线优先放到后期做**——让模型生成这些等于白白提高崩坏率，
剪辑软件里加一帧白闪和一次抖动只要三十秒，而且效果更准。

#### 三阶段展开（五件套的时间顺序）

1. **重心沉降（蓄力）**：出招前身体重心下移、膝盖微屈、地面因踩踏受力而开裂或扬尘。
2. **动能传递（出招）**：发力部位肌肉隆起、衣服因快速挥动产生贴体褶皱、武器带起气流气浪。
3. **受力反馈（击中）**：**力量感的灵魂**。不要写「打倒对方」，要写「重拳命中脸颊瞬间面部肌肉剧烈震颤、汗水与血沫飞溅、身体呈弧线被击退数米、双脚在地面擦出深深的划痕与尘土」。

#### 物理力学反馈提示词表

| 动作阶段 | 物理微动作描述（Positive Prompts） | 叙事/视觉目的 |
| :--- | :--- | :--- |
| **蓄力 (Anticipation)** | `shoulders tense, body weight shifts downward, feet stomping the ground creating minor cracks and swirling dust, clothes blowing backward due to energy buildup` | 表现招式爆发前的压迫感，积蓄张力。 |
| **武器挥砍 (Slash/Swing)** | `blade cutting through air, glowing kinetic wind trail, shockwave warping the air (refraction effect), speed lines flashing in background` | 表现冷兵器的锋利与速度，使武器轨迹可见。 |
| **拳脚命中 (Impact)** | `fist connecting with jaw, impact frame flashing white for 1 frame, sweat and water droplets flying off, facial muscles compression` | 突出"拳拳到肉"的物理重量，增加瞬间冲击力。 |
| **受击反弹 (Reaction)** | `character knocked backward, sliding on dirt leaving deep tracks, background blur, dust exploding behind upon wall impact` | 用被击退者的狼狈程度来反衬出招者的力量。 |
| **气浪与环境反馈** | `kinetic air blast dispersing nearby grass and pebbles, dynamic smoke trails curling around limbs, volumetric dust rising` | 利用环境（碎石、风沙、落叶）的形变作为力量的扩音器。 |

### 3.3 反滑步 / 物理阻尼词库

> 不写"他跑"，而是描述物理受力过程，让大模型的三维物理模拟器正确工作。

#### 反滑步对照表

| ❌ 滑步写法（触发 AI 瑕疵） | ✅ 物理阻尼写法（正确） |
|----------------------------|----------------------|
| 他向前跑 | 重心快速前倾，双腿交替蹬地，鞋底与地面每步产生碎石飞溅 |
| 她转身离开 | 重心先向转向侧偏移，肩膀带动躯干旋转，裙摆因惯性延迟0.5秒跟随 |
| 他被击飞 | 冲击力从胸口传导，身体向后弓形弹出，四肢因惯性滞后甩动 |
| 她跳起来 | 膝盖深蹲蓄力，重心猛然上移，头发因反向惯性短暂下压后飘起 |

#### 重心与力学（Weight & Momentum）

| 物理动作 | 英文提示词 | 适用场景 |
|----------|-----------|---------|
| 重心快速转移 | `Rapid weight transfer from back foot to front` | 起跑/出拳/突然加速 |
| 重心偏移 | `Center of gravity shifting laterally` | 转弯/闪避/失去平衡 |
| 惯性延续 | `Momentum carry-through with residual body sway` | 急停/被击退后的惯性晃动 |
| 蓄力释放 | `Coiling tension release from legs through torso` | 跳跃/挥剑/投掷 |
| 失重飘浮 | `Zero-gravity drift with limbs trailing behind` | 太空/水下/仙侠飞行 |

#### 流体与材质互动（Fluid & Material）

| 物理效果 | 英文提示词 | 适用场景 |
|----------|-----------|---------|
| 泥水飞溅流体力学 | `Splashing fluid dynamics, water droplets arcing with realistic trajectory` | 雨天奔跑/泥地打斗 |
| 织物风阻 | `Realistic fabric wind resistance, heavy coat dragging against movement` | 风衣/斗篷/旗帜 |
| 头发惯性甩动 | `Hair whip with inertia delay, strands following head rotation 0.3s late` | 转身/被击/突然回头 |
| 液体泼溅物理 | `Liquid splash with viscosity-appropriate spread pattern` | 血液/酒水/雨水 |
| 烟尘扰流 | `Turbulent smoke displaced by rapid body movement` | 穿越烟雾/爆炸后奔跑 |

#### 环境互动（掩盖 AI 瑕疵的利器）

> **核心技巧：** 当角色与地面/环境持续互动时，大模型会被迫计算接触面物理，从而大幅减少"悬浮滑步"。

| 互动效果 | 英文提示词 | 适用场景 |
|----------|-----------|---------|
| 踩踏碎石飞溅 | `Debris kicked up with each footstep, gravel scattering` | 追逐/奔跑/战斗 |
| 水坑踩踏 | `Puddle splash on each footstep, water ripples spreading` | 雨天场景/湿地 |
| 雪地压痕 | `Snow compression under weight, leaving deep footprints` | 雪地行走/追踪 |
| 沙尘卷起 | `Sand clouds rising with each stride, wind carrying particles` | 沙漠/战场 |
| 草地压弯 | `Grass blades bending and springing back under footsteps` | 田野/草原/花海 |
| 地面震动 | `Ground tremor rippling outward from impact point` | 巨物着陆/爆炸/重击 |

#### 运动强度修饰词（每个动作都必须带）

| 等级 | 中文修饰词 | English Modifiers | 适用场景 |
|------|-----------|------------------|---------|
| ⚡ 极强 | 猛烈、暴烈、爆裂、猛冲 | violent, explosive, slamming, bursting | 爆炸/撞击/格斗 |
| 🔥 强烈 | 剧烈、迅猛、急速、用力 | dramatic, vigorous, rapid, forceful | 追逐/运动/情绪高潮 |
| ⚡ 突然 | 突然、骤然、猛然、戛然 | sudden, abrupt, snapping, jolting | 惊吓/转变/闪回 |
| 🌊 中等 | 稳步、从容、自然、轻快 | steady, confident, natural, brisk | 叙事推进/日常动作 |
| 🍃 轻柔 | 缓缓、温柔、轻柔、丝滑 | gentle, soft, smooth, delicate | 浪漫/舒缓/ASMR |
| 🪨 渐进 | 渐渐、逐步、缓慢、不知不觉 | gradual, slowly, imperceptibly, easing | 日出/情绪渐变/暗场 |

> **避免矛盾组合**——`缓慢爆裂` / `gentle slamming` 这类自相矛盾的描述会让模型困惑。

### 3.4 "出招-受击"三镜拆分法（Montage Edit）

> 不要强求 AI 在同一个镜头中生出"A 打中 B 且 B 倒地"。拆成三个镜头，后期蒙太奇拼接。

| 镜号 | 名称 | 景别/时长 | 画面内容 | 生成难度 |
|---|---|---|---|---|
| **1** | 出招镜 | 中景/特写，2s | A 重心下沉，一记重拳朝摄影机方向猛烈轰出，带起一阵强风气浪，画面在出拳瞬间极速向前 Whip Zoom | **低**——只有单人出招动作，完全不会穿模 |
| **2** | 受击镜 | 近景/特写，1.5s | B 侧脸受重击，脸部发生物理压缩受力形变，头猛地向一侧偏转，水珠飞溅 | **低**——可通过 LivePortrait 或受击关键帧插值快速生成 |
| **3** | 环境负反馈镜 | 远景/全景，2s | B 身体成弧线向后倒飞，砸在地上向前滑行，地上擦起一片尘土，背景的货架或碎石崩落 | **中等**——远景人物细节度低，主要展示"人体抛物线 + 物理碎裂特效"，极易跑通 |

> **效果：** 三镜在时间轴上快速拼接（2s → 1s → 2s），配合**击中瞬间一帧的白屏闪烁（冲击帧）**和**爆裂的撞击音效（SFX）**，视觉冲击力甚至会超越真实动作演员的套路打斗。

### 3.5 五镜动作链（10 秒内拉满视觉节奏）

```text
第一镜(全景)  →  第二镜(中景)  →  第三镜(近景)  →  第四镜(特写)  →  第五镜(POV)
Establishing      Charge            Attack            Impact           Reaction
```

| # | 镜头 | 时长 | 目的 | 画面 |
|---|---|---|---|---|
| 1 | **全景对峙 Establishing Clash** | 2-3s | 展示双方的相对站位、体型差距以及场景氛围 | 大雨滂沱的竹林中，两名剑客斗笠低垂，按剑对视 |
| 2 | **中景前冲 Medium Shot Charge** | 1.5s | 展示爆发速度和前冲身法 | 低角度摄像机前冲，侠客踏地起尘，身后的泥水飞溅 |
| 3 | **近景交锋 Close-up Attack** | 1.5-2s | 展示招式的帅气度与动作线条 | 单人挥刀切入画面，刀锋在空气中拉出一道半月形的白色刀光气浪 |
| 4 | **特写重击 Extreme Close-up Impact** | 1s | 传递极致的力量与物理重量（拳拳到肉） | 拳头或刀靶重重砸在对方脸上，下巴瞬间产生挤压形变，汗水与雨水在强力下飞散 |
| 5 | **第一人称受击 POV Reaction** | 2s | 增强观影的代入感与情绪张力 | 第一人称视线模糊、镜头伴随强震，看向上方缓缓收拳的胜者 |

### 3.6 攻防轮转规则（防"单方面挨打"）

> **回合定义：** 一次完整的「蓄力 → 出招 → 受击 → 环境反馈」为**一个回合**（约 3 镜、4-6 秒）。

| 编号 | 规则 | 检查方式 |
|---|---|---|
| **R1** | **任一方不得连续挨打超过一个回合。** 第二个回合必须出现该方的反击、格挡或闪避——哪怕最终失败 | 数镜表：同一角色连续出现在 2 个以上"受击镜"即违规 |
| **R2** | **优势方逐回合轮换。** 回合 1 若 A 打 B，回合 2 必须是 B 反打 A 或 B 成功格挡 | 回合表的"进攻方"列不得连续同值超过 1 行 |
| **R3** | 每回合结束必须给受击方一个 **0.5-1s 的可读反应镜**（表情/眼神），否则观众无法共情 | 每回合末镜是否有 CU/ECU 表情镜 |
| **R4** | 15 秒段落 = **2 个完整回合 + 1 记终结击**；30 秒段落 = 3-4 个回合 + 终结击 | 时长预算表 |
| **R5** | **只有终结击**允许开启慢动作 + 冲击帧 + 环境负反馈全开 | 见 3.7 |
| **R6** | 连续同向出招不得超过 2 镜（画面单调 + 增加越轴风险），第 3 镜必须换轴侧或换景别 | 见 3.8 |
| **R7** | 每一个打击或蓄力动作，必须伴随尘土、碎石、落叶、雨滴或水墨粒子等**物理负反馈** | 逐镜检查环境反馈词 |

**回合表模板（写打戏前先填）：**

| 回合 | 进攻方 | 防守方 | 防守方结局 | 镜数 | 时长 | 慢动作 |
|---|---|---|---|---|---|---|
| R1 | A | B | 被击退（挨打） | 3 | 0-5s | 否 |
| R2 | B | A | 成功反击/A 格挡 | 3 | 5-10s | 否 |
| 终结 | A | B | 被终结（倒地） | 3 | 10-15s | **是（仅命中 0.5s）** |

### 3.7 慢动作与冲击帧使用规则

| 规则 | 内容 |
|---|---|
| **慢动作只用于最后一击** | 在终结击命中瞬间，视频降速至 **0.25x 播放（持续 0.5s）**，增加招式的分量感 |
| **子弹时间限定场景** | 兵器相碰或致命一击时使用：`bullet time style, extreme slow-motion (slow-mo), 360-degree orbit shot around the frozen clash of blades, sparks suspended in air` |
| **中间回合禁止慢动作** | 中间回合用正常速度 + Whip Zoom + 冲击帧；全程慢动作 = 观感"没有力量"（负面词 `slow motion with no force`） |
| **冲击帧（Impact Frame）** | 在命中黄金帧插 1 帧强曝光/黑白闪：`1-frame flashing impact white screen, sudden momentary black and white flash, extreme dynamic range burst at the moment of contact` |
| **视觉生理原理** | 视网膜接收到约 0.04s（24fps 下 1 帧）的明暗骤变时，视觉皮层产生物理性"碰撞负反馈"，生理层面制造打击力量感 |
| **冲击波滤镜** | 在重撞击帧添加 1-2 帧的画面轻微缩放或色偏，模拟空气冲击波 |

**动作时间戳引导（Timestamp Motion Control）：**

```text
[0:00-0:02] A charges forward aggressively; [0:02-duration] A swings a heavy right hook connecting with B's jaw.
```

> **原理：** 扩散模型在时序帧中按步生成。在提示词中显式带入秒级时段切片，能引导模型在扩散前几步将动作能量强行约束在对应帧区间，从根本上解决动作随机发生、无法卡点的难题。

### 3.8 防越轴硬锚定（180 度轴线）

> **正文见 [blocking-lighting.md](blocking-lighting.md) §2.1–2.4**——180 度轴线原理图（含动作拍摄专用图示）、左右站位锁定语句（动作戏硬锚定 / OTS 安全过渡 / 镜头轴线一致负面词）、防越轴三招（屏幕左右固定锚定 / OTS 定向 / 后期镜像翻转兜底）与允许跳轴的四种情况，全部以那一份为准，本文件不重复。

打戏视角只补一条：横轴（左右）被 §2.1–2.4 锁死之后，一场打戏的空间变化只剩**换轴侧**（§3.6 的 R6：连续同向出招不得超过 2 镜，第 3 镜换轴侧或换景别）和**换高度**（Y 轴高度分层，见 [blocking-lighting.md](blocking-lighting.md) §1.2b）两个出口，两个都不用，两人会被钉死在同一条水平线上原地对抡——观众读不到攻守易位，一场打戏摊平成没有重音的乱动。

### 3.9 动能运镜术语

| 运镜 | 说明 | 提示词 |
|---|---|---|
| **极速推焦 Whip Zoom / Fast Push** | 拳头或武器击中目标瞬间，镜头以极快速度推向撞击点 | `whip zoom into the contact point, high-speed camera motion, sudden camera shake on impact` |
| **手持震颤 Handheld Shake** | 模拟摄影师手持在战场奔跑的纪实感，震颤与受力瞬间同步 | `handheld camera tracking, raw documentary style, dynamic screen shake synchronized with the heavy blow` |
| **低角度仰拍追踪 Low-Angle Tracking** | 摄影机置于极低位置，仰视出招者或前冲的身体，放大威慑力 | `low-angle tracking shot, looking up at the hero charging forward, fast camera movement close to the ground` |
| **希区柯克变焦 Dolly Zoom / Whip Pull** | 出招瞬间镜头拉远，突出招式在大环境中的爆裂范围 | `dolly zoom effect, rapid camera pull back to reveal a shockwave blast dispersing the environment` |
| **子弹时间 Bullet Time** | 兵器相碰或致命一击时时间骤慢，360 度环绕展示凝固细节 | `bullet time style, extreme slow-motion (slow-mo), 360-degree orbit shot around the frozen clash of blades, sparks suspended in air` |
| **侧向平行跟随 Side Tracking** | 展示肢体语言与动作全貌，适合跑步/舞蹈/格斗 | `side tracking shot, parallel to subject movement` |
| **低角度贴地跟随 Low Angle Follow** | 夸大运动动感，制造速度压迫感 | `low angle follow shot, camera near ground level` |

### 3.10 冷兵器与能量光影特效

| 效果 | 写法要点 | 提示词 |
|---|---|---|
| **剑气折射与刀光气浪** | 不要写"发光的蓝色剑气"，要写空气折射气浪 | `refraction trails, kinetic aura wave, heat distortion along the blade path` |
| **金属对撞微粒与火星** | 兵器碰撞时应有反作用力产生的粒子飞溅 | `intense orange sparks ejecting from the steel collision, glowing metal embers suspended in slow-motion, physics-based particle dispersal` |
| **逆光剪影与侧逆边缘光** | 在雨、雾、尘土中勾勒手部和武器边缘 | `strong backlight (contre-jour) creating a dramatic silhouette, sharp rim lighting tracing the armor edges, light rays filtering through the thick dust and splinters` |
| **顶光与硬侧光** | 强调肌肉与金属锐利边缘 | `dramatic top-down lighting mixed with hard side-light, emphasizing character muscles and sharp metallic edges` |
| **体积光/丁达尔** | 烟尘粒子中的光束 | `volumetric light beams (Tyndall effect) filtering through smoke and dust particles` |
| **动作黄金配色** | 青橙色调 | `Teal and Orange color grading, high contrast cinema grading, warm highlights and cool cyan shadows, cinematic blockbuster look` |

#### 意图 → 特效选型决策表（一镜一主叙事特效）

上表是**怎么写**，这张表是**该写哪一个**。两个维度分开收放，别一起松也别一起紧：

- **粒子密度可以拉满**：同一类粒子铺再多都不崩——模型对同源粒子只解一套受力方向，密度只增加渲染量。
- **粒子类别必须择一**：火星 / 灰尘 / 水花 / 碎屑同框，等于让模型同时解算三套重力与风阻，飘散方向互相打架，最后糊成分不出材质的噪点。
- **叙事特效种类 ≤ 1**：冲击波、剑气折射、能量爆闪、血雾这类**改变画面物理读法**的特效，一镜只准一种；
  第二种会和第一种争抢形变场的解算预算，被挤掉的是主体人物——**先崩的一定是脸和手**，特效本身反而渲染得很漂亮。
- 光影与调色（顶光、硬侧光、体积光、青橙配色）**不计入这个配额**，它们不产生形变场，可以照常叠加。

| 叙事意图（这镜要观众感到什么） | 唯一主叙事特效 | 粒子类（择一，密度可拉满） | 同镜禁止叠加 |
|---|---|---|---|
| 终结、绝杀、这一下打完了 | 冲击波气浪（环形扩散 + 空气折射） | 尘土 | 剑气折射、能量爆闪 |
| 兵器锋利、硬碰硬的金属感 | 金属对撞火星 | 火星 | 体积光雾、水花、血雾 |
| 招式轨迹要看得清 | 剑气折射 / 刀光气浪残影 | **不加粒子**（留空气干净衬托轨迹） | 火星、碎屑 |
| 危险逼近、压迫、看不清对手 | 逆光剪影 + 边缘轮廓光 | 浮尘 | 冲击波、能量爆闪 |
| 超自然、异能、非人力量 | 能量爆闪 | 碎屑 | 火星、冲击波 |
| 环境恶劣、身处险地 | 体积光丁达尔 | 雨丝或水花 | 火星、能量爆闪 |
| 挨打的代价、惨烈 | 汗水血沫放射状飞散 | 水花 | 尘土、火星 |

写法上要**显式排他**，只点名一类还不够，模型会自动补齐它认为「该有」的其他粒子：

```text
dense orange sparks only, no dust, no debris, no water splash,
single dominant effect: metal collision sparks, no shockwave, no energy burst
```

> 选型自查：**遮住主体只看特效，说不出这镜在讲什么，就是特效在自说自话**——换一个意图对得上的，别再加一个。

### 3.11 15 秒攻防打戏完整模板

#### 3.11.1 段落总谱（先填这张表，再写提示词）

| 镜号 | 时间 | 回合 | 角色 | 景别/机位 | 动作（含受力过程） | 环境负反馈 | 慢动作 | 音效卡点 |
|---|---|---|---|---|---|---|---|---|
| S1 | 0-3s | 建立 | A 左 / B 右 | 全景，低角度平视 | 双方按兵器对视，重心微沉 | 雨幕/尘埃浮动 | 否 | 环境音 + 风声 |
| S2 | 3-4.5s | R1 出招 | A | 中景，低角度前冲跟拍 | A 重心下沉→蹬地前冲→右直拳轰向镜头 | 踏地起尘、泥水飞溅 | 否 | 破风声先于画面 3 帧 |
| S3 | 4.5-5.5s | R1 受击 | B | 近景特写 | B 侧脸受击，面部肌肉压缩形变，头猛偏 | 汗水血沫飞溅 | 否 | 钝击骨裂（形变第一帧） |
| S4 | 5.5-7s | R1 反馈 | B | 远景 | B 弧线后飞，落地前滑，双脚擦出划痕 | 尘土爆起、货架崩落 | 否 | 重体落地 + 沙石碎裂 |
| S5 | 7-9s | R2 反击 | B | 中近景，侧向平行跟拍 | B 单手撑地起身→重心前移→反手横扫 | 地面碎石被扫飞 | 否 | 破空声 |
| S6 | 9-10.5s | R2 格挡 | A | 近景 OTS | A 抬臂格挡，前臂受力下沉半寸，双脚后滑 | 脚下擦出两道浅痕 | 否 | 金属/骨肉闷响 |
| S7 | 10.5-12s | 终结蓄力 | A | 特写 | A 咬紧牙关颌线绷紧，重心猛沉，膝盖微屈 | 地面开裂、扬尘、衣摆后扬 | 否 | 低频蓄音 |
| S8 | 12-13.5s | **终结击** | A→B | 极致特写 | 拳头命中下颌，下巴挤压形变，汗水飞散 | 冲击波气浪 | **是 0.25x / 0.5s + 1 帧白闪** | 重击 + 混响拖尾 |
| S9 | 13.5-15s | 收束 | B / A | POV 受击 → 全景 | B 第一人称视线模糊、镜头强震，看向上方缓缓收拳的 A | 尘埃缓慢落定 | 否 | 耳鸣高频 + 环境音回落 |

#### 3.11.2 15 秒攻防提示词模板（可直接粘贴，逐项替换方括号）

```text
15秒[题材]打戏段落，[画面类型+渲染风格+色调]，多镜头视频(multishot video)，
风格锚定：真实电影质感，实拍写真，photorealistic live-action cinematic film still, real human skin texture, natural lighting；绝非动画、绝非卡通、绝非3D渲染、绝非插画、绝非草图。

【空间锚定】
[角色A锚定块]位于画面左侧，面向右侧出招；[角色B锚定块]位于画面右侧，面向左侧防守。全段保持该左右关系，不跳轴。
场景：[场景圣经——地面材质/天气/光源方向/色温]。

【时间轴】
[0:00-0:03] 建立对峙：全景低角度，两人[持械/空手]对视，双方重心微沉，肩部绷紧；[环境粒子——雨幕/尘埃/落叶]在光束中浮动。镜头缓慢推进。
[0:03-0:04.5] 回合一·A出招：中景低角度贴地跟拍，A重心快速前倾(rapid weight transfer from back foot to front)，双腿交替蹬地，脚下踏地起尘、泥水飞溅(puddle splash on each footstep)，右[拳/刀]朝镜头方向猛烈轰出，衣物因快速挥动产生贴体褶皱，带起强风气浪；出招瞬间镜头极速向前 whip zoom。
[0:04.5-0:05.5] 回合一·B受击：近景特写，B侧脸受重击，面部肌肉在力下剧烈压缩形变(facial muscles compression)，头猛地向一侧偏转，汗水与[雨水/血沫]飞溅；命中帧插入1帧白屏闪烁(1-frame flashing impact white screen)，画面剧烈震动。
[0:05.5-0:07] 回合一·环境反馈：远景，B身体呈弧线向后弹出，四肢因惯性滞后甩动，落地后向前滑行，双脚在地面擦出深深的划痕与尘土(sliding on dirt leaving deep tracks)，背景[货架/碎石/木箱]被撞得崩落。
[0:07-0:09] 回合二·B反击：中近景侧向平行跟拍，B单手撑地，手臂微颤地撑起身体，重心前移，反手横扫；地面碎石被扫飞，烟尘因躯体快速移动产生扰流。B的目光涣散了一瞬又咬牙聚焦回来。
[0:09-0:10.5] 回合二·A格挡：过肩近景，从B右肩后方拍摄，焦点在A身上；A抬臂格挡，前臂受力瞬间下沉，重心被迫后移，双脚在地面后滑并擦出两道浅痕；A眉头压低，下颌绷紧。
[0:10.5-0:12] 终结蓄力：特写，A咬紧牙关颌线绷紧，鼻翼扩张深深吸气，肩部绷紧、身体重心明显下沉，双脚踩踏地面造成细小龟裂与扬尘(feet stomping the ground creating minor cracks and swirling dust)，衣摆因蓄力气流向后扬起。
[0:12-0:13.5] 终结击（唯一慢动作）：极致特写，[拳/刀]重重命中B的下颌，下巴瞬间产生挤压形变，汗水与水珠在强力下呈放射状飞散；此处降速至0.25倍慢放持续0.5秒，命中帧插入1帧强曝光白闪与画面轻微缩放色偏，模拟空气冲击波；环绕气浪将周围[碎石/落叶/水花]向外掀开。
[0:13.5-0:15] 收束：第一人称受击视角，B的视线模糊、镜头伴随强烈震动，仰视上方缓缓收拳的A；随后切全景，尘埃缓缓落定，A背对镜头站立，边缘轮廓光勾出身形。

【全局补充】
物理：每一次出招与受击都必须带环境负反馈（尘土/碎石/水花/衣物惯性/头发0.3秒延迟甩动）。
表演：受击方每回合末必须有0.5-1秒的可读表情反应；任一方连续挨打不得超过一个回合。
光影：[主光方向+色温]（光源层），[体积光/边缘轮廓光/逆光剪影]（光行为层），[青橙色调/低饱和灰绿]（色调层）。全段光源方向固定，运镜不改变光源方向或色调基准。
音效：破风声先于画面命中3帧；钝击音对齐面部形变第一帧；金属格挡保留0.5秒高频余音；落地音混合沙石碎裂。仅生成动作与环境音效，不要背景音乐。
一致性：保持同一张脸、同一发型、同一服装、同一兵器归属；角色A始终在画面左侧，角色B始终在画面右侧。
禁止：任何文字、字幕、LOGO或水印；跳轴、瞬移、变脸、道具换手、肢体穿模、悬浮滑步、无受力的假打。
```

#### 3.11.3 五种题材的正/负向提示词（可直接粘贴）

**模板一：古风硬核武侠——刀剑碰撞与水墨残影**（竹林/古建筑楼顶，重力量、重写意）

```text
【正向提示词】
Cinematic action scene, low-angle tracking shot. Two martial artists in bamboo hats and black ancient robes clashing swords.
The heavy steel blades strike together, generating intense sparks flying outward. Kinetic shockwave warps the air around them.
One warrior slides backward on the wet ground, feet kicking up dirt and rain splashes. Volumetric fog in background.
Extreme slow-motion during impact, camera whip pan tracking the trajectory of the sword.
Epic lighting, octane render, Unreal Engine 5 render, cinematic 3D render quality, high-fidelity CGI.

【负向提示词】
(避免：照片、真实名人、证件照、写真、passport photo, headshot, photorealistic, real human skin pores, camera snapshot, deformed limbs, floating bodies, clean ground, static air)
```

**模板二：现代硬核近战——拳拳到肉与力学形变**（地下拳馆/雨夜街头，重挫败感）

```text
【正向提示词】
Gritty action movie style, handheld camera. Close-up shot of a powerful fist connecting with the opponent's jaw.
Slow-motion capture of the impact: sweat and water droplets flying off in a spray, facial muscles compressed under the force.
The screen shakes violently upon connection. The opponent stumbles backward, crashing into wood crates, debris and dust exploding into the air.
Rembrandt lighting, high contrast, deep shadows, cinematic 3D render, high-fidelity CGI.

【负向提示词】
(避免：照片、真实名人、写真、photorealistic, headshot, real human skin pores, camera snapshot, extra fingers, deformed face, floating action, no-impact fight, slow motion with no force)
```

**模板三：科幻/玄幻动作——能动气浪与粒子碰撞**（废土/赛博街头，重特效冲击）

```text
【正向提示词】
Sci-fi combat action, dolly zoom shot. A warrior in sleek exoskeleton armor executing a ground-slam attack.
A massive circular energy shockwave blast expands outward, warping the space and air (refraction effect).
Pebbles, dirt, and concrete debris are thrown into the air, suspended in high-speed camera slow-motion.
Neon lights reflection on wet ground, volumetric smoke trails curling around armor, Unreal Engine 5 render, cinematic 3D render.

【负向提示词】
(避免：照片、真实名人、写真、photorealistic, headshot, real human skin pores, camera snapshot, low-resolution dust, static environment, no-impact slam)
```

**模板四：近身缠斗快打——节奏与密度**（走廊/电梯/狭窄室内，重压迫感）

```text
【正向提示词】
近身缠斗快打，双人近距离交锋，手脚快速交替攻防，动作密集紧凑，身法灵活多变，姿态瞬息切换，
角色A在画面左侧面向右，角色B在画面右侧面向左，两人相距一步之内，
每次格挡带起衣料摩擦与手臂碰撞的形变，狭窄走廊，前景有虚化的墙体遮挡，
手持轻微抖动运镜，强烈明暗对比，高燃打斗氛围，
画面稳定流畅，无闪烁跳帧，无五官变形，无肢体畸形，人物不换脸，光影统一，24fps。

【负向提示词】
(避免：merged bodies, intersecting limbs, tangled limbs, fused characters, floating action,
no-impact fight, deformed limbs, axis flip, photorealistic headshot, camera snapshot)
```

> 缠斗是**穿模率最高**的场景（两具身体持续重叠）。写这条时务必配合 3.4 三镜拆分，
> 不要让模型在一镜里生完整个缠斗回合；`merged bodies / intersecting limbs` 必须挂在负向词里。

**模板五：落地重击终结——破坏力与慢动作**（旷野/屋顶/废墟，重终结感）

```text
【正向提示词】
落地震地重击，人物从空中极速坠落，重拳重脚砸向地面，
落地瞬间地面碎石飞溅、蛛网状纹路开裂向四周扩散，尘土呈环形炸开，
冲击力炸裂，画面震撼高燃，慢动作镜头，低角度仰拍，史诗级光影，
画面稳定流畅，无闪烁跳帧，无五官变形，无肢体畸形，人物不换脸，光影统一，24fps。

【负向提示词】
(避免：clean ground, static air, no-impact slam, low-resolution dust, floating bodies,
deformed limbs, slow motion with no force)
```

> 落地重击是全场**唯一**推荐一镜开满五件套的镜头：它自成一次打击，出招—受击—环境全压在同一次落地上，没有可分摊的三镜链。
> 按 3.7，慢动作只给命中后的 0.5 秒。

#### 3.11.4 单镜动作提示词（1.5–2.5s，用于逐镜生成）

```text
镜头[shot_id]，[景别]，[机位角度]，[焦段]。
角色[名]位于画面[左/右]侧，面向[方向]。
动作因果链：[准备（重心/膝盖/肩部）] → [发力（哪个部位、什么方向、什么强度修饰词）] → [接触（形变/飞溅/1帧白闪）] → [反应（惯性/后滑/擦痕）] → [恢复]。
环境负反馈：[尘土/碎石/水花/落叶] + [衣物惯性] + [头发0.3秒延迟甩动]。
运镜：[whip zoom / handheld shake / low-angle tracking]，与受力瞬间同步。
光影：[主光方向+色温]，[边缘轮廓光/体积光]。
音效：[破风/钝击/金属/落地]，对齐[形变第一帧/火花迸发瞬间]。
保持：同一张脸、同一服装、同一兵器在同一只手；不跳轴。
禁止：任何文字、字幕、LOGO或水印；肢体穿模、悬浮滑步、无受力的假打。
```

#### 3.11.5 打斗提示词万能公式（五块拼装）

写任何一条打戏提示词时，按这五块顺序拼，缺块就是力量感缺口：

```text
① 动作与反馈 = 蓄力（重心/肌肉/关节）+ 出招（轨迹/气浪/残影）+ 反馈（形变/飞溅/后弹/擦地）
② 镜头运镜   = 景别 + 角度（低机位仰拍增压迫）+ 运镜（急推变焦/手持晃动/升格慢放）
③ 光影氛围   = 主光方向色温 + 明暗对比 + 环境破坏粒子（碎石/尘土/火花/水花）
④ 音效提示   = 金属撞击 / 钝击闷响 / 破空声 / 地面碎裂声（写进提示词帮模型定节奏）
⑤ 防崩后缀   = 见下方固定串
```

**防崩坏后缀（打戏专用，每条必挂）**——权威定义见 [3.13](#313-动作戏负面词与网关清洗)，此处是副本，两处对不上时以 3.13 为准：

```text
画面稳定流畅，无闪烁跳帧，无五官变形，无肢体畸形，人物不换脸，光影统一，24fps
```

> 后缀里的 `24fps` 是**交付帧率常量**，任何镜头都不许改写或删除；升格镜的 `60fps` 只能写在正文的①②块里，
> 且必须带 `for slow-motion, delivered at 24fps`（口径见 §四点五「帧率单一口径」）。

> ④ 音效提示写进提示词的作用不是让模型「发声」，而是**帮它定位动作节拍**——
> 写了「金属撞击声」，模型更容易把兵器相交安排在明确的一帧上，而不是糊成连续运动。

### 3.12 动作音效与 Foley 卡点表

> 动作戏"三分看画，七分听声"。无声或不对位的打戏像"纸片人比划"。

| 动作类型 | 推荐 SFX/Foley 音效描述 | 对齐控制（对齐画面的哪一帧） | 混音建议 |
| :--- | :--- | :--- | :--- |
| **重拳/重腿命中** | `Heavy blunt punch impact, organic low-frequency thud, bone cracking sound effect` | 重拳击中面部形变的**第一帧** | 适当切掉中高频，增强低音（Bass），产生钝击骨裂的物理分量感 |
| **金属兵器格挡** | `High-pitched metallic sword clash, ringing steel resonance, weapon parry` | 兵器相交迸发出橙色火花的那**一瞬间** | 音频留置 0.5s 的高频余音颤鸣（Ringing tail），表现兵器对震 |
| **空手挥舞/武器破风** | `Fast whoosh sweep, air tearing sound, blade swinging through air` | 动作开始加速前冲、刀光气浪浮现的**前 3 帧** | 声音先于画面命中发生，为撞击进行听觉蓄力 |
| **受击飞出坠地** | `Heavy body fall, gravel debris rustling, dust explosion impact sound` | 身体后背或脚底接触地面、爆起尘土的**那一帧** | 混合沙石碎裂声与身体重击声，按场景材质（木板/泥地）调整 |

**材质拟声精细化（Material Foley）：**

| ✗ 笼统写法 | ✓ 精细化写法 | 英文提示词 |
|------------|------------|------------|
| 走路声 | 重靴踩在干雪上的嘎吱声 | `Crunching heavy boots on dry compacted snow` |
| 走路声 | 高跟鞋踩在湿滑大理石上的清脆哒哒 | `Sharp heels clicking on wet marble floor` |
| 走路声 | 赤脚踩在浅水洼中的啪嗒飞溅 | `Bare feet splashing through shallow puddle` |
| 撞击声 | 次声波级的沉重撞击，伴碎片飞溅 | `Heavy sub-bass impact with debris scatter and rattle` |
| 门声 | 锈铁门磨混凝土地面的刺耳刮擦 | `Rusty metal door grinding on concrete floor` |
| 衣物声 | 烈风中皮革风衣猎猎拍打 | `Leather coat flapping violently in gale-force wind` |
| 液体声 | 浓稠血液滴落在金属地板上的沉闷啪嗒 | `Viscous liquid dripping onto metal surface, thick splat` |

**动作音效分类词库：**

| 动作类型 | 音效描述 |
|----------|----------|
| 脚步 | 高跟鞋清脆哒哒声 / 军靴沉重踏地 / 赤脚在水中溅水 |
| 打斗 | 拳头击中肉体的沉闷声 / 刀刃出鞘的锋利声 / 骨骼碎裂 |
| 爆炸 | 低频轰隆+冲击波气浪+碎片坠落 |
| 金属 | 铁链拖拽+齿轮咬合+金属碰撞铿锵 |
| 风 | 呼啸穿过峡谷 / 微风拂过耳边 / 风暴级狂风呼号 |
| 魔法/科幻 | 能量充能嗡鸣 / 传送门嘶嘶声 / 光剑振动低频 |

> **音效排他原则（纯动作镜）：** 必须强调 `仅生成[真实脚步声/喘息声/风动声]，绝对不要配任何背景音乐和台词。`

### 3.13 动作戏负面词与网关清洗

**肢体/动作负面词：**

```text
deformed limbs, floating bodies, clean ground, static air, floating action, no-impact fight,
slow motion with no force, extra fingers, deformed face, low-resolution dust, static environment,
merged bodies, overlapping bodies, intersecting limbs, tangled limbs, fused characters
```

**中文负面约束：**

```text
不要肢体穿模，不要悬浮滑步，不要假打无力，不要地面干净无尘，不要空气静止，不要跳轴，不要瞬移，不要道具换手
```

**打戏防崩坏后缀（正向串，每条打戏提示词结尾必挂）：**

```text
画面稳定流畅，无闪烁跳帧，无五官变形，无肢体畸形，人物不换脸，光影统一，24fps
```

> **本串就是全片收尾三串里的第三串，权威定义在此。** 适用面**仅打戏镜**：画质锚点串（全片每一镜）与一致性串（第 2 镜起）
> 照常挂，本串叠在这两串之后，三串语义不重叠、可同时挂。三串的归口表以及「为什么不能有第四串」的机理见
> [shot-grammar.md](shot-grammar.md)〈收尾串归口〉，本节不复述。
>
> **打戏新增的稳定性约束一律并进本串**，不要另起一条打戏专用的第四串。多一串就把尾部权重再往后拽一截，
> 而打戏提示词里被压低的恰恰是排在最前的①动作与反馈块——受力过程被稀释成「假打无力」（`no-impact fight`）：
> 画面确实稳了，拳头却不落在人身上。本串已含「无闪烁跳帧」与「光影统一」，同义项不要再挂第二遍。

**第三方网关安全清洗（Sanitizer）：**

- **痛点**：第三方网关的内容审核极度敏感，把用于防"疑似真人"的敏感身份词（`passport photo` / `headshot` / `not a real person`）或激烈冲突词（`杀`/`死`/`暴力`/`重拳打脸`/`羞辱`）直接投递会被判违规返回 400。
- **自愈方案**：发送前经过**动作词清洗器**，正则替换成对的中英文括号，剔除暴力、血腥及身份敏感词（如将"重拳砸烂脸颊"清洗为"双手与手臂的快速物理碰撞"），保留正向的写实电影画风与分镜。

**Seedance 2.0 传参合规（防 400）：**

1. `resolution` / `duration` / `ratio` / `watermark` 必须在请求体**顶层字段**，不得在 text 里写 `--flags`
2. content 的文本对象**必须**携带 `style_caption` 字段，否则报 `InvalidParameter.BodyFormat`
3. `style_caption` 推荐值：`真实电影质感，实拍写真，photorealistic live-action cinematic film still, real human skin texture, natural lighting; 绝非动画、绝非卡通、绝非3D渲染、绝非插画、绝非草图 (not anime, not cartoon, not 3d render, not cgi, not illustration, not sketch)`

### 3.14 动作戏 Checklist

```text
- [ ] 分镜拆分率 > 80%：动作戏绝不使用超过 3 秒的长镜头，全片采用快切节奏
- [ ] 每段只做 1 个动作单元，没有单段 8–12 秒的完整连招
- [ ] 打击感五件套齐全：蓄力势能 / 接触冲击 / 受击反馈 / 环境破坏 / 镜头反馈——按"一次打击"跨三镜链核对，不是按单镜核对
- [ ] 没有任何一镜同时扛满五类（落地重击终结镜除外）
- [ ] 攻防轮转：任一方连续挨打不超过一个回合，回合表的"进攻方"列无连续同值
- [ ] 每回合末给受击方 0.5-1s 的可读反应镜
- [ ] 防越轴检测：相邻镜头中 A 与 B 的左右屏幕相对位置恒定；越轴镜头后期水平镜像翻转
- [ ] 物理动作带起环境反馈：每个打击/蓄力伴随尘土、碎石、落叶、雨滴或水墨粒子
- [ ] 画面/声轨帧级对齐：兵器撞击与重拳击中的音效对齐画面受力变形第一帧
- [ ] 慢动作只出现在终结击（0.25x，持续 0.5s），中间回合不得慢放
- [ ] 冲击帧：重击命中插 1 帧白闪 + 1-2 帧轻微缩放/色偏
- [ ] 每个动作都带运动强度修饰词，无"缓慢爆裂"式矛盾组合
- [ ] 全段风格词统一，没有水墨 / 赛璐珞 / 写实混搭
- [ ] 每段都挂了形象锁与角色参考图
- [ ] 没有动作进行中的 360° 大旋转镜头（环绕只出现在子弹时间的冻结瞬间，或主体周围空旷的非接触单人镜）
- [ ] 七原则复检：Clarity 与 Geography 成立，Stakes / Motivation 在场次说明里写清了
- [ ] 防真人风控：图生视频首帧图包含 CGI/3D 渲染字样
- [ ] API 合规：请求体含 style_caption；第三方网关前经过 Sanitizer 清洗
```

---

## 四、群演与背景人物的行为约束

### 4.1 三条铁律

| # | 铁律 | 原因 |
|---|------|------|
| 1 | **背景人物只做低幅度循环动作**（走动/交谈/敲键盘/举杯），不做剧情动作 | 多主体复杂互动是首次生成成功率最低的梯队 |
| 2 | **不看镜头、不与主角发生肢体接触、面部不清晰**（浅景深虚化） | 避免 `incorrect eye lines` / `broken interactions` / `crowd collision` / 肢体穿模 |
| 3 | **群演反应必须与主事件一致** | 主角在打斗而背景在悠闲喝茶 = 情绪错位、观众出戏 |

### 4.2 群演分级与约束表

| 层级 | 定义 | 允许的行为 | 面部处理 | 单次同框数量 | 提示词写法 | 崩坏风险 |
|---|---|---|---|---|---|---|
| **L0 背景板** | 纯环境人流，无叙事功能 | 单一循环动作（行走/站立/端盘） | 完全虚化，不可辨识 | 不限（远景） | `背景人流保持自然走动，面部完全虚化在景深之外，不看向镜头` | 低 |
| **L1 有反应群演** | 对主事件有集体反应（惊呼/退让/回头） | 一个统一的集体反应动作 | 中景轮廓可见，不给特写 | ≤ 8 人 | `宾客们同时转头看向门口方向，身体微微后仰退开半步，面部不清晰` | 中 |
| **L2 有动作群演** | 与主角有非接触互动（围堵/举杯/鼓掌） | 允许一个明确动作，不与主角肢体接触 | 侧面/背面为主 | ≤ 4 人 | `四名黑衣人从画面右侧呈半圆围拢，保持与主角一臂以上距离，背对镜头` | 高 |
| **L3 有台词配角** | 有一句以下台词 | 按主角标准处理：锚定块 + 表情 + 口型 | 需要锁定五官锚定块 | ≤ 2 人 | 走 2.2 台词行格式 + 角色锚定块 | 最高 |

> **升级即降配：** 层级每升一级，同框人数必须减半；L2/L3 若必须与主角同框，优先拆成单人镜头正反打。

### 4.3 群演行为约束提示词（可直接粘贴）

**中文：**

```text
背景人物保持低幅度循环动作（[走动/交谈/敲键盘/举杯]），动作幅度控制在小范围，不看向镜头，不与主角发生肢体接触，不遮挡主角面部；面部落在景深之外不清晰；人物之间保持自然间距，不重叠、不粘连；背景人数与站位全场保持不变。
```

**English：**

```text
background extras perform simple looping actions, low amplitude, faces out of focus in shallow depth of field, no eye contact with camera, no physical interaction with the main characters, natural spacing between people, consistent crowd count and placement throughout the scene
```

**集体反应（L1）：**

```text
[人群身份]同时[转头/后退半步/低语]，反应方向统一指向[主事件位置]，动作幅度一致但起始时间略有先后（0.2秒内错开），面部不清晰，不看向镜头。
```

**围堵/对峙（L2）：**

```text
[N]名[身份]从画面[方向]呈[半圆/一字]围拢，与主角保持一臂以上距离，全部背对或侧对镜头；不发生肢体接触；主角始终位于画面[左/右/中]侧，不跳轴。
```

### 4.4 群演负面提示词（多人/群像场景必挂）

```text
duplicate people, cloned faces, repeated extras, copy-paste crowd, identical expressions,
merged bodies, overlapping bodies, intersecting limbs, missing person parts,
floating heads, broken interactions, incorrect eye lines, looking in wrong direction,
awkward spacing, crowd collision, tangled limbs, fused characters, inconsistent scale,
foreground character blur, background character collapse, malformed background people,
random extra hands, random extra faces, ghost people, transparent body, incomplete body
```

**中文负面：**

```text
不要克隆脸，不要复制粘贴人群，不要表情整齐划一，不要肢体重叠粘连，不要漂浮的头，不要视线错位，不要人群碰撞，不要比例不一致，不要背景人物崩坏，不要随机多出的手和脸，不要画面杂乱，不要随机增加物体
```

### 4.5 群像站位法（决定观众一眼读到的权力关系）

> **站位法正文见 [blocking-lighting.md](blocking-lighting.md) §1.1「八种基础站位法（行业通用底座）」**——核心镜头 / 对话切换 / 三角关系 / 空间象征 / 运动固定 / 对称仪式 / 冲突对峙 / 前后中景层次八法的定义与调度建议以那一份为准（可复制提示词模板见同文件速查章第 8 节「八大固定站位法」与附录 §1.2「七大可复制站位公式」，其中群像站位为公式 7）；「群像关系镜头」与「夜色群像镜头」两种群像镜头灵感见 [blocking-lighting.md](blocking-lighting.md) §1.2 公式 7 与 §4.9。本文件不重复。

群演视角只加一条口径：**站位法排的是有名有姓的角色，群演按 §4.2 分级只做层次填充，不占站位法里的位置**——把 L0/L1 群演写进三角关系的顶点或对峙的张力空间，模型会按主体规格去刻画他的五官和动作，既抢走主角的焦点，又直接踩中 §4.4 的克隆脸与串脸风险，这一镜的阵营关系反而读不出来。

### 4.6 防串脸与背景稳定

```text
1. 分别锚定：每个有名有姓的角色独立锚定块，明确空间位置
   "[角色A锚定块] on the left, [角色B锚定块] on the right"
2. 差异化设计：主角间在发色/脸型/服装色上拉开区分度（避免两个角色都是黑长直）
3. 视线/站位绑定：明确谁面向谁，避免错位  "A facing B, B looking down"
4. 优先分镜规避：能单人镜头解决的对话，不强行同框
5. 竖屏（9:16）单人优先：画幅窄，双人同框易拥挤，多用单人正反打
6. 背景要简洁稳定：`保持同一场景，不要更换背景，不要随机增加物体，不要画面杂乱`
```

### 4.7 群演场景模板

```text
[时长]群像场景，[画面类型+渲染风格+色调]，
画面（0-Xs）：[景别]，从[方向]拍摄，[场景圣经]，
[主角锚定块]位于画面[位置]，面部朝向[对象]，视线[情绪修饰]地聚焦于[对象]；
背景[N]名[身份]群演分布在[中景/背景]，保持低幅度循环动作（[动作]），面部落在景深之外不清晰，不看向镜头，不与主角发生肢体接触；
[运镜 + 叙事动机]。
[X-Xs]：[主事件发生]，群演统一做出[集体反应]，反应方向指向[主事件位置]，起始时间在0.2秒内错开。
音效：[人群低语/掌声/脚步] + [主事件音效]。
一致性：全场保持相同的群演人数、站位、服装色系与光源方向。
禁止：任何文字、字幕、LOGO或水印；克隆脸、复制粘贴人群、肢体重叠粘连、群演看向镜头、群演与主角发生接触。
```

### 4.8 群演质检清单

```text
- [ ] 群演或背景人物反应是否与主事件一致？
- [ ] 是否出现克隆脸/复制粘贴人群/表情整齐划一？
- [ ] 群演是否看向镜头、是否与主角发生肢体接触？
- [ ] 群演面部是否落在景深之外（L0/L1/L2 不得清晰可辨）？
- [ ] 跨镜头群演人数、站位、服装色系是否一致？
- [ ] 前景遮挡用的次要角色是否稳定（无 background character collapse）？
- [ ] 同框人数是否符合分级上限（L1≤8 / L2≤4 / L3≤2）？
- [ ] 竖屏画幅下是否优先使用单人正反打而非多人同框？
```
