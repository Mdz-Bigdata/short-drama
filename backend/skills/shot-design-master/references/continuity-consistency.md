# 连续性与一致性锁

多个分镜视频合并后要看不出割裂，靠的不是运气，是**每一镜都显式继承上一镜的状态**。

连续性优先级（冲突时按此取舍）：

```text
角色一致性 > 光影一致性 > 色调一致性 > 背景一致性 > 运动一致性
```

---

## 〇、五条铁律（生图阶段最容易翻车的五处）

六锚点管的是「有没有锁」，这五条管的是「锁得对不对」。分镜图阶段翻车基本都出在这五处。

### 铁律一 · 视线方向必须连续

A 镜角色看向画面**右侧**，B 镜揭示他看到的对象，这个对象必须落在画面**左侧或正前方**。
观众的视线才能从 A「跟过去」到 B；同侧出现会让视线「弹回来」，这就是越轴。

```text
角色面朝画面右侧、视线向右（character faces screen right, looking toward screen right）
→ 下一镜：对象位于画面左前方（the object sits on screen left, revealed by the previous eyeline）
```

两种写法二选一：**指方向**（`视线向右`）或**指落点**（`角色目光投向画面左前方`）。落点写法在多人同框时更稳，因为它同时钉死了「看谁」。

对话戏的正反打写法与英文串见 §附 3.x（视线匹配剪辑 / 正反打连续）。

### 铁律二 · 光影方向必须统一

同场景的连续镜头，光源方向不能变。观众未必说得出哪里不对，但一定觉得「怪」。

**在分镜脚本阶段就把每个场景的光向写死一句**，后续所有该场景的镜头原样复制：

```text
公寓场景：主光源为窗外冷蓝光（从画面右侧），辅光源为落地灯暖黄光（从画面左侧）
```

> 脚本可以复制粘贴，**出图不能**。每张分镜图仍要人眼复核一遍光向——模型会在长句里悄悄翻面。

### 铁律三 · 动作要有「帧间感」（半拍原则）

连续两镜展示同一动作时，后一帧必须是前一帧的自然延续。**B 镜展示的是 A 镜动作完成到五到八成时的状态。**

```text
A 镜：伸手去拿桌上的杯子，手还在半空
B 镜：指尖刚触到杯壁          ← 半拍，流畅
✗ B 镜：已经端起来喝了一口     ← 跳帧
✗ B 镜：手仍在半空只挪了两厘米  ← 拖沓
```

半拍原则是 §二「五步拆法」的**帧级补充**：五步管的是一个动作拆几镜，半拍管的是相邻两镜之间跨多远。

**为什么关键帧必须是「运动中的瞬间」。** 每一镜的起幅姿态必须写成**爆发瞬间 / 接触瞬间 / 动作中段**，不能写成一个已经收住的静止姿态：

```text
✓ 短刀正向上身要害推进中
✓ 脚刚离地腾空起跳
✓ 衣袂横拖出残影
✗ 已经完成劈砍后收刀站定   ← 死姿态
```

**禁止写「已经完成劈砍后收刀」这类死姿态**，失败链条是：起始帧是死姿态 → 模型认为动作尚未开始 → 视频开场先「重新启动」一次（有一段多余的起势）→ 剪进时间线就是节奏断裂。

**口语自检法。** 把上一镜的落幅描述和本镜的起幅描述**连着念出来**：「接得上」就通过，念着别扭就是断了。这条比任何百分比都好执行——不确定 B 镜该落在六成还是八成时，念一遍就有答案。

**两套衔接模型的适用边界。** 本文件里有两套写法，用错地方一样会断：

| 情形 | 用哪套 | 具体要求 |
|---|---|---|
| 同一个动作的**连续两镜** | **半拍原则**（本条） | B 镜是 A 镜完成五到八成的状态，**允许动作重叠** |
| **跨镜硬切**与**首尾帧模式** | **落幅 == 起幅**（见 §五） | **严格同帧对齐**，落幅描述原样抄进下一镜起幅，不留重叠 |

打戏的出招镜 → 受击镜属前者（同一次挥砍被拆成两镜，必须重叠）；段落之间的切换属后者（一个回合收束、下一个回合起手，必须严丝合缝）。

### 铁律四 · 景别变化要有节奏

景别的编排本质就是节奏的编排。连续三个近景观众会闷，连续三个远景观众会走神。

```text
远景（交代环境）→ 中景（展示动作）→ 近景/特写（强调情绪）   推入：宏观到微观，天然带紧张感
特写 → 近景 → 远景                                    抽离：适合收尾、回忆、释然
```

**红线：同一场景内不得出现超过两个连续的相同景别。** 例外只有刻意制造效果时（如两个特写叠加制造窒息感），且必须在分镜表里注明意图。

### 铁律五 · 色调是情绪的底色

同场景连续镜头色调必须一致。剧情有情绪转折时（平静 → 崩溃）色调**可以**跟着变，但**变的过程必须有过渡**。

```text
✗ 前一镜暖色调 → 后一镜突然冷色调
✓ 暖色调 → 过渡镜（半明半暗的画面，或一个表情变化的近景）→ 冷色调
```

过渡镜给色调转换一个「呼吸感」。没有过渡镜的色调跳变，观众读到的是穿帮，不是情绪。

---

## 一、六大连贯锚点

第 2 镜起，每一镜都必须锁住这六项：

| 锚点 | 锁什么 | 提示词写法 |
|---|---|---|
| 人物 | 同一张脸、同一发型、同一服装、同一配饰、同一伤痕 | `同一人物同一张脸同一发型同一服装` |
| 空间 | 同一场景、同一左右画面方向 | `同一场景与左右画面方向，正反打遵守180度轴线` |
| 动作 | 从上一镜最后一帧自然延续 | `承接上一镜最后一帧、动作与站位无缝衔接` |
| 情绪 | 逐级递进，不突变 | `情绪逐级递进不突变` |
| 道具 | 始终在同一只手、同一位置 | `道具始终在同一只手同一位置` |
| 光影 | 光源方向、色温、时间一致 | `光影色温时间一致` |

**正向串**（可直接拼进任何视频提示词）：

```text
严守跨镜连贯六锚点：同一人物同一张脸同一发型同一服装、同一场景与左右画面方向、
动作从上一镜自然延续、情绪逐级递进不突变、道具始终在同一只手同一位置、光影色温时间一致，
正反打遵守180度轴线
(same character, same outfit, same hairstyle, same location, same screen direction,
prop continuity, gradual emotional continuity, obey 180-degree rule)
```

**负向串**：

```text
(规避跨镜断裂：jump cut, time skip, sudden pose change, teleporting, changing background,
changing outfit, changing hairstyle, changing face, inconsistent lighting, axis flip,
broken eyeline, disappearing prop, duplicated prop, mismatched action, abrupt emotion change,
random camera angle, spatial discontinuity, flickering, scene reset)
```

**承接句**（第 2 镜起每镜开头）：

```text
directly continues from the final frame of the previous shot, matching action and screen direction,
承接上一镜最后一帧、动作与站位无缝衔接
```

---

## 二、逐镜单动作原则

一个镜头只推进**一个**小动作。禁止从「发现」直接跳到「离开」。

标准五步拆法：

```text
发现 → 反应 → 消化 → 决定 → 行动
```

复杂动作按 `准备 → 执行 → 结果` 拆，必要时细分 3–5 步。

> 例：「喝水」拆成 伸手 → 拿起水杯 → 送到嘴边饮下 → 放下水杯。
> 例：「看到信后离开」拆成 视线落到信上（发现）→ 瞳孔收缩呼吸一滞（反应）→ 手指捏紧信纸（消化）→ 抬眼看向门口（决定）→ 起身推门（行动）。

必须切镜的六种情况：情绪显著转变、复杂动作、人物增减或关系转换、空间转场、时间跳跃、说话人更替（视线乒乓）。

---

## 三、人物一致性

### 3.1 角色不变量卡（每个角色写一次，全片引用）

```text
【角色不变量 · {角色名}】
面孔：{脸型/五官特征/肤色/年龄感}
发型：{长度/分缝/束发方式}，全片不变
服装：{上衣/下装/外披/鞋}，颜色与材质固定
配饰：{饰品及其佩戴位置}
伤痕/标记：{位置与形态}，出现后不得消失
持有道具：{道具}恒定在{左/右}手
体态：{身高比例/站姿习惯}
音色：{音色描述}
```

### 3.2 写法要点

- 有参考图时**不要**在提示词里重述长相，只用 `<主体1>` 代号引用——重述是漂移的头号来源。
- 无参考图时，把不变量卡整段写进 `retention_analysis`，并在每镜只写差异。
- 服装状态变化（湿透、破损、沾血）一旦发生，后续所有镜头都必须继承。

### 3.3 分身 / 复制人防治

多角色同框时模型常把主角复刻成外形一致的「分身」站在旁边。固定挂：

```text
视频全程禁止出现外形、着装、配饰完全一致的人物，禁止生成同款分身、双胞胎效果，
同一画面中仅保留单个对应人物，不出现人物重复复刻
(no duplicated character, no twin, no clone, no repeated identical person, single instance per character)
```

---

## 四、场景一致性

1. 每场戏先写一份**场景圣经**（见 [blocking-lighting.md](blocking-lighting.md) §三 场景圣经），后续镜头全部继承。
2. 提示词里写死：`背景保持{场景圣经描述}不变，不要改变构图与陈设，背景简洁稳定不随机发挥`。
3. 场景复用是短剧的成本核心——同一地点的所有镜头共用同一张场景参考图。

> **打戏例外：只有列进「可破坏元素清单」的东西才允许被打坏。** 场景圣经第⑥要素（可破坏元素清单，见 [blocking-lighting.md](blocking-lighting.md) §3.1）写明了本场哪些元素可以碎、碎成什么形态；这些元素的破坏在提示词正文里正面写死，不受第 2 条那句负面串管辖。清单以外的墙面、家具、门窗、道具，全场仍被第 2 条封死。反过来，嫌打戏碍事就把 `不要改变构图与陈设` 整句删掉，等于放开了全部陈设——桌椅换位、墙面花纹变形、道具凭空增减，一镜一个屋子。

---

## 五、首尾帧衔接

跨镜衔接的机械保证：

```text
第 N 镜的落幅 == 第 N+1 镜的起幅
```

写法：把上一镜落幅的画面描述，原样抄进下一镜的起幅位置。这样即使模型不理解「承接」，画面本身也对得上。

需要严丝合缝时，直接用**首尾帧模式**：把上一镜的末帧图作为下一镜的首帧图。

---

## 六、时间与光线连续性

- 同一场戏内时间不流动：光源方向、色温、影子长度全程不变。
- 需要表现时间流逝时，必须给一个独立的**转场镜**（成片上占 1–2 秒；这是剪辑时长，生成时仍按 ≥4 秒下单再裁短），不要在正戏镜头里偷偷换光。
- 雨、雪、烟、尘等环境元素一旦出现，后续同场镜头必须持续存在。

---

## 七、输出前一致性自检清单

- [ ] 每一镜都写了起幅与落幅？
- [ ] 第 N+1 镜的起幅 == 第 N 镜的落幅？
- [ ] 六锚点串（人物/空间/动作/情绪/道具/光影）已挂在每一镜？
- [ ] 角色左右站位全场未翻转？没有越轴？
- [ ] 道具在同一只手、同一位置？没有凭空出现或消失？
- [ ] 服装状态变化（湿/破/血）被后续镜头继承了？
- [ ] 情绪是逐级递进的，没有从平静直接跳到崩溃？
- [ ] 同一场戏的光源方向与色温一致？
- [ ] 素材代号（`@图片N` / `<主体N>` / `<场景N>`）全片统一？
- [ ] 防分身负面串已挂？
- [ ] 每镜只推进了一个小动作，没有跳步？
- [ ] 相邻两镜的同一动作呈「半拍」关系（后镜是前镜完成五到八成的状态）？
- [ ] 视线方向连续：上一镜看向画面右侧，本镜对象出现在画面左侧或正前方？
- [ ] 同一场景内没有超过两个连续的相同景别？
- [ ] 色调转折处插了过渡镜，没有暖冷直接跳变？

---

# 附：完整词典与扩展条目

> 上文为速查版（分镜阶段按预算截断时优先保留）；以下为完整版。

> 本节是分镜生成前必须先执行的"上锁"环节。核心方法：**先写连续性圣经，再写分镜表；每个镜头都继承上一镜的状态；每条提示词只推进一个小动作；用可观察的物理连续代替抽象剧情描述。**

## 0. 锁的优先级与总览

### 0.1 连续性优先级（冲突时按此顺序取舍）

```text
角色一致性 > 光影一致性 > 色调一致性 > 背景一致性 > 运动一致性
```

### 0.2 五大连续性维度与失败表现

| 维度 | 说明 | 失败表现 |
|------|------|----------|
| 视觉连续性 | 画面风格、色彩、光影一致 | 前后镜头色调突变、光线矛盾 |
| 角色连续性 | 人物外观、服装、姿态一致 | 换脸、衣服颜色变化、发型突变 |
| 空间连续性 | 场景布局、物品位置一致 | 背景物品消失、空间关系错乱 |
| 时间连续性 | 光线变化合理、动作衔接 | 白天突然变黑夜、动作不接 |
| 运动连续性 | 动作方向、速度、节奏一致 | 人物朝左走突然朝右、速度突变 |

### 0.3 六把锁与平台字段的对应

| 锁 | 对应分镜契约字段 | 生成阶段生效点 |
|---|---|---|
| 人物锁 | `characters` / `character_id:state_id` / 五视图引用 | 角色卡 → 图片提示词 → 视频提示词 |
| 空间锁 | `scene` / `composition` / `camera_angle`（轴线侧） | 场景圣经 → 九宫格 → 运镜 |
| 动作锁 | `subject_action` / `start_state` / `end_state` | 逐镜单动作拆分 |
| 情绪锁 | `expression` / 情绪曲线阶段 | 情绪圣经 → 每镜只推进一级 |
| 道具锁 | `props`（名称:所在手:状态） | start/end state + continuity_in/out |
| 光影锁 | `lighting`（主光方向、色温、时间、天气） | 场景圣经 → 全场复用 |

---

## 1. 六大连贯锚点

AI 短剧想不跳跃，每个镜头都要锁住六类信息。

| 锚点 | 要锁定什么 | 常用提示词 |
|---|---|---|
| 人物连续 | 同一张脸、同一发型、同一服装、同一站位 | `same character, consistent face, same outfit, same hairstyle` |
| 空间连续 | 角色在房间里的方向、距离、左右关系 | `same location, same room layout, screen direction preserved` |
| 动作连续 | 下一镜从上一镜动作结束处接上 | `continues from previous shot, matching action, action continuity` |
| 情绪连续 | 情绪逐步变化，不突然换情绪 | `gradual emotional transition, same emotional state carried over` |
| 道具连续 | 手机、杯子、信、刀、包的位置不变 | `same prop in the same hand, prop continuity` |
| 光影连续 | 同一场戏保持同一光源方向和色温 | `same lighting direction, consistent color tone, same time of day` |

### 1.1 连贯性专用约束词库（按锚点分组）

#### 人物一致

```text
same character, consistent face, same facial features, same hairstyle, same outfit, same makeup, same age, same body shape, no face change, no hairstyle change, no outfit change
```

#### 空间一致

```text
same location, same room layout, same furniture placement, same background, same screen direction, same left-right relationship, no background change, no teleporting, no spatial jump
```

#### 动作一致

```text
matching action, action continuity, starts from the previous pose, continues the previous motion, no sudden pose change, no skipped movement, no abrupt body position change
```

#### 道具一致

```text
same prop, prop continuity, same prop position, same object in the same hand, no disappearing prop, no duplicated prop, no changing object
```

#### 光影一致

```text
same lighting direction, same color temperature, consistent shadows, same time of day, same weather, consistent exposure, no lighting shift, no color shift
```

#### 镜头一致

```text
preserve camera axis, obey the 180-degree rule, consistent eyeline, consistent screen direction, no axis flip, no random camera angle change
```

### 1.2 通用连续性公式

#### 中文公式

```text
[镜头编号] + [承接上一镜状态] + [同一人物与服装] + [同一空间与站位] + [上一镜动作的延续] + [本镜只推进一个小动作] + [情绪连续] + [光影连续] + [镜头运动] + [稳定性约束]
```

#### 英文公式

```text
[shot number], continues directly from the previous shot, same character with consistent face and outfit, same location and screen direction, matching action from the last frame, only one small action progresses in this shot, gradual emotional continuity, same lighting and color tone, [camera movement], continuity constraints
```

#### 最小可用英文连续性句（可直接尾缀到任何镜头提示词）

```text
continues directly from the previous shot, matching the last frame, same character, same outfit, same hairstyle, same location, same screen direction, same prop position, gradual emotional continuity, no jump cut, no sudden pose change, no teleporting, no changing background
```

#### 最小可用中文连续性句

```text
直接承接上一镜最后一帧，同一人物，同一服装，同一发型，同一场景，同一站位，同一道具位置，动作从上一镜自然延续，情绪缓慢递进，不要跳切，不要突然换姿势，不要瞬移，不要更换背景
```

### 1.3 逐镜「承接上一镜」检查清单（每一镜发出前必跑）

> 六项全部有明确答案才允许写提示词；任一项写不出来，说明上一镜的落幅状态没记录，回去补 `end_state`。

- [ ] **人物**：承接上一镜的哪张脸、哪套服装、哪个发型、哪个站位？（`character_id:state_id` 是否与上一镜相同）
- [ ] **空间**：角色在画面左还是右？与上一镜的左右关系是否一致？轴线在哪一侧？出入口、家具位置是否复用场景圣经？
- [ ] **动作**：上一镜结束时身体处于什么姿态（坐/站/转身进行中/手抬到什么高度）？本镜从这个姿态的准确位置继续。
- [ ] **情绪**：上一镜结束在情绪曲线的哪一级？本镜只推进一级，不跳级。
- [ ] **道具**：道具在谁手上、哪只手、什么状态（亮屏/合上/半满/破损）？位置与上一镜逐字相同。
- [ ] **光影**：主光方向、色温、时间、天气是否与上一镜完全一致？是否出现无动机的光位变化？

补充三问（多人/对话镜必答）：

- [ ] 正反打（shot-reverse-shot）是否保持 180 度轴线（180-degree rule），A 始终在画面左、B 始终在画面右？
- [ ] 视线是否匹配（eyeline match）：上一镜看向画面右侧，本镜就应揭示画面右侧的对象。
- [ ] 本镜要向下一镜交付什么（`continuity_out`）？写成一句可复制的落幅状态。

### 1.4 分镜连续表模板（先出表，再逐镜生成）

| 镜号 | 时间 | 承接上一镜 | 人物站位 | 动作连续 | 情绪阶段 | 道具状态 | 镜头 | 提示词重点 |
|---|---|---|---|---|---|---|---|---|
| S01 | 0-3s | 开场建立 | A在左，B在右 | 两人静止 | 压抑平静 | 手机在茶几右上角 | 全景静止 | 固定空间和人物关系 |
| S02 | 3-6s | 接S01两人站位 | A仍在左侧 | A低头看手机 | 怀疑 | A右手靠近手机 | 中景慢推 | 动作只推进到低头 |
| S03 | 6-9s | 接S02低头状态 | A靠近茶几 | A拿起手机 | 被刺痛 | 手机在A右手 | 手部特写 | 道具连续 |
| S04 | 9-12s | 接S03手机在手 | A抬头看B | A眼眶泛红 | 强忍眼泪 | 手机仍在右手 | 近景慢推 | 情绪递进 |
| S05 | 12-15s | 接S04强忍状态 | A转身离开 | A缓慢转身 | 沉默离开 | 手机垂在右手 | 慢拉远 | 空间与动作收束 |

输出字段固定为：**镜号、时长、承接上一镜、景别、运镜、人物站位、动作、情绪阶段、道具状态、光影、中文提示词、英文提示词、负面提示词。**

### 1.5 15 秒短剧连续性结构（对应 minimax H3 / seedance 2.0 单镜上限）

15 秒五拍表（0-3s 建立场景与人物关系 / 3-6s 触发事件 / 6-9s 角色反应 / 9-12s 情绪升级 / 12-15s 行动或悬念，含每拍的镜头建议）以 [prompt-contracts.md](prompt-contracts.md) §6.4「15 秒五拍连续性变体」为准，本文件不重复。下面两条是这张表在**连续性**上最容易被读错的地方。

> **表头的 0-3s / 3-6s 是成片时间线位置，不是生成请求时长。** §1.4 的分镜连续表与 prompt-contracts.md §6.4 五拍表里的「一格 3 秒」，说的是这一镜在 15 秒成片里占哪一段（层③·成片剪辑时长），**不是让你把 `duration=3` 填进请求**——4 秒是平台地板值，填 3 直接 400 打回。正确算法：15 秒五镜按 **5 × 4 秒下单 = 20 秒素材**，剪辑台每镜各裁掉约 1 秒，落回 15 秒时间线。三层口径（生成请求 / 动作节拍 / 成片剪辑）的完整对照表以 [models-failures.md](models-failures.md) §1.1 为准，本文件不重复。
>
> **多下单的那 1 秒要留在落幅之后，不能留在动作中间。** 写这一拍时把动作在 4 秒内做完并**保持住落幅姿态**，末尾 1 秒只留余劲（呼吸起伏、衣料回落、手仍停在原处），裁的就是这段余劲——落幅状态没变，下一镜起幅照样原样承接（见 §五）。反过来把动作正好卡在第 4 秒收住，裁掉 1 秒就等于把动作拦腰截断，下一镜起幅接的是一个没做完的姿态，两句连着一念就断。

### 1.6 整场生成模板（连续性规则版）

#### 中文整场生成模板

```text
请为以下 AI 短剧生成连续分镜。要求剧情和镜头无跳跃，所有镜头必须直接承接上一镜最后一帧。

连续性规则：
1. 同一角色保持同一张脸、同一发型、同一服装、同一饰品。
2. 同一场景保持相同空间布局、家具位置、道具位置、光源方向和时间状态。
3. 每个镜头只推进一个小动作，不允许从“发现”直接跳到“离开”。
4. 情绪必须逐步递进，不允许突然大哭、突然愤怒、突然释然。
5. 正反打必须遵守180度轴线，角色左右关系不变。
6. 下一镜必须写明“承接上一镜的什么动作、什么站位、什么道具状态”。

输出字段：镜号、时长、承接上一镜、景别、运镜、人物站位、动作、情绪阶段、道具状态、光影、中文提示词、英文提示词、负面提示词。

剧情：[填写剧情]
角色圣经：[填写人物固定描述]
场景圣经：[填写场景固定描述]
情绪曲线：[填写情绪递进]
```

#### 英文整场生成模板

```text
Create a continuous shot list for an AI short drama. The story and camera flow must have no jumps. Every shot must continue directly from the final frame of the previous shot.

Continuity rules:
1. Keep the same character face, hairstyle, outfit, accessories, and body shape.
2. Keep the same location layout, furniture placement, prop positions, lighting direction, and time of day.
3. Each shot advances only one small physical action. Do not jump from discovery directly to leaving.
4. Emotional changes must be gradual. No sudden crying, sudden anger, or sudden relief.
5. Preserve the 180-degree rule in shot-reverse-shot scenes. Keep left-right relationships consistent.
6. Each next shot must state what action, position, and prop status it inherits from the previous shot.

Output columns: shot number, duration, continuity from previous shot, shot size, camera movement, character positions, action, emotional stage, prop status, lighting, Chinese prompt, English prompt, negative prompt.

Story: [insert story]
Character bible: [insert fixed character description]
Location bible: [insert fixed location description]
Emotional arc: [insert emotional progression]
```

---

## 2. 逐镜单动作原则

### 2.1 五步拆分法：发现 → 反应 → 消化 → 决定 → 行动

**原则：每一步单独成镜，禁止跳步。**

#### 错误写法

```text
她发现真相后崩溃离开。
```

问题：动作和情绪跨度太大，AI 会跳过中间过程。

#### 正确拆分

```text
S01：她低头看到手机上的消息，身体僵住。
S02：她缓慢抬眼看向对方，眼眶开始泛红。
S03：她嘴唇抿紧，右手攥住手机，呼吸变重。
S04：她没有说话，只是后退半步。
S05：她转身，手机垂在右手，缓慢走出客厅。
```

| 步骤 | 镜头职责 | 可见物理动作 | 情绪级别变化 | 典型景别 |
|---|---|---|---|---|
| 发现 | 信息进入角色 | 低头看到 / 听到 / 触到 | 平静 → 定住 | 中景或手部/屏幕特写 |
| 反应 | 身体先于理智反应 | 身体僵住、呼吸停顿、瞳孔收缩 | +1 级（怀疑） | 近景 |
| 消化 | 情绪在脸上流动 | 抬眼、抿唇、攥紧道具、呼吸变重 | +1 级（被刺痛） | 近景慢推 / 大特写 |
| 决定 | 出现选择动作 | 后退半步、放下道具、握紧拳 | +1 级（强忍） | 大特写或半身 |
| 行动 | 执行并交付下一镜 | 转身、离开、递出、按下 | 收束 | 慢拉远 / 背影 |

### 2.2 单镜密度红线

| 约束 | 数值 | 依据/后果 |
|---|---|---|
| 每镜推进的物理动作 | **1 个**（可配 1 个辅助动作） | 3 个并发肢体动作显著提高肢体变形风险 |
| 每个独立物理动作留时 | **2–4 秒（区间）** | 低于下限 → 糊动（motion mush）、动作被跳过；高于上限 → 帧间位移累积、动作崩坏 |
| 每 5 秒时间片内事件数 | ≤ 2–3 个 | 超过则时间线压缩，部分事件被整段跳过 |
| 每 3–5 秒至少 | 1 个新动作或状态变化 | 否则出现循环/静止（looping / freezing） |
| 每镜推进的情绪阶段 | **1 级** | 跳级 = 情绪突变，观众出戏 |
| 情绪过渡留时 | 至少 1–2 秒（真人肌肉 0.3–1.5 秒过渡） | 瞬间切换 = AI 假脸四大陷阱之一 |
| 微表情密集镜头切片 | 每 2 秒一个切片，一个核心变化 + 一个联动细节 | 让情绪像水一样流动，而非像开关一样跳变 |
| 关键情绪转折/揭示 | 至少 3–5 秒专属时长 | 时长不足会被压缩掉 |

> 本表所有秒数都是**动作节拍时长（层②）**，不是生成请求时长（层①）——生成请求恒 **≥ 4 秒**（平台地板值），短节拍由 4 秒素材裁出（见 [models-failures.md](models-failures.md) §1.1）。写分镜表时按节拍算，提交生成时按 4 秒起算，两者不冲突。

### 2.3 动作写法：因果链代替结果词

- ❌ `拿出信封`
- ✅ `右手从口袋中缓慢抽出信封 → 五指握住信封上缘 → 手臂向前平伸递出`
- ❌ `走过去`
- ✅ `向画面左侧大步迈出三步`
- ❌ `她的手放在桌上`（静态状态 → 会循环/静止）
- ✅ `她的手从桌面缓慢滑向信封边缘，指尖停在封口处`

> 手部精度要求高时指明左右手与手指；关键时加 `双手始终保持自然的五指结构`。

### 2.4 情绪圣经与情绪递进模板

#### 情绪圣经模板

```text
本场情绪曲线：压抑平静 → 怀疑 → 被刺痛 → 强忍眼泪 → 沉默离开。每个镜头只推进一个情绪阶段，不允许突然大哭、突然愤怒或突然释然。
```

```text
Emotional arc of this scene: restrained calm → suspicion → emotional hurt → holding back tears → silent departure. Each shot advances only one emotional stage. No sudden crying, no sudden rage, no sudden relief.
```

#### 情绪递进整句模板

「从平静到崩溃」「从隐忍到愤怒爆发」「从心动到克制」「从震惊到麻木」四条可直接粘贴的整句提示词（中英双语）见 [performance-action.md](performance-action.md) §1.9，本文件不重复。把它们**拆到 4–5 个镜头**里逐镜推进，仍受本节「每镜只推进一个情绪阶段」约束。

#### 情绪断层的两条连续性修法

情绪类问题的完整修正表（13 行，含表情太夸张 / 哭戏假 / 角色没情绪 / 情绪不连贯）见 [performance-action.md](performance-action.md) §1.13。跨镜连续性上只有这两条必须逐镜执行：

| 问题 | 修正方法 |
|---|---|
| 面瘫式静态面部 | 添加活体呼吸感：`轻微呼吸起伏`/`偶尔眨眼`/`subtle breathing rhythm` |
| 情绪瞬间切换 | 使用渐进词：`逐渐`/`缓缓`/`一点点`，至少留 1-2 秒的情绪过渡（配合 §2.2 的情绪过渡留时红线） |

---

## 3. 人物一致性锁

### 3.1 锁定强度阶梯（从源头做一致性，不靠后期硬救）

```text
强 ┌─ 首帧参考（image-to-video）★推荐主力
   │    用锁定好的角色图作为视频首帧驱动，
   │    一致性远高于纯文字生成（text-to-video）
   │
   ├─ 角色 LoRA / face embedding
   │    对同一角色训练专属模型，跨镜头复用
   │
   ├─ 固定种子（fixed seed）
   │    同一 seed + 同一提示词，减少随机漂移
   │
弱 └─ 纯提示词描述
        仅靠文字描述外貌，漂移最严重，不可单独依赖
```

- ❌ 避免：每个镜头用纯 text-to-video 重新生成人物
- ❌ 避免：靠"美女"这类模糊词描述人物（每次生成都不同）
- ❌ 避免：先生成动作再考虑一致性（漂移已发生，只能靠后期硬救）
- ❌ 避免：特写镜头堆叠（脸部细节暴露最多，漂移最致命）
- ✅ 使用：image-to-video，首帧锚定同一张角色参考图
- ✅ 使用：具体到字段的锚定块，全程逐字复用

### 3.2 五视图角色设定板（角色锚点的唯一来源）

五个视图从左到右固定顺序：**正面（front view，0°）→ 正面四分之三（front three-quarter view，约 45°）→ 标准侧面（standard profile view，90°）→ 背面四分之三（rear three-quarter view，约 135°）→ 背面（back view，180°）**。

五视图用于锁定：

- **身份 DNA**：脸型、五官比例、痣/疤位置、纹身、年龄感和肤色，发型、发色、角色气质、时代背景；
- **头发**：发际线、发型结构、长度、发色和头饰；
- **身体**：身高、肩宽、体型、四肢比例和站姿基准；
- **服装**：版型、层次、颜色、面料、纹样、鞋子和磨损状态；
- **标志物**：眼镜、耳饰、项链、腕表、武器或剧情道具。

分镜、海报、角色动作、九宫格和运镜视频都必须引用这份角色锚点，不得仅凭文字重新生成。

#### 硬性规范

| 类别 | 规范 |
|---|---|
| 画布与排列 | 一张横向画布，严格划分为五个等宽面板；五个面板只能放同一个角色，顺序不可改变 |
| 拍摄条件 | 同焦段、同相机高度、同中性光、同纯色背景 |
| 完整性 | 每格完整全身、自然站姿、双脚不裁切、身体无遮挡 |
| 比例 | 五个视图的角色高度和缩放比例一致 |
| 身份 | 同一脸型、同一五官比例、同一痣/疤位置、同一发际线、同一发型、同一服装、同一配饰、同一身材 |
| 角度职责 | 角度变化只能揭示新的侧面或背面信息，不能重新设计角色 |

#### 禁止项

```text
禁止重复角度、镜像脸、多人、额外肢体、手指异常、裁切脚部、坐姿、动态姿势、透视夸张、服装变体、发型变体、场景道具、文字、水印、边框标题和复杂背景。
```

#### 项目标准中文模板

```text
为角色「[角色名称]」制作同一人物、同一服装、同一发型、同一体型的五视图角色设定板。
画布严格横向等宽五栏，五个视图按从左到右固定顺序：
正面、正面四分之三、标准侧面、背面四分之三、背面。

身份 DNA：[脸型、五官比例、肤色、痣/疤及准确位置、年龄感]。
发型：[发际线、长度、结构、发色、头饰]。
体型：[身高感、肩宽、体型、四肢比例]。
服装：[上衣、下装、外套、鞋子、颜色、材质、纹样、磨损状态]。
配饰：[固定配饰及佩戴位置]。
视觉风格：[写实电影角色设定 / 国风写实 / 动画设定等]。

五个视图必须是同一个人物，不得改变脸型、五官比例、痣/疤位置、发际线、发型、服装、配饰和身材。
同焦段、同相机高度、同中性光、同纯色背景、完整全身、自然站姿、无遮挡。
禁止重复角度、镜像脸、多人、额外肢体、裁切脚部、文字、水印和场景道具。
```

#### English template

```text
Create one strict five-panel full-body character turnaround sheet for [character name].
Use one horizontal canvas divided into five equal-width panels in this fixed left-to-right order:
front view, front three-quarter view, standard profile view, rear three-quarter view, back view.

The five panels must depict the exact same identity, face proportions, age, skin tone, hairline,
hairstyle, hair color, body proportions, outfit construction, colors, materials and signature accessories.
Identity DNA: [identity details]. Visual style: [style].

Use the same focal length, camera height, neutral lighting, plain background, scale and natural standing pose.
Show the complete body and both feet without occlusion.
No repeated angles, mirrored face, extra people, extra limbs, cropped feet, outfit variants,
text, watermark, title, props or environmental scenery.
```

> 参考图补充规范（用于图生视频首帧/身份锚定）：同一光照、同一人物；表情取**中性基准**（不带情绪，避免锁定到特定表情）；柔光正面、无强阴影（便于后续重打光）；分辨率 ≥ 1024×1024，五官清晰无模糊；纯色/灰底（避免背景干扰特征提取）；主角 3-5 张多角度，配角至少 1 张正面。

### 3.3 角色 DNA 锁定字段

#### 五维 DNA 特征清单（拒绝抽象形容词）

| 维度 | 核心特征清单 | 描述技巧与控制词示例 |
| :--- | :--- | :--- |
| **面部** | 脸型、眼距、鼻梁高度、眉形、特定标记 | “瓜子脸，剑眉星目，左眼下方有一颗泪痣，`consistent facial structure`，`locked face identity`” |
| **发型** | 发色、长度、质地、分缝位置 | “黑色碎发，`保持发型不变`，`与参考图中发型一致`” |
| **体型** | 身高、肩宽、四肢比例 | “身高180cm，偏瘦体型，九头身比例，`normal human proportions`” |
| **服饰** | 核心主色调、款式、材质、标志性配件 | 固定描述句式：“身穿黑色连帽卫衣，配戴银色项链” |
| **情绪/动作** | 常用表情气质、眼神特征 | “眼神冷峻，嘴角习惯性微扬，符合XX性格” |

#### 必锁定字段表

| 字段 | 必须锁定的内容 | 示例 |
|------|--------------|------|
| 脸型 | 脸型形状 | `oval face` / `square jaw` |
| 眼睛 | 形状 + 瞳色 | `almond-shaped dark brown eyes` |
| 发型 | 长度 + 颜色 + 分缝 | `black shoulder-length hair, center part` |
| 肤色 | 明确色调 | `fair skin` / `tan skin` |
| 标志特征 | 痣/疤/酒窝/雀斑 | `small mole below left eye` |
| 服装 | 款式 + 颜色 | `beige trench coat over white shirt` |
| 体型 | 身材 + 比例 | `slim build, 168cm proportion` |

#### 角色锁定卡（五视图质检通过后提取，后续镜头复制，不得自由改写）

```yaml
character_id: char_001
name: "[角色名称]"
identity_dna:
  age_appearance: "[年龄感]"
  face_shape: "[脸型]"
  eyes: "[眼型、颜色、间距]"
  eyebrows: "[眉形、浓淡]"
  nose: "[鼻梁、鼻头]"
  lips: "[唇形、颜色]"
  skin: "[肤色、质感]"
  marks: "[痣、疤、纹身与准确位置]"
hair:
  hairline: "[发际线]"
  style: "[发型结构]"
  color: "[发色]"
body:
  height: "[身高感]"
  build: "[体型、肩宽、比例]"
outfit:
  upper: "[上衣]"
  lower: "[下装]"
  outerwear: "[外套]"
  shoes: "[鞋子]"
  palette: ["[主色]", "[辅色]"]
  material: "[材质]"
signature_accessories: ["[固定配饰]", "[固定道具]"]
five_view_order: ["正面", "正面四分之三", "标准侧面", "背面四分之三", "背面"]
five_view_image: "[五视图图片地址]"
```

#### 禁止变化（角色卡的硬约束）

- 不改变身份、脸型、五官比例、年龄感和肤色；
- 不改变发际线、发型、发色和头饰；
- 不改变服装版型、层次、颜色、材质和鞋子；
- 不改变体型、身高感和四肢比例；
- 不丢失或新增标志性配饰、伤疤、纹身和剧情道具。

### 3.4 角色描述锚定块（全程逐字复用）

```text
[角色A 锚定块 — 全程复用]
A 28-year-old woman, oval face, almond-shaped dark brown eyes,
straight black shoulder-length hair with center part,
small mole below left eye, fair skin,
wearing a beige trench coat over white shirt,
slim build, 168cm proportion
```

#### 人物圣经模板（中文/英文，复制到每一镜的人物部分）

```text
角色A：28岁女性，椭圆脸，黑色长直发，低马尾，白色针织衫，浅蓝牛仔裤，左手戴银色戒指，妆容自然，疲惫但克制的眼神。全场保持同一张脸、同一发型、同一服装、同一饰品。
```

```text
Character A: a 28-year-old woman, oval face, long straight black hair tied in a low ponytail, white knit sweater, light blue jeans, silver ring on her left hand, natural makeup, tired but restrained eyes. Keep the same face, hairstyle, outfit, and accessories throughout the entire scene.
```

### 3.5 跨镜头身份锚点（3 镜以上项目必加）

为每个角色指定 **2–3 个永久可见的独特物理标记**，要求在不同姿态、光线和角度下都能被模型抓住。

```text
林澈的跨镜头锚点：左眉浅疤（始终可见）、右手无名指银色戒指、深蓝旧夹克左胸口袋别一支钢笔。
米娅的跨镜头锚点：红色丝巾系在左腕、右耳单颗珍珠耳坠、黑色Moleskine笔记本始终在右手或右侧口袋。
```

写入连续性圣经的不变量段落：

```text
【不变量 — 角色锚点】
林澈的左眉浅疤、银戒指和蓝夹克口袋钢笔在所有镜头中保持可见。
米娅的红丝巾、珍珠耳坠和黑色笔记本在所有镜头中保持可见。
```

- 5 镜以上项目：提供多视角参考图（正面、四分之三、侧面），不要只给一张正脸——角色转身时身份才守得住。
- 长片提示词：在**每一幕开头重述角色不变量**，不要只写在圣经抬头。

### 3.6 服装 / 发型 / 配饰 / 伤痕 / 道具 handoff

| 类别 | 锁定粒度 | Handoff 规则 | 漂移时的修法 |
|---|---|---|---|
| 服装 | 版型、层次、颜色、材质、纹样、鞋子、磨损状态（不要只写“黑色西装”） | 词组顺序、修饰词在每镜中**绝对一致**，逐字复制 | ControlNet Depth/Pose 约束轮廓；局部重绘（inpaint）修正；负面词 `--no extra accessories, changing clothes, changing patterns` |
| 发型 | 发际线、分缝、刘海、长度、卷度、发色、头饰位置 | 五个视图逐项核对后再进入分镜 | 明确写出每一项，禁止只写“长发” |
| 配饰 | 固定配饰 + 佩戴位置（左手/右耳/左腕） | 不丢失、不新增；`missing accessory / added accessory` 入负面词 | 参考图中突出配饰特征 |
| 妆发状态 | 浓淡、凌乱度与时间/场景/人物状态匹配 | 哭戏、雨戏、打斗后的妆发变化必须有剧情原因，逐步体现 | 不允许突然精致或突然凌乱 |
| 伤痕/战损 | 位置、面积、颜色、湿度、新旧 | **只能单向恶化**：受伤后下一镜不得痊愈；血迹、脏污、雨水状态连续 | 战损版作为新的**角色状态**独立生成五视图，不覆盖基础状态 |
| 道具 | 名称、归属、所在手、空间位置、状态 | 在每镜 `start_state` 与 `end_state` 中声明，下一镜 `continuity_in` 原样承接 | 状态变化必须写明触发点与新状态 |

#### 角色状态（state_id）规则

儿童版、老年版、战损版、换装版作为新的"角色状态"，分别生成五视图；**不得覆盖基础状态**。每个分镜格按 `character_id + state_id` 引用角色，**不通过姓名模糊匹配**。

### 3.7 同一只手、同一位置：道具连续写法

道具字段格式（九宫格每格必填）：

```yaml
props: ["prop_phone:right_hand:screen_on"]
```

首尾状态声明（防止道具换手/消失/复制）：

```yaml
start_state: "手机位于右手胸前，视线落在屏幕"
end_state: "手机仍在右手胸前，视线抬向画外右侧"
continuity_in: "承接上一镜手机亮屏和右手位置"
continuity_out: "向下一镜交付画外右侧视线"
```

道具状态发生变化时，必须写明**原因、时刻和新状态**，并声明旧状态不可复现：

```text
00:42，她因抓住栏杆停下，将车票塞入夹克右侧口袋；此后双手空出，车票不可重新出现在手中。
```

道具连续提示词：

```text
same prop, prop continuity, same prop position, same object in the same hand, no disappearing prop, no duplicated prop, no changing object
```

```text
同一道具仍在同一只手里，道具位置不变，不要道具消失，不要道具重复，不要道具换手
```

> 道具库固定字段：道具名、外观、所属角色、首次出现、剧情作用、状态变化、最终去向。使用后状态要更新（破损、丢失、转交、隐藏）；道具不能在没有记录的情况下进入关键剧情。

### 3.8 多角色同框防串脸

防串脸六条方案（分别锚定 / 差异化设计 / 视线站位绑定 / 优先分镜规避 / 竖屏单人优先 / 背景简洁稳定）见 [performance-action.md](performance-action.md) §4.6，本文件不重复。跨镜连续性上只补一条：**同一组角色的锚定块必须逐镜逐字复用**，左右站位一旦定下就不得在后续镜头里对调（见 §4.8）。

#### 角色台账（Role ledger，多人镜必写）

| Role | Visual identity | Costume/prop | Start position | Voice/dialogue |
|---|---|---|---|---|
| A / 林澈 | @图片1 | blue coat, silver ring | frame left | @音频1; Mandarin |
| B / 米娅 | @图片2 | red scarf, black notebook | frame right | no voice ref; Spanish |

- 每个角色提供独立五视图，分镜中使用不同 `character_id`，明确左右站位、视线和服装，**禁止仅用“男人/女人”区分**。
- 保持每个人的脸、头发、服装、身体比例、道具、画面站位和声音稳定；若角色交换位置，必须描述交叉动作和交换后的结果站位。

### 3.9 人物一致性强化词库

#### 正向词

```text
same character, same identity, identical facial proportions, same hairline, same hairstyle,
same outfit construction, same colors and materials, same body proportions, same age appearance,
same signature accessories, strict five-view character reference,
front view, front three-quarter view, standard profile view, rear three-quarter view, back view
```

```text
同一个人物，同一身份，同一张脸，同一五官比例，同一发际线，同一发型和发色，
同一服装版型、颜色与材质，同一体型和年龄感，同样的标志性配饰，严格参考角色五视图
```

#### 负向词

```text
different person, identity drift, face variation, age change, hairstyle change, hair color change,
outfit change, missing accessory, added accessory, body proportion change, mirrored face,
duplicate angle, extra person, extra limbs, deformed hands, cropped feet, text, watermark
```

### 3.10 角色漂移诊断（症状 → 根因 → 修法）

**症状**：角色的脸、头发、身材比例或服装在不同镜头间变化；第 5 镜的人明显不像第 1 镜。

| 根因 | 修法 |
|---|---|
| 身份只有文字描述，没有视觉锚点 | 提供清晰、正面、光线良好的身份参考图，并绑定明确范围：`@图片1 → 角色A的面孔、发型、体型 → 全片` |
| 身份属性散落在提示词各处 | 合并为一个锚定块，集中放在人物段落 |
| 视频/创意迁移参考污染了人物外貌 | 显式排除：`不要迁移@视频1中的人物外貌` |
| 长片提示词没在幕边界重述不变量 | 每一幕开头重述角色身份，而不是只写在圣经抬头 |
| 缺少可锁定的独特标记 | 补 2–3 个跨镜身份锚点（疤、配饰、纹身、服装细节）并写入圣经 |

**替代路线**：使用关键帧优先两阶段契约——先用 T2I 定帧锁定身份，再把它作为 `@图片1` 做 I2V，显著降低漂移。

兜底修复（生成无法满足时）：换脸（face swap）用统一参考脸覆盖漂移帧；局部重绘（inpaint）仅重绘漂移的五官区域；肤色/发色偏移用调色统一校正。

---

## 4. 场景一致性锁

### 4.1 场景圣经的继承规则（写法与样例见 blocking-lighting.md）

场景圣经的**六要素写法、填空模板与权威样例**（夜晚高层公寓客厅中英双语版、带光源清单的精简版、最小可复制成品）见 [blocking-lighting.md](blocking-lighting.md) §3.2–3.3，本文件不重复。

本文件只管一件事：**这场戏的场景圣经一旦定稿，后续每一镜怎么继承。**

- **逐字复用，不得转述。** 场景圣经整段（或其精简版）以原文粘进每一镜的场景部分；改写一次措辞，模型就可能重排家具。
- **只允许收窄，不允许新增。** 后续镜头可以只写场景圣经里已有元素的一部分（近景不必写背景霓虹），但不得引入圣经里没有的物体、光源或出入口。
- **变更必须记录原因并起新版本。** 搬家、破坏、装修、时间流逝导致场景改变时，写成 `scene_001 → scene_001_b` 的新场景 ID，并在分镜表里标出从哪一镜起生效；禁止在同一 ID 下悄悄改描述。
- **光源方向与时间状态跟着场景走，不跟着镜头走。** 换景别、换机位都不改主光方向和色温（见 §6 时间与光线连续性）。

### 4.2 场景设计文档（Scene Sheet，工程化归档格式）

```markdown
## 场景：女主公寓客厅

### 空间布局
- 面积: 约30平米
- 沙发: 灰色布艺三人沙发，靠右墙
- 茶几: 白色大理石圆形茶几，沙发正前方
- 窗户: 右墙落地窗，白色纱帘
- 门: 左侧墙面，白色木门

### 光线设定
- 白天: 自然光从右侧落地窗射入，暖色调
- 夜晚: 沙发上方暖色吊灯 + 窗边落地灯

### AI生成提示词（固定部分）
"modern chinese apartment living room, grey fabric sofa on
right wall, white marble round coffee table, floor-to-ceiling
window with white curtain on right, white door on left wall..."
```

> 场景库固定字段：场景名、地点、用途、空间布局、主色调、道具清单、光线、声音环境、可发生事件。同一场景保存多角度参考图；场景变化必须记录原因（搬家、破坏、装修、时间流逝）；场景库必须标明**哪些元素不可变**，并与分镜编号关联。

### 4.3 分镜中的场景字段模板

见 [blocking-lighting.md](blocking-lighting.md) §3.4（场景功能 / 空间布局 / 人物站位 / 光源 / 关键道具 / 背景层次 / 稳定约束七个字段，另附九宫格资产清单的场景条目 YAML），本文件不重复。**这七个字段的取值在整场戏内必须逐镜相同**，只有「人物站位」允许随剧情推进变化，且变化必须在分镜表的「承接上一镜」列里写清楚。

### 4.4 背景稳定：不给 AI 随机发挥的空间

#### 空间锁提示词

```text
Character A remains on screen left, Character B remains on screen right, the table stays between them, preserving left-right relationship and 180-degree rule
```

```text
角色A始终在画面左侧，角色B始终在画面右侧，桌子位于两人中间，保持左右关系和180度轴线
```

#### 场景负面词

中英两串场景稳定性负面词以 [blocking-lighting.md](blocking-lighting.md) §3.9 为准（那一份还带着打戏场次的使用注：写进场景圣经「可破坏清单」的元素不受 `不要家具变化 / 不要道具变化` 管辖，清单以外的一切仍由这两串封死）。**整场戏的每一镜都挂同一串，不要逐镜增删词条**——负面词本身变了，等于换了一次约束条件。

#### 背景漂移的容忍原则

- 背景物品位置漂移（桌上的杯子、墙上的画）优先用**场景参考图强约束** + **ControlNet Depth Map 锁定空间结构**。
- 接受"主要物品一致、细节可忽略"的原则；利用**浅景深虚化背景**，降低观众注意力。
- 新出现的物体必须与场景语义匹配，否则视为随机发挥。

### 4.5 场景锚定与批量生成策略

| 策略 | 概念 | 执行 |
|---|---|---|
| **锚定帧** | 每个场景选定 1 个"锚定帧"作为该场景所有镜头的视觉基准 | ①为每个场景生成 1 张高质量静态图作为锚定帧；②该场景所有视频生成都以此图为参考；③调色时以此图为该场景色彩标准；④出现偏差时以锚定帧为准修正 |
| **场景包批量生成** | 同一场景的所有镜头在同一 session 内连续生成 | 按场景分组而非按剧情顺序生成；同场景镜头用相同 Seed 基数（如 42, 43, 44…）；生成完一个场景再进入下一个 |

优势：模型状态稳定，风格一致性最高；参数上下文连续；便于立即对比检查。

### 4.6 场景地理不变量（写入连续性圣经）

```text
【场景 Bible】
废弃海边车站：候车室在轨道北侧，出口朝东，海在南侧；傍晚逐渐入夜；主光始终来自西侧落日。
```

跟踪五组状态：①身份（脸、发、年龄、体型、声音）；②服装与道具（准确归属、所在手、状态、位置）；③地理（出入口、画面方向、光源、天气）；④故事信息（谁在什么时候知道了什么）；⑤音频状态（音乐母题、环境音、对白语言、静默）。

### 4.7 参数锁（同一场景不换模型、不换参数）

```yaml
固定参数:
  - Seed: 保持同一场景内种子不变或微调（±1-5）
  - CFG Scale: 全片统一（建议7-9）
  - Sampler: 全片统一（如DPM++ 2M Karras）
  - Steps: 全片统一（如30-50步）
  - Model/Checkpoint: 全片统一，不要中途换模型
  - LoRA: 角色LoRA、风格LoRA全片锁定

可变参数:
  - 动作描述
  - 镜头角度
  - 表情细节
```

参考图层级与权重：

```text
第一层：全局风格参考图（1张，锁定整体调性）    风格参考: weight 0.3-0.4
第二层：角色参考图（每个角色1-3张，多角度）    角色参考: weight 0.6-0.8
第三层：场景参考图（每个场景1-2张）            场景参考: weight 0.4-0.6
第四层：上一镜头尾帧（作为当前镜头的衔接参考）  尾帧参考: weight 0.2-0.3
```

### 4.8 轴线锁：跨镜不得翻转左右

180 度轴线的原理图、左右站位锁定语句、防越轴三招（屏幕左右固定锚定 / OTS 定向 / 后期镜像翻转兜底）与允许跳轴的四种情况，见 [blocking-lighting.md](blocking-lighting.md) §2.1–2.4，本文件不重复。

连续性视角只加一条硬规则：**由于每个镜头独立渲染，A 在左、B 在右的屏幕关系必须在整场戏的每一镜里保持不变**——上一镜 A 在左、下一镜突然 A 在右，剪辑时动作方向完全颠倒，是最难在后期救回的连续性事故之一。

- 每一镜的提示词都必须显式带上左右锚定句，**不能只在第一镜写一次**就指望模型记住。
- 若剧情确实需要过轴，必须**演出一个可见的中性角度、角色转身或镜头弧线**（即 blocking-lighting.md §2.4 的四种情况之一），并在分镜表的「承接上一镜」列里写明这一镜是有意换侧，让下一镜知道新的左右基准。
- 越轴镜头在成片终检里按"可后期修"分级处理：位置越轴但动作方向正确的，走水平镜像翻转；动作方向也错的，必须重生成。

---

## 5. 首尾帧衔接：上一镜落幅 = 下一镜起幅

### 5.1 状态字段：把"落幅"写成可复制的一句话

每一镜必须产出四个字段，下一镜逐字继承：

```yaml
start_state: "[画面开始时的准确状态]"
end_state: "[画面结束时的准确状态]"
continuity_in: "[从上一镜承接什么]"
continuity_out: "[向下一镜交付什么]"
```

分镜脚本规范（含首尾状态的完整写法）：

```
镜号: S01-C03
场景: 客厅（同S01-C01场景）
时间: 下午3点（暖色自然光从右侧窗户射入）
角色: 女主（白色连衣裙、长发左分、银色项链）
动作: 从沙发站起，转身面向门口
情绪: 惊讶→紧张
上一镜头结束状态: 女主坐在沙发左侧，面朝右
下一镜头起始状态: 女主站立，面朝门口方向（画面左侧）
摄像机: 中景、平角、固定机位
```

### 5.2 交接状态向量（每个转场点复制一次）

```text
交接状态：角色位于站台右侧、面向左前方、奔跑动量尚未停止；帆布包在左肩；车票仍在右手；雨势增强；镜头正向后移动；音乐在低频持续音上。
```

必含七项：**位置 / 朝向 / 动量 / 道具归属 / 天气或光线 / 镜头运动方向 / 声音状态。**

### 5.3 镜头衔接提示词（六种承接句，直接复制）

#### 直接承接上一镜

```text
continues directly from the final frame of Shot S01, same character positions, same camera axis, same lighting, the character's hand continues the previous motion without interruption
```

```text
直接承接 S01 最后一帧，人物站位不变，镜头轴线不变，光线不变，角色的手部动作从上一镜自然延续，没有中断
```

#### 动作匹配剪辑（match cut）

```text
match cut on the character's hand movement, the hand starts in the exact position where the previous shot ended, same prop in the same hand, action continuity preserved
```

```text
手部动作匹配剪辑，手从上一镜结束时的准确位置继续移动，同一道具仍在同一只手里，保持动作连续
```

#### 视线匹配剪辑（eyeline match）

```text
eyeline match, the character looks toward screen right in the previous shot, the next shot reveals the object located on screen right, preserving spatial direction
```

```text
视线匹配，上一镜角色看向画面右侧，下一镜揭示画面右侧的对象，保持空间方向一致
```

#### 正反打对话连续（shot-reverse-shot）

```text
shot-reverse-shot continuity, keep the 180-degree rule, Character A remains on screen left, Character B remains on screen right, consistent eyelines, no axis flip
```

```text
正反打连续，遵守180度轴线，角色A始终在画面左侧，角色B始终在画面右侧，视线方向一致，不要跳轴
```

#### 情绪递进衔接

```text
emotional continuity from the previous shot, the character remains hurt but restrained, expression changes gradually, no sudden crying, no sudden anger
```

```text
情绪承接上一镜，角色仍然受伤但克制，表情缓慢变化，不要突然大哭，不要突然愤怒
```

#### 时间连续衔接

```text
real-time continuity, no time skip, no sudden change in daylight, no change in weather, no change in room lighting, the moment continues immediately
```

```text
实时连续，没有时间跳跃，日光不突然变化，天气不变，室内灯光不变，事件立即延续
```

> **速度处理不算 time skip。** 升格（慢动作，slow motion）与降格（快切，fast motion）是**时间的表达方式**，不是时间跳跃，与上面这串不冲突，两者可以同时挂。三条限制：
> ① **整镜统一速度，不在单镜内变速**——模型做不了速度渐变，变速在剪辑台做；
> ② 首尾帧状态仍按**原速契约**衔接——落幅写的是动作到位的姿态，与放慢多少倍无关；
> ③ 慢动作只出现在**终结击命中**（0.25x，约 0.5 秒），中间回合保持正常速度或快切，全程慢动作等于没有慢动作。

### 5.4 首尾帧衔接技术流程

```
流程:
1. 生成镜头A的视频
2. 提取镜头A的最后一帧（尾帧）
3. 以尾帧作为镜头B的首帧/参考图
4. 生成镜头B的视频
5. 检查衔接点是否自然
6. 如有跳变，在衔接点添加1-3帧过渡
```

> 首尾帧图片**只用于边界构图**；不要假定它同时定义了中间所有动作。中间动作仍需在提示词里逐段写清。

### 5.5 转场类型与连续性要求

| 类型 | 特点 | 适用 | 连续性要求 | 注意 |
|---|---|---|---|---|
| A 硬切（hard cut） | 直接切换，无过渡 | 同一场景内、对话正反打 | ★★★★★ | 动作必须严格接续，光影不能有任何变化 |
| B 淡入淡出（dissolve/fade） | 渐隐渐显，0.5-2 秒过渡 | 时间流逝、场景转换、情绪过渡 | ★★★☆☆ | 利用过渡遮盖 AI 生成的细微差异 |
| C 运动转场（motion transition） | 利用运动模糊完成衔接 | 快节奏、动作场景 | ★★☆☆☆ | 甩镜头（whip pan）/推拉转场/旋转转场 |
| D 遮挡转场（mask transition） | 前景物体遮挡完成切换 | 同一空间内的视角变化 | ★★☆☆☆ | 人物过镜、门的开合、物品遮挡 |
| E 匹配剪辑（match cut） | 形状/动作/颜色相似性衔接 | 场景跳转、蒙太奇 | ★★★☆☆ | 形式连续替代内容连续 |

#### AI 短剧推荐转场策略

```
同一场景连续动作 → 硬切（需严格一致性控制）
同一场景时间跳跃 → 淡入淡出
不同场景切换     → 遮挡转场/运动转场（隐藏差异）
情绪高潮快切     → 运动转场 + 音效衔接
回忆/闪回       → 调色变化 + 淡入淡出
```

### 5.6 视频延长与无缝转场契约（跨 15s / 30s 上限时使用）

#### 连续延长

延长（续镜）模板正文见 [prompt-contracts.md](prompt-contracts.md) §3.8「视频延长（续镜）」，本文件不重复——**必须连同那里的警告一起读**：编辑 / 延长任务直接用 `@视频N` 指代，不要写「参考 @视频N」，否则会被误判为参考任务。

连续性侧只补一条：延长段的**交接状态必须逐项写全**（角色位置、朝向、动作动量、镜头运动、光线、声音），缺哪一项，模型就在哪一项上重置——最常见的是动作动量丢失，接缝处人物"停一下再重新起步"。

#### 转场延长

```text
参考@视频1，向后延长[N]秒。原视频保持不变。
[转场类型]：镜头A为[源末尾状态/景别]；[遮挡物/相似形/动作/焦点]在连接点保持[位置、尺寸、方向、速度]；过渡到镜头B的[新场景/新景别]。
0-X秒：[建立转场触发]。
X-N秒：[转场后事件]。
要求连接自然，无黑屏、跳帧、闪烁、硬切或主体突变。
```

#### 两段视频无缝衔接

```text
将@视频1和@视频2无缝衔接，不修改两段原视频本身。
连接设计：@视频1尾帧的[锚点]以[方向/速度]运动并[遮挡/填满/变形]画面；过渡为@视频2首帧的[对应锚点]。
在连接点保持锚点的形状、位置、尺寸、运动方向、速度、光线或色彩连续。
情绪从[A]过渡到[B]。生成的桥接段不得出现黑屏、跳帧、硬切、闪烁、文字或主体突变。
```

### 5.7 分段规划：受单镜时长上限约束时的承接设计

| 目标 | 路线 | 理由 |
|---|---|---|
| 精确控制单个连续镜头的开始与结束画面 | 首尾帧模式 | 尾状态是硬性剧情锚点（落座、转身完成、道具到位、门完全关闭） |
| 延续一段值得保留的源片 | 视频延长 | 原片保持不变，提示词只管新增区间 |
| 超出单次生成上限或需要逐段过审 | 分段规划 | **每段都有刻意设计的交接点和独立验收关口** |

- 不要仅仅因为需求超过单镜上限就随意切分；切分点必须落在**可写清交接状态**的动作边界上。

  > **动作戏例外。** 打戏的切分阈值不是模型时长上限，而是**动作崩坏阈值（一个动作节拍 2–4 秒）**——长打戏必须按节拍强制拆成多个短镜分别生成、后期拼接，**禁止一镜到底**：单镜头越长，帧间位移累积越大，中段必崩（人物穿模、兵器变形、脚下滑步）。
  > 但两条约束是**叠加**而非二选一：切分点仍必须落在可写清交接状态的动作边界上（蓄力末 / 命中瞬间 / 落地瞬间），**不能在动作中途一刀切**。既满足节拍时长，又落在可交接的边界上，才是合法切分点。
- 每段结尾必须给出"最后一个稳定画面 + 音频尾巴"，下一段以其为 `continuity_in`。
- 若某段被打回重做，**只重做该段，不破坏已通过镜头的契约**。
- 首尾帧模式的适用前提：合法首帧和尾帧都存在；首尾画面属于同一镜头且场景/角色差异可连续过渡；运行时模型档案确认支持首尾帧。候选模型不兼容时必须**失败关闭**，不能静默丢弃尾帧、参考视频或音频。

### 5.8 单镜完整提示词范例（含全部六锁 + 承接）

```text
Shot S03, continues directly from Shot S02 final frame, same character, same outfit, same hairstyle, same living room, Character A remains on screen left, Character B remains on screen right, the phone remains in Character A's right hand, Character A slowly raises her eyes from the phone toward Character B, her expression changes from suspicion to emotional hurt, close-up shot, slow push-in, same cold blue moonlight from screen right, shallow depth of field, cinematic realism, consistent face, matching action, prop continuity, no jump cut, no axis flip, no sudden pose change, no changing background, no flickering
```

```text
S03，直接承接 S02 最后一帧，同一角色，同一服装，同一发型，同一客厅，角色A仍在画面左侧，角色B仍在画面右侧，手机仍在角色A右手中，角色A从手机缓慢抬眼看向角色B，表情从怀疑过渡到被刺痛，近景慢推，右侧冷蓝月光不变，浅景深，电影感写实，保持同一张脸，动作连续，道具连续，不要跳切，不要跳轴，不要突然换姿势，不要更换背景，不要闪烁
```

### 5.9 单镜头结构化提示词模板（平台契约版）

模板正文（15 个契约字段）见 [prompt-contracts.md](prompt-contracts.md) §3.2 A「契约字段版」，本文件不重复。

填这张表时，连续性只盯三行：**首状态**必须与上一镜的尾状态逐字对齐；**尾状态**必须写成下一镜可以直接抄走的一句话（见 §5.1）；**连续性**行必须同时写清承接什么、交付什么，只写一半的镜头等于把接缝留给模型自由发挥。

### 5.10 九宫格每格必填字段（分镜图与视频共用）

```yaml
shot_id: 1
grid_index: 1
characters: ["char_001:base"]
scene: "scene_001"
props: ["prop_phone:right_hand:screen_on"]
effects: ["rain:medium:background"]
shot_size: "中景"
camera_angle: "平视，轴线左侧"
lens_mm: 50
composition: "角色位于画面左三分线，右侧留对白负空间"
camera_movement: "缓慢推近"
camera_reason: "将观众注意力移向人物的细微反应"
subject_action: "人物读完信息后抬眼"
expression: "眉心收紧，嘴唇抿住，呼吸短暂停顿"
start_state: "手机位于右手胸前，视线落在屏幕"
end_state: "手机仍在右手胸前，视线抬向画外右侧"
continuity_in: "承接上一镜手机亮屏和右手位置"
continuity_out: "向下一镜交付画外右侧视线"
storyboard_image: "[独立分镜图]"
```

### 5.11 分镜 → 运镜的一致性契约

不可改变的字段：`shot_id`；角色及五视图/状态引用；场景、道具、特效；景别、机位、焦段、构图、动作轴线和视线；主体动作、表情、灯光；首状态、尾状态、连续性输入/输出；分镜图及参考素材清单。

系统把这些字段规范化为 JSON 并计算 SHA-256 指纹。视频计划必须携带相同 `contract_fingerprint`；任一字段修改后，旧视频计划自动过期并重新生成。

#### 运镜提示词编译模板

编译模板正文见 [prompt-contracts.md](prompt-contracts.md) §3.2 B「运镜编译版」，本文件不重复。

> **不要单独手写视频提示词。** 修改镜头契约后重新计算指纹、重新编译分镜图片提示词和运镜提示词；指纹不一致时禁止生成。

### 5.12 关键帧优先两阶段：把光影锁在 Stage 1

多镜项目要求跨镜视觉一致时，先出 T2I 定帧锁构图/光影/身份，再做 I2V 只注入运动。

#### Stage 2（I2V 运动层）的连续性保护段

```text
【连续性保护】
保持@图片1中的[角色身份/服装/道具/场景地理/光照方向/色调]不变。
不要引入@图片1中不存在的人物、道具或场景元素。
光影不因运镜变化而改变基调——摄影机移动时光源保持空间固定。
```

补充约束：`运镜不改变光源方向或色调基准`。

---

## 6. 分身 / 复制人防治

### 6.1 三层来源：为什么会出现"同款分身"

| 来源 | 表现 | 根因 |
|---|---|---|
| 设定层 | 两个角色长得像，观众分不清 | 角色差异度不足；出现双胞胎、长相接近的角色 |
| 生成层 | 同一画面出现两个同款人、镜像脸、克隆脸、群演复制粘贴 | 五视图/分镜格里出现重复角度、镜像、多人 |
| 参考层 | 参考图里的路人被一起迁移进画面 | 参考绑定没写排除项（`不要迁移图片中的顾客`） |

### 6.2 设定层：角色差异化硬规则

```
AI特别注意:
- 角色外形要有强辨识度（便于AI保持一致性）
- 避免双胞胎、长相接近的角色
- 服装颜色差异要大（AI更容易区分）
- 发型要有标志性特征
```

- AI 短剧角色**不宜超过 4-5 人**（控制一致性成本）；对话密集、场景固定、2-4 人是最稳的配置。
- 主角之间在**发色 / 脸型 / 服装色**上拉开区分度（避免两个角色都是黑长直）。
- 同类角色必须能被区分，避免多个角色视觉太像。

### 6.3 生成层：禁止同款分身条款（写入每条提示词）

#### 五视图设定板（角色卡阶段）

```text
禁止重复角度、镜像脸、多人、额外肢体、手指异常、裁切脚部、坐姿、动态姿势、透视夸张、服装变体、发型变体、场景道具、文字、水印、边框标题和复杂背景。
```

#### 九宫格总提示词（分镜阶段）

模板正文见 [prompt-contracts.md](prompt-contracts.md) §3.8，本文件不重复。其中「所有格严格继承同一角色五视图、场景圣经、道具归属、特效规则、180 度轴线、主光方向和色温」与「禁止…角色换脸、服装漂移、道具换手、左右翻转、光向跳变」两句，正是本章防分身条款在九宫格阶段的落点，**一格都不能漏写**。

#### 单人镜通用负面词（防复制人）

```text
duplicated body, duplicate person, clone face, mirrored face, duplicate angle, extra person, extra limbs, extra fingers, missing fingers, fused fingers, extra hands, random extra faces, ghost people, incomplete body
```

#### 双人 / 多人 / 群演场景负面词

见 [performance-action.md](performance-action.md) 附 §4.4「群演负面提示词」（英文串 + 中文串 + 群演分级与围拢站位模板），本文件不重复。多人镜必挂，且**整场戏逐镜挂同一串**。

#### 中文分身负面约束

```text
不要出现同款分身，不要复制人，不要克隆脸，不要镜像脸，不要重复角度，不要多余人物，不要额外肢体，不要多手指，不要群演复制粘贴，不要表情完全相同的路人，不要肢体穿模融合
```

### 6.4 参考层：防止参考素材把"人"带进来

每个参考资产必须写三段式绑定：**迁移什么 / 作用范围 / 禁止迁移什么。**

```text
@图片1 → 女主身份、发型与服装 → 全片
@图片2 → 咖啡馆空间、色彩和材质 → 全片；不要迁移图片中的顾客
@视频1 → 手部拉花动作力学 → 08–14秒；不要迁移人物外貌和背景
```

- **禁止** `完全参考@视频1` 这类写法——引擎无法判断要的是身份、场景、动作、镜头、节奏还是音轨。
- 5 个以上参考仍持续污染时，精简到 2–3 个核心参考，其余用文字描述。
- 身份冲突时显式声明优先级：`身份优先级：@图片1的面孔和发型最高；@图片2只参考夹克版型；@图片3只参考银色徽章，不参考人物。`
- 稳定区间：视频/音频中可辨识主体 1–5 个最稳（6–10 需更多次尝试）；图片中可辨识主体 1–8 个最稳（9–12 需更多次尝试）。**主体超过 5 个时，把多角度拆成多张单视图图片，而不是一张密集拼图。**

---

## 7. 一致性自检清单（发出分镜前必须逐项通过）

### 7.1 A 级门禁：连贯性检查清单（生成前）

- [ ] 是否写了角色圣经，并在每个镜头复用固定外貌句？
- [ ] 是否写了场景圣经，并固定家具、道具、光源方向？
- [ ] 每个镜头是否都有“承接上一镜”字段？
- [ ] 每个镜头是否只推进一个动作？
- [ ] 情绪是否按阶段递进，而不是突然变化？
- [ ] 正反打是否保持 180 度轴线和左右关系？
- [ ] 道具是否始终在同一位置或同一只手里？
- [ ] 光影、时间、天气是否没有突然变化？
- [ ] 负面词是否包含 `no jump cut / no axis flip / no sudden pose change`？

### 7.2 Prompt 一致性清单（每条提示词发出前）

```
□ 风格关键词与上一镜头完全相同
□ 角色描述词与角色设计文档一致
□ 场景描述词与场景设计文档一致
□ 光线描述与当前时间段设定一致
□ 附加了角色参考图（Reference Image）
□ 附加了场景参考图
□ 指定了相同的种子（Seed）或风格引导
```

### 7.3 角色锁自检（逐镜头）

```
□ 五官比例与参考图一致（重点：眼距、鼻型、唇形）
□ 瞳色/肤色无偏移
□ 发型长度/分缝一致
□ 标志特征（痣/疤）位置正确
□ 服装颜色/款式连续
□ 体型比例一致（无忽胖忽瘦）
□ 2-3 个跨镜身份锚点在本镜可见
□ 多人镜中每个角色使用独立 character_id 与明确左右站位
```

### 7.4 镜头连续性检查（与上一镜逐项对比）

```markdown
## 镜头连续性检查 - 镜号: ____

### 与上一镜头对比
- [ ] 角色面部一致
- [ ] 角色服装一致（颜色、款式、配饰）
- [ ] 角色姿态/位置自然接续
- [ ] 场景布局一致（家具、物品位置）
- [ ] 光线方向一致
- [ ] 光线强度/色温一致
- [ ] 色调/整体氛围一致
- [ ] 动作方向连续（左右不跳轴）
- [ ] 画面风格/质感一致

### 本镜头自身
- [ ] 无AI伪影（多余肢体、融合错误）
- [ ] 运动自然流畅
- [ ] 无帧间闪烁
- [ ] 构图符合镜头设计

### 衔接处理
- [ ] 确定转场类型: ________
- [ ] 尾帧已保存供下一镜头参考: □是 □否
- [ ] 需要后期修复: □否 □是（记录: ________）
```

### 7.5 契约与资产交付检查

- [ ] 每个角色有独立五视图，且顺序严格正确；
- [ ] 五视图为横向五等宽栏、完整全身、同焦段、同高度、同光线、同背景；
- [ ] 每个故事板恰好为 3×3 九宫格；
- [ ] 每格包含角色、场景、道具、特效和完整镜头字段；
- [ ] 分镜图提示词和运镜提示词来自同一契约；
- [ ] 分镜计划与视频计划的 `contract_fingerprint` 一致；
- [ ] 自动模式选择有可读理由，模型能力不匹配时明确降级或阻断；
- [ ] 未支持的参考素材不会被静默忽略。

### 7.6 场景锁自检

见 [blocking-lighting.md](blocking-lighting.md) §3.11 场景设计检查清单（8 条，比本文件旧版多一条「这场景是否承担明确剧情功能」），本文件不重复。清单最后一条「是否能支持后续镜头连续生成」就是本文件的验收口：**过不了这一条，后面每一镜的承接都白写。**

### 7.7 成片终检（合成后）

```
□ 全片角色面部无突变
□ 全片色调连贯无突变
□ 全片光影方向一致（同一场景）
□ 镜头衔接处无明显跳帧
□ 动作方向连续（180度法则）
□ 环境音无突然中断
□ 背景音乐连贯
□ 字幕/UI元素统一
□ 无AI伪影（多余手指、变形等）
□ 整体节奏感流畅
```

### 7.8 问题分级与处置

| 级别 | 定义 | 典型问题 | 处置 |
|---|---|---|---|
| **S** | 必须重做 | 主角身份严重漂移观众无法识别；主因果断裂；合规/版权风险；音画严重不同步 | 重做该镜/该段 |
| **A** | 必须修复 | 关键角色服装、道具、伤口、关系明显不连续；关键镜头脸崩、手崩、背景融化 | 重新生成对应镜头 |
| **B** | 建议修复 | 局部光线、色彩、音量轻微波动；个别道具位置轻微不连续但不影响理解 | 后期修复 |
| **C** | 可记录后优化 | 轻微噪点；非关键背景细节变化；局部构图可更美观 | 记录，不阻断发布 |

粗剪阶段的三级分类同源：**A 级问题（必须重新生成）**：角色面部变化、场景完全不同；**B 级问题（可后期修复）**：轻微色差、小物件变化；**C 级问题（用转场遮盖）**：角度跳变、背景细节差异。

发布阈值：S 级必须为 0；A 级必须全部修复；B 级建议不超过 3 个且不得集中在同一关键场景。

### 7.9 从 AI 生成角度的终审六问

- 同一个角色是否跨镜头稳定？
- 同一个场景是否跨镜头稳定？
- 关键道具是否跨镜头稳定？
- 画面中是否有手、脸、文字、空间结构错误？
- 视频是否有漂移、融化、闪烁、跳帧？
- 多模型输出是否仍像同一个项目？

---

## 8. 连续性故障排查速查表

| 症状 | 根因 | 修法 |
|---|---|---|
| 角色面部不一致 | 每镜重新文生 | 角色 LoRA 权重 0.8+；IP-Adapter Face 模式；FaceFusion/Roop 统一面部；改用首帧参考 |
| 服装/配饰变化 | 服装只写了品类词 | 拆成版型/层次/颜色/材质/纹样/鞋子/磨损，绑定 `state_id`；ControlNet Depth/Pose 约束轮廓；局部重绘修正 |
| 发型漂移 | 未写发际线与分缝 | 明确发际线、分缝、刘海、长度、卷度、发色、头饰位置，五视图逐项核对 |
| 背景物品位置漂移 | 无场景参考图 | 场景参考图强约束 + ControlNet Depth Map；浅景深虚化背景 |
| 光影方向矛盾 | 光影参数写进了运动层 | 光影集中写在关键帧（T2I）阶段，运镜阶段不重写；圣经写死 `主光始终来自画面左上方30°、色温5600K暖白`；加 `运镜不改变光源方向或色调基准`；同场景集中在一个 batch 生成 |
| 动作不接续 | 未记录首尾状态 | 尾帧接首帧法；分镜脚本记录每镜首尾动作状态；补 2-4 帧动作补间；运动转场遮盖 |
| 画面闪烁/风格跳变 | 帧间时间一致性差 | Temporal Consistency 设置；Deflicker 后期去闪烁；统一滤镜/胶片颗粒遮盖；适度降低 CFG Scale |
| 镜头指令失效 | 指令埋太深或与空间冲突 | 把运镜指令放在概述之后或每个时间片开头；确认镜头路径在描述空间中物理可行 |
| 循环 / 静止 | 描述的是静态而非过程 | 保证每个节拍首尾帧有变化；把动作写成过程；长停顿补微动作（呼吸、眨眼、发丝、环境运动） |
| 时间线压缩 | 事件塞太多 | 按时间预算分配；每 5 秒窗口不超过 2-3 个动作；关键情绪转折留 3-5 秒 |
| 参考素材污染 | 绑定缺排除项 | 每个参考写"迁移什么/范围/禁止迁移什么"；冲突时声明优先级 |
| 运镜和分镜不一致 | 单独手写了视频提示词 | 修改镜头契约后重新计算指纹、重新编译两套提示词；指纹不一致禁止生成 |

> 诊断纪律：**先定位失败维度，再改那一处**；不要一次改整条提示词，一次迭代只测一个修法；同一修法两次迭代仍无效则换路线。

### 8.1 视觉胶水：用统一视觉层盖住残余差异

在最终合成时添加统一的视觉层，让不同 AI 生成的素材看起来像出自同一台相机：

- 全片一致的 Film Grain（胶片颗粒）
- 统一的暗角（Vignette）
- 轻微的 Bloom/Glow 效果
- 统一的锐化/柔化程度
- 一致的 Letterbox（黑边）

---

## 9. 负面提示词总表（连续性专用）

### 英文

```text
jump cut, time skip, sudden pose change, teleporting, changing background, changing outfit, changing hairstyle, changing face, inconsistent lighting, inconsistent shadows, axis flip, broken eyeline, disappearing prop, duplicated prop, mismatched action, abrupt emotion change, random camera angle, spatial discontinuity, flickering, scene reset
```

### 中文

```text
不要跳切，不要时间跳跃，不要突然换姿势，不要瞬移，不要更换背景，不要换衣服，不要换发型，不要换脸，不要光线突变，不要阴影突变，不要跳轴，不要视线错位，不要道具消失，不要道具重复，不要动作接不上，不要情绪突变，不要随机换角度，不要空间断裂，不要闪烁，不要场景重置
```

### 表情/身份补充负面词

```text
bad anatomy, distorted face, asymmetrical eyes, crossed eyes, extra teeth, deformed mouth, frozen face, plastic skin, uncanny smile, exaggerated expression, flickering, changing face, changing hairstyle, changing outfit, extra fingers, extra hands, blurred facial features
```

---

## 10. 最小可复制成品（整段连续分镜一次性下发）

```text
Create a 5-shot continuous AI short drama sequence. Every shot continues directly from the final frame of the previous shot. Keep the same character face, hairstyle, outfit, location, lighting, screen direction, and prop positions. Each shot advances only one small action and one emotional beat. Preserve the 180-degree rule. Use matching action, eyeline match, and gradual emotional continuity. No jump cuts, no time skips, no sudden pose changes, no teleporting, no changing background, no changing outfit, no changing face, no axis flip, no disappearing props.
```

```text
生成一个 5 镜头连续 AI 短剧分镜。每个镜头必须直接承接上一镜最后一帧。保持同一人物脸型、发型、服装、场景、光线、画面方向和道具位置。每个镜头只推进一个小动作和一个情绪节拍。遵守180度轴线。使用动作匹配、视线匹配和渐进式情绪连续。不要跳切，不要时间跳跃，不要突然换姿势，不要瞬移，不要更换背景，不要换服装，不要换脸，不要跳轴，不要道具消失。
```

---

## 11. 完整工作流（一致性锁的执行顺序）

1. 为每个角色/角色状态生成严格五视图；
2. 五视图质检并生成角色锁定卡；
3. 建立场景、道具和特效资产卡（场景圣经 / 道具库 / 情绪曲线）；
4. 生成恰好九格的 3×3 分镜契约，逐格填 `start_state / end_state / continuity_in / continuity_out`；
5. 从契约生成九宫格总图及九张独立分镜图；
6. 计算每个镜头的契约指纹；
7. 从同一契约编译运镜提示词；
8. 自动判断首尾帧、多图/宫格、多模态或首帧模式；
9. 与运行时模型能力协商，记录供应商、模式、理由和降级链；
10. 指纹一致后生成视频，质检角色、场景、道具、特效、动作、轴线和首尾状态；
11. 不合格镜头只重做对应镜头，不破坏已通过镜头的契约；
12. 配音、音效与 BGM 合成后输出成片和完整溯源记录。