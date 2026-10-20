# AI 短剧情节与镜头连贯性提示词文档

> 目标：减少 AI 短剧常见的剧情跳跃、人物忽然换位、情绪断层、镜头轴线混乱、道具消失、时间不连续、上一镜动作接不上下一镜的问题。

核心方法：**先写连续性圣经，再写分镜表；每个镜头都继承上一镜的状态；每条提示词只推进一个小动作；用可观察的物理连续代替抽象剧情描述。**

## 1. 连贯性的六个锚点

AI 短剧想不跳跃，每个镜头都要锁住六类信息。

| 锚点 | 要锁定什么 | 常用提示词 |
|---|---|---|
| 人物连续 | 同一张脸、同一发型、同一服装、同一站位 | `same character, consistent face, same outfit, same hairstyle` |
| 空间连续 | 角色在房间里的方向、距离、左右关系 | `same location, same room layout, screen direction preserved` |
| 动作连续 | 下一镜从上一镜动作结束处接上 | `continues from previous shot, matching action, action continuity` |
| 情绪连续 | 情绪逐步变化，不突然换情绪 | `gradual emotional transition, same emotional state carried over` |
| 道具连续 | 手机、杯子、信、刀、包的位置不变 | `same prop in the same hand, prop continuity` |
| 光影连续 | 同一场戏保持同一光源方向和色温 | `same lighting direction, consistent color tone, same time of day` |

## 2. 通用连续性提示词公式

### 中文公式

```text
[镜头编号] + [承接上一镜状态] + [同一人物与服装] + [同一空间与站位] + [上一镜动作的延续] + [本镜只推进一个小动作] + [情绪连续] + [光影连续] + [镜头运动] + [稳定性约束]
```

### 英文公式

```text
[shot number], continues directly from the previous shot, same character with consistent face and outfit, same location and screen direction, matching action from the last frame, only one small action progresses in this shot, gradual emotional continuity, same lighting and color tone, [camera movement], continuity constraints
```

### 最小可用英文连续性句

```text
continues directly from the previous shot, matching the last frame, same character, same outfit, same hairstyle, same location, same screen direction, same prop position, gradual emotional continuity, no jump cut, no sudden pose change, no teleporting, no changing background
```

### 最小可用中文连续性句

```text
直接承接上一镜最后一帧，同一人物，同一服装，同一发型，同一场景，同一站位，同一道具位置，动作从上一镜自然延续，情绪缓慢递进，不要跳切，不要突然换姿势，不要瞬移，不要更换背景
```

## 3. 先写“连续性圣经”

生成任何镜头前，先固定全剧或单场戏的基础设定。后续每条提示词都复制这些固定句。

### 人物圣经模板

```text
角色A：28岁女性，椭圆脸，黑色长直发，低马尾，白色针织衫，浅蓝牛仔裤，左手戴银色戒指，妆容自然，疲惫但克制的眼神。全场保持同一张脸、同一发型、同一服装、同一饰品。
```

```text
Character A: a 28-year-old woman, oval face, long straight black hair tied in a low ponytail, white knit sweater, light blue jeans, silver ring on her left hand, natural makeup, tired but restrained eyes. Keep the same face, hairstyle, outfit, and accessories throughout the entire scene.
```

### 场景圣经模板

```text
场景：夜晚的客厅，沙发在画面左侧，落地窗在画面右侧，茶几在两人中间，手机放在茶几右上角，主光来自右侧窗外冷蓝月光，室内有一盏暖色台灯。全场保持相同空间布局、光源方向、道具位置和时间状态。
```

```text
Location: a living room at night, sofa on the left side of the frame, floor-to-ceiling window on the right, coffee table between the two characters, phone on the upper-right corner of the table, cold blue moonlight from the right window, warm table lamp inside. Keep the same room layout, lighting direction, prop positions, and time of day throughout the scene.
```

### 情绪圣经模板

```text
本场情绪曲线：压抑平静 → 怀疑 → 被刺痛 → 强忍眼泪 → 沉默离开。每个镜头只推进一个情绪阶段，不允许突然大哭、突然愤怒或突然释然。
```

```text
Emotional arc of this scene: restrained calm → suspicion → emotional hurt → holding back tears → silent departure. Each shot advances only one emotional stage. No sudden crying, no sudden rage, no sudden relief.
```

## 4. 分镜连续表模板

生成短剧前，先让模型按这个表输出，再逐镜生成。

| 镜号 | 时间 | 承接上一镜 | 人物站位 | 动作连续 | 情绪阶段 | 道具状态 | 镜头 | 提示词重点 |
|---|---|---|---|---|---|---|---|---|
| S01 | 0-3s | 开场建立 | A在左，B在右 | 两人静止 | 压抑平静 | 手机在茶几右上角 | 全景静止 | 固定空间和人物关系 |
| S02 | 3-6s | 接S01两人站位 | A仍在左侧 | A低头看手机 | 怀疑 | A右手靠近手机 | 中景慢推 | 动作只推进到低头 |
| S03 | 6-9s | 接S02低头状态 | A靠近茶几 | A拿起手机 | 被刺痛 | 手机在A右手 | 手部特写 | 道具连续 |
| S04 | 9-12s | 接S03手机在手 | A抬头看B | A眼眶泛红 | 强忍眼泪 | 手机仍在右手 | 近景慢推 | 情绪递进 |
| S05 | 12-15s | 接S04强忍状态 | A转身离开 | A缓慢转身 | 沉默离开 | 手机垂在右手 | 慢拉远 | 空间与动作收束 |

## 5. 镜头衔接提示词

### 直接承接上一镜

```text
continues directly from the final frame of Shot S01, same character positions, same camera axis, same lighting, the character's hand continues the previous motion without interruption
```

```text
直接承接 S01 最后一帧，人物站位不变，镜头轴线不变，光线不变，角色的手部动作从上一镜自然延续，没有中断
```

### 动作匹配剪辑

```text
match cut on the character's hand movement, the hand starts in the exact position where the previous shot ended, same prop in the same hand, action continuity preserved
```

```text
手部动作匹配剪辑，手从上一镜结束时的准确位置继续移动，同一道具仍在同一只手里，保持动作连续
```

### 视线匹配剪辑

```text
eyeline match, the character looks toward screen right in the previous shot, the next shot reveals the object located on screen right, preserving spatial direction
```

```text
视线匹配，上一镜角色看向画面右侧，下一镜揭示画面右侧的对象，保持空间方向一致
```

### 正反打对话连续

```text
shot-reverse-shot continuity, keep the 180-degree rule, Character A remains on screen left, Character B remains on screen right, consistent eyelines, no axis flip
```

```text
正反打连续，遵守180度轴线，角色A始终在画面左侧，角色B始终在画面右侧，视线方向一致，不要跳轴
```

### 情绪递进衔接

```text
emotional continuity from the previous shot, the character remains hurt but restrained, expression changes gradually, no sudden crying, no sudden anger
```

```text
情绪承接上一镜，角色仍然受伤但克制，表情缓慢变化，不要突然大哭，不要突然愤怒
```

### 时间连续衔接

```text
real-time continuity, no time skip, no sudden change in daylight, no change in weather, no change in room lighting, the moment continues immediately
```

```text
实时连续，没有时间跳跃， daylight 不突然变化，天气不变，室内灯光不变，事件立即延续
```

## 6. 避免跳跃的分镜写法

### 错误写法

```text
她发现真相后崩溃离开。
```

问题：动作和情绪跨度太大，AI 会跳过中间过程。

### 正确拆分

```text
S01：她低头看到手机上的消息，身体僵住。
S02：她缓慢抬眼看向对方，眼眶开始泛红。
S03：她嘴唇抿紧，右手攥住手机，呼吸变重。
S04：她没有说话，只是后退半步。
S05：她转身，手机垂在右手，缓慢走出客厅。
```

原则：**发现 → 反应 → 消化 → 决定 → 行动**，每一步单独成镜。

## 7. 连贯性专用约束词库

### 人物一致

```text
same character, consistent face, same facial features, same hairstyle, same outfit, same makeup, same age, same body shape, no face change, no hairstyle change, no outfit change
```

### 空间一致

```text
same location, same room layout, same furniture placement, same background, same screen direction, same left-right relationship, no background change, no teleporting, no spatial jump
```

### 动作一致

```text
matching action, action continuity, starts from the previous pose, continues the previous motion, no sudden pose change, no skipped movement, no abrupt body position change
```

### 道具一致

```text
same prop, prop continuity, same prop position, same object in the same hand, no disappearing prop, no duplicated prop, no changing object
```

### 光影一致

```text
same lighting direction, same color temperature, consistent shadows, same time of day, same weather, consistent exposure, no lighting shift, no color shift
```

### 镜头一致

```text
preserve camera axis, obey the 180-degree rule, consistent eyeline, consistent screen direction, no axis flip, no random camera angle change
```

## 8. 负面提示词

### 英文负面词

```text
jump cut, time skip, sudden pose change, teleporting, changing background, changing outfit, changing hairstyle, changing face, inconsistent lighting, inconsistent shadows, axis flip, broken eyeline, disappearing prop, duplicated prop, mismatched action, abrupt emotion change, random camera angle, spatial discontinuity, flickering, scene reset
```

### 中文负面词

```text
不要跳切，不要时间跳跃，不要突然换姿势，不要瞬移，不要更换背景，不要换衣服，不要换发型，不要换脸，不要光线突变，不要阴影突变，不要跳轴，不要视线错位，不要道具消失，不要道具重复，不要动作接不上，不要情绪突变，不要随机换角度，不要空间断裂，不要闪烁，不要场景重置
```

## 9. 场景连续性完整模板

### 中文整场生成模板

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

### 英文整场生成模板

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

## 10. 单镜头提示词模板

```text
Shot S03, continues directly from Shot S02 final frame, same character, same outfit, same hairstyle, same living room, Character A remains on screen left, Character B remains on screen right, the phone remains in Character A's right hand, Character A slowly raises her eyes from the phone toward Character B, her expression changes from suspicion to emotional hurt, close-up shot, slow push-in, same cold blue moonlight from screen right, shallow depth of field, cinematic realism, consistent face, matching action, prop continuity, no jump cut, no axis flip, no sudden pose change, no changing background, no flickering
```

```text
S03，直接承接 S02 最后一帧，同一角色，同一服装，同一发型，同一客厅，角色A仍在画面左侧，角色B仍在画面右侧，手机仍在角色A右手中，角色A从手机缓慢抬眼看向角色B，表情从怀疑过渡到被刺痛，近景慢推，右侧冷蓝月光不变，浅景深，电影感写实，保持同一张脸，动作连续，道具连续，不要跳切，不要跳轴，不要突然换姿势，不要更换背景，不要闪烁
```

## 11. 15 秒短剧连续性结构

| 时间 | 功能 | 连续性重点 | 镜头建议 |
|---|---|---|---|
| 0-3s | 建立场景和人物关系 | 锁定空间、人物左右、道具位置 | 全景或中景静止 |
| 3-6s | 触发事件 | 只让一个道具或一个动作启动 | 中景慢推 |
| 6-9s | 角色反应 | 承接上一动作，表情轻微变化 | 近景或手部特写 |
| 9-12s | 情绪升级 | 情绪只上升一级，不直接爆发 | 大特写慢推 |
| 12-15s | 行动或悬念 | 动作从上一镜自然收束 | 慢拉远或背影镜头 |

## 12. 连贯性检查清单

生成前逐项检查：

- [ ] 是否写了角色圣经，并在每个镜头复用固定外貌句？
- [ ] 是否写了场景圣经，并固定家具、道具、光源方向？
- [ ] 每个镜头是否都有“承接上一镜”字段？
- [ ] 每个镜头是否只推进一个动作？
- [ ] 情绪是否按阶段递进，而不是突然变化？
- [ ] 正反打是否保持 180 度轴线和左右关系？
- [ ] 道具是否始终在同一位置或同一只手里？
- [ ] 光影、时间、天气是否没有突然变化？
- [ ] 负面词是否包含 `no jump cut / no axis flip / no sudden pose change`？

## 13. 最小可复制成品

```text
Create a 5-shot continuous AI short drama sequence. Every shot continues directly from the final frame of the previous shot. Keep the same character face, hairstyle, outfit, location, lighting, screen direction, and prop positions. Each shot advances only one small action and one emotional beat. Preserve the 180-degree rule. Use matching action, eyeline match, and gradual emotional continuity. No jump cuts, no time skips, no sudden pose changes, no teleporting, no changing background, no changing outfit, no changing face, no axis flip, no disappearing props.
```

```text
生成一个 5 镜头连续 AI 短剧分镜。每个镜头必须直接承接上一镜最后一帧。保持同一人物脸型、发型、服装、场景、光线、画面方向和道具位置。每个镜头只推进一个小动作和一个情绪节拍。遵守180度轴线。使用动作匹配、视线匹配和渐进式情绪连续。不要跳切，不要时间跳跃，不要突然换姿势，不要瞬移，不要更换背景，不要换服装，不要换脸，不要跳轴，不要道具消失。
```
