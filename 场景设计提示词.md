# AI 短剧场景设计提示词文档

> 目标：让 AI 短剧场景不再像随机背景，而是服务剧情、人物关系、情绪氛围和镜头调度。场景不是“漂亮环境”，而是剧情压力、人物状态和信息揭示的容器。

核心方法：**先定场景功能，再定空间布局；先找光，再定构图；道具要参与叙事；背景要稳定、简洁、有层次。**

## 1. 场景设计四层结构

| 层级 | 作用 | 需要写清楚什么 |
|---|---|---|
| 剧情功能 | 决定这场戏为什么发生在这里 | 告白、对峙、揭露、逃离、崩溃、反转 |
| 空间关系 | 决定人物怎么站、怎么移动 | 左右关系、距离、遮挡、出入口、视线方向 |
| 情绪氛围 | 决定观众感受到什么 | 压迫、孤独、暧昧、危险、温暖、衰败 |
| 视觉细节 | 决定画面是否可信和稳定 | 光源、色温、家具、道具、材质、背景层次 |

## 2. 通用场景设计公式

### 中文公式

```text
[场景类型] + [剧情功能] + [空间布局] + [人物站位] + [关键道具] + [光源方向] + [色调氛围] + [材质细节] + [背景层次] + [镜头景别] + [稳定性约束]
```

### 英文公式

```text
[scene type], [dramatic function], [spatial layout], [character blocking], [key props], [lighting direction], [color mood], [material details], [background depth], [shot type], [stability constraints]
```

### 最小可用模板

```text
cinematic [scene type], designed for [dramatic function], clear spatial layout, main character positioned [screen position], key prop placed [prop position], [lighting direction and color temperature], [emotional atmosphere], layered background, shallow depth of field, consistent location, no background change, no random objects, no cluttered composition
```

```text
电影感[场景类型]，用于表现[剧情功能]，空间布局清晰，主角位于[画面位置]，关键道具放在[道具位置]，[光源方向和色温]，[情绪氛围]，背景有前中后三层，浅景深，保持同一场景，不要更换背景，不要随机增加物体，不要画面杂乱
```

## 3. 场景圣经模板

每场戏生成前，先固定场景圣经。后续所有镜头都继承这段描述。

```text
场景圣经：夜晚的高层公寓客厅，冷色城市灯光从右侧落地窗照入，左侧是深灰色沙发，中间是黑色玻璃茶几，茶几右上角放着一部亮屏手机，背景有虚化的城市霓虹。空间关系固定：女主站在画面左侧靠近沙发，男主站在画面右侧靠近落地窗，两人之间隔着茶几。全场保持同一空间布局、同一家具位置、同一道具位置、同一光源方向、同一夜晚时间。
```

```text
Scene bible: a high-rise apartment living room at night, cold city light entering from the floor-to-ceiling window on screen right, a dark gray sofa on screen left, a black glass coffee table in the center, a lit phone placed on the upper-right corner of the table, blurred city neon in the background. Fixed spatial relationship: the female lead stands on screen left near the sofa, the male lead stands on screen right near the window, with the coffee table between them. Keep the same room layout, furniture placement, prop position, lighting direction, and night-time setting throughout the scene.
```

## 4. 场景功能设计

| 剧情功能 | 场景设计重点 | 推荐场景 | 提示词关键词 |
|---|---|---|---|
| 告白 | 温暖、私密、低干扰 | 天台、车内、夜晚街角、窗边 | warm backlight, intimate space, quiet background |
| 对峙 | 空间距离、压迫线条、冷光 | 办公室、客厅、走廊、审讯室 | symmetrical composition, cold hard light, tense distance |
| 分手 | 空旷、留白、人物疏离 | 雨夜街边、车站、客厅、桥上 | negative space, emotional distance, muted colors |
| 反转 | 信息遮挡、线索道具、阴影 | 书房、储物间、地下车库 | foreground obstruction, hidden clue, low-key lighting |
| 崩溃 | 封闭、压低、无出口感 | 卫生间、卧室角落、电梯 | confined space, close walls, oppressive framing |
| 复仇 | 冷硬、秩序、权力感 | 顶层办公室、酒店走廊、法庭外 | low angle, hard shadows, black gold tone |
| 回忆 | 柔焦、逆光、低对比 | 校园、旧房间、海边、老街 | soft focus, warm haze, nostalgic color |
| 逃离 | 方向明确、动线清楚 | 巷子、楼梯间、停车场 | leading lines, motion direction, handheld camera |

## 5. 空间布局提示词

### 左右关系

```text
Character A remains on screen left, Character B remains on screen right, the table stays between them, preserving left-right relationship and 180-degree rule
```

```text
角色A始终在画面左侧，角色B始终在画面右侧，桌子位于两人中间，保持左右关系和180度轴线
```

### 前中后景

```text
foreground: blurred door frame, middle ground: main character standing near the table, background: soft city lights through the window, layered cinematic depth
```

```text
前景是虚化的门框，中景是主角站在桌边，背景是窗外柔和城市灯光，形成电影感空间层次
```

### 出入口与动线

```text
clear exit door in the background left, character movement direction from screen right to screen left, visible pathway, no blocked movement path
```

```text
背景左侧有清晰出口，角色运动方向从画面右侧到左侧，行动路径可见，不要阻断动线
```

### 压迫构图

```text
narrow hallway, strong vertical lines, low ceiling, character framed tightly between walls, oppressive composition, cold overhead light
```

```text
狭窄走廊，强烈竖线条，低天花板，角色被墙面紧紧夹在中间，压迫式构图，冷色顶光
```

## 6. 光影与色调设计

| 情绪 | 光影设计 | 色调 | 提示词 |
|---|---|---|---|
| 温情 | 柔和侧逆光、暖色台灯 | 暖黄、奶油色 | `warm practical lamp, soft backlight, cozy amber tone` |
| 压迫 | 顶光、硬阴影、低照度 | 冷蓝、灰黑 | `cold overhead light, hard shadows, low-key lighting` |
| 悬疑 | 局部光、前景遮挡、暗部多 | 冷绿、深蓝 | `low-key lighting, foreground shadow, greenish cold tone` |
| 复仇 | 高反差、边缘光、金属反光 | 黑金、冷白 | `high contrast, rim light, black and gold palette` |
| 悲伤 | 侧光、窗光、低饱和 | 灰蓝、雾白 | `soft window light, desaturated blue gray tone` |
| 暧昧 | 暖逆光、浅景深、柔焦 | 粉橙、暖棕 | `warm backlight, shallow depth of field, soft romantic glow` |
| 孤独 | 大面积暗部、远处小光源 | 冷蓝、黑色 | `large negative space, distant small light, lonely blue tone` |

## 7. 道具叙事设计

道具不要只做装饰，要承担剧情信息。

| 道具 | 叙事功能 | 场景提示词 |
|---|---|---|
| 手机 | 消息、背叛、真相 | `lit phone screen on the coffee table, the only bright object in the scene` |
| 戒指 | 婚姻、承诺、背叛 | `silver ring catching a small highlight, placed near the edge of the table` |
| 合同 | 权力、交易、威胁 | `unsigned contract folder on the desk, sharply lit by a cold desk lamp` |
| 旧照片 | 回忆、秘密、亲情 | `old photo partly hidden under a book, warm nostalgic light` |
| 水杯 | 紧张、沉默、破裂 | `half-filled glass cup, slight reflection, placed between two characters` |
| 门 | 逃离、拒绝、边界 | `closed door in the background, clear exit line, symbolic separation` |
| 雨伞 | 分别、保护、疏离 | `black umbrella leaning near the entrance, wet floor reflection` |
| 镜子 | 自我审视、真相分裂 | `mirror reflection showing the character's hidden expression` |

## 8. 常用短剧场景库

### 高层公寓客厅

```text
high-rise apartment living room at night, floor-to-ceiling window on screen right, dark gray sofa on screen left, black glass coffee table in the center, blurred city neon outside, cold blue moonlight from the window, warm table lamp inside, modern but emotionally cold atmosphere, layered background, cinematic realism, consistent room layout
```

适合：分手、对峙、揭穿真相、深夜谈判。

### 总裁办公室

```text
luxury CEO office, large dark wooden desk, city skyline behind the character, leather chair, minimalist black and gold decor, cold directional light, strong vertical lines, low-angle composition, power and pressure atmosphere, clean background, no clutter
```

适合：复仇、谈判、权力压迫、身份揭露。

### 雨夜街边

```text
rainy street at night, wet asphalt reflecting neon lights, bus stop on screen left, empty road stretching into the background, cold blue and magenta reflections, lonely atmosphere, visible rain streaks, shallow depth of field, cinematic melancholy
```

适合：分手、错过、追车失败、孤独离开。

### 老旧出租屋

```text
small old rental room, peeling beige walls, narrow bed on screen left, wooden table near the window, single warm bulb overhead, clutter kept minimal, worn fabric texture, quiet poor but intimate atmosphere, realistic lived-in details
```

适合：底层逆袭、家庭压力、病痛、秘密藏身。

### 医院走廊

```text
quiet hospital corridor at night, pale green walls, fluorescent ceiling lights, empty chairs along the wall, distant nurse station, cold sterile atmosphere, long leading lines, slight echoing emptiness, desaturated color tone
```

适合：生死抉择、亲情崩溃、真相揭露。

### 地下停车场

```text
underground parking garage, concrete pillars, dim fluorescent lights, parked cars in the background, strong shadows, cold greenish tone, wide empty space, suspenseful atmosphere, clear vanishing lines, cinematic thriller style
```

适合：悬疑、绑架、交易、跟踪、反转。

### 校园教室

```text
sunlit classroom in late afternoon, wooden desks in neat rows, chalkboard in the background, warm golden light through the windows, dust particles in the air, nostalgic soft focus, quiet youthful atmosphere
```

适合：暗恋、回忆、青春遗憾、初次心动。

### 古风庭院

```text
ancient Chinese courtyard at dusk, stone path, wooden corridor, paper lanterns, bamboo shadows on the wall, warm candlelight mixed with cool twilight, elegant symmetrical composition, restrained dramatic atmosphere
```

适合：权谋、隐忍告别、身份反转、夜谈。

## 9. 类型化场景组合

### 虐恋分手场景

```text
rainy night outside an apartment building, wet pavement reflecting street lamps, the female lead under a dim warm entrance light, the male lead standing several steps away in colder blue street light, visible emotional distance between them, black umbrella near the edge of the frame, cinematic melancholy, no crowded background
```

### 复仇回归场景

```text
luxury hotel corridor, polished marble floor, black and gold wall panels, strong overhead light forming sharp shadows, the protagonist walking from the dark end of the hallway into the light, symmetrical composition, power and revenge atmosphere, slow tracking shot
```

### 悬疑发现线索场景

```text
dim study room, desk lamp as the only light source, old documents scattered neatly on the desk, one hidden photo half exposed under a book, foreground bookshelf partially blocking the view, low-key lighting, greenish cold tone, tense quiet atmosphere
```

### 家庭崩溃场景

```text
small dining room at night, half-finished dinner on the table, one empty chair, warm overhead light but desaturated colors, family photo on the wall slightly out of focus, the table separating the characters, quiet suffocating atmosphere
```

### 暧昧心动场景

```text
small convenience store at midnight, warm fluorescent light, rain on the glass window, shelves softly blurred in the background, two characters standing close near the counter, intimate quiet atmosphere, soft reflections, shallow depth of field
```

## 10. 分镜中的场景字段模板

| 字段 | 写法 |
|---|---|
| 场景功能 | 这场戏用于“揭穿背叛” |
| 空间布局 | 沙发左、窗户右、茶几中间、门在后方 |
| 人物站位 | A在左，B在右，中间隔着茶几 |
| 光源 | 右侧冷蓝窗光，左后方暖色台灯 |
| 关键道具 | 亮屏手机在茶几右上角 |
| 背景层次 | 前景门框，中景人物，背景城市霓虹 |
| 稳定约束 | 保持同一布局、同一光源、同一道具位置 |

## 11. 场景生成完整模板

### 中文模板

```text
请为 AI 短剧设计一个电影感场景。先说明场景功能，再输出场景圣经和可直接用于图像/视频生成的提示词。

要求：
1. 场景必须服务剧情，不要只是漂亮背景。
2. 写清楚空间布局：左侧、右侧、中间、前景、背景、出入口。
3. 写清楚人物站位和可移动路线。
4. 写清楚关键道具的位置和叙事功能。
5. 写清楚光源方向、色温、阴影和色调。
6. 背景要简洁稳定，不要随机增加杂物。
7. 输出中英文提示词和负面提示词。

剧情功能：[填写]
人物关系：[填写]
情绪氛围：[填写]
短剧类型：[填写]
```

### 英文模板

```text
Design a cinematic scene for an AI short drama. First define the dramatic function, then output a scene bible and direct image/video generation prompts.

Requirements:
1. The scene must serve the story, not just look beautiful.
2. Define the spatial layout clearly: left side, right side, center, foreground, background, entrance and exit.
3. Define character blocking and possible movement paths.
4. Define key prop positions and their narrative function.
5. Define lighting direction, color temperature, shadows, and color mood.
6. Keep the background simple and stable, with no random objects.
7. Output English prompt, Chinese prompt, and negative prompt.

Dramatic function: [insert]
Character relationship: [insert]
Emotional atmosphere: [insert]
Short drama genre: [insert]
```

## 12. 负面提示词

### 英文负面词

```text
random background, cluttered composition, inconsistent room layout, changing furniture, changing props, changing lighting direction, inconsistent color tone, unrealistic scale, messy objects, empty meaningless background, overdecorated set, no spatial depth, confusing layout, no clear entrance, no clear character position, background flickering
```

### 中文负面词

```text
不要随机背景，不要画面杂乱，不要空间布局变化，不要家具变化，不要道具变化，不要光源方向变化，不要色调突变，不要比例失真，不要无意义空背景，不要过度装饰，不要没有空间层次，不要布局混乱，不要缺少出入口，不要人物站位不清，不要背景闪烁
```

## 13. 场景设计检查清单

生成前逐项检查：

- [ ] 这场景是否承担明确剧情功能？
- [ ] 是否写清楚左、右、中、前景、背景？
- [ ] 是否写清楚人物站位和距离？
- [ ] 是否有一个关键道具参与叙事？
- [ ] 光源方向和色温是否明确？
- [ ] 背景是否足够简洁，避免 AI 随机发挥？
- [ ] 是否能支持后续镜头连续生成？
- [ ] 是否加入 `consistent location`、`same room layout`、`no changing background`？

## 14. 最小可复制成品

```text
cinematic high-rise apartment living room at night, designed for an emotional confrontation, floor-to-ceiling window on screen right, dark gray sofa on screen left, black glass coffee table in the center, lit phone on the upper-right corner of the table as the key story prop, female lead on screen left near the sofa, male lead on screen right near the window, cold blue moonlight from the right, warm table lamp behind the sofa, blurred city neon in the background, layered foreground-middle-background depth, tense quiet atmosphere, shallow depth of field, cinematic realism, consistent location, same room layout, same lighting direction, no random objects, no changing background, no cluttered composition
```

```text
电影感夜晚高层公寓客厅，用于表现情感对峙，右侧是落地窗，左侧是深灰色沙发，中间是黑色玻璃茶几，茶几右上角放着亮屏手机作为关键剧情道具，女主站在画面左侧靠近沙发，男主站在画面右侧靠近窗户，右侧冷蓝月光照入，沙发后方有暖色台灯，背景是虚化城市霓虹，形成前中后景层次，安静紧张的氛围，浅景深，电影感写实，保持同一场景，同一空间布局，同一光源方向，不要随机物体，不要更换背景，不要画面杂乱
```
