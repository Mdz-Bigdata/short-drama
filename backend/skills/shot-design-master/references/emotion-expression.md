# AI 短剧情绪与面部表情提示词库

> 核心原则：不要只写“悲伤、愤怒、害怕、感动”。AI 更容易执行可观察的面部肌肉、眼神、呼吸、肢体、镜头和光影描述。

## 1. 通用提示词公式

### 中文公式

```text
[景别/镜头] + [人物身份与外观一致性] + [情绪阶段] + [面部表情细节] + [眼神] + [嘴部/下颌] + [身体反应] + [动作节奏] + [光影氛围] + [稳定性约束]
```

### 英文公式

```text
[shot type and camera movement], [character identity and consistent appearance], [emotional state], [specific facial muscles], [eye expression], [mouth and jaw details], [body reaction], [slow subtle motion], [lighting and mood], [stability constraints]
```

### 通用稳定性约束

```text
consistent face, natural facial anatomy, subtle micro expressions, realistic eyes, fluid motion, no flickering, no face distortion, no extra teeth, no deformed mouth, no unnatural smile, no crossed eyes, no changing hairstyle, no changing outfit
```

## 2. 情绪提示词总表

| 情绪 | 面部表情提示词 | 眼神提示词 | 身体反应提示词 | 适合镜头 |
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

## 3. 微表情细节词库

### 眉毛

```text
眉心轻轻收紧、眉毛内侧上扬、单侧眉峰微挑、眉头压低、眉尾下垂、眉毛短暂抽动、眉间出现细纹
```

### 眼睛

```text
眼眶泛红、眼睫轻颤、泪水在眼眶打转、视线下垂、眼神躲闪、瞳孔放大、眼神失焦、眼睛微眯、直视不眨眼、笑意不达眼底
```

### 嘴部

```text
嘴唇抿成一条线、嘴角轻微抽动、嘴角下压、嘴唇微张、牙关紧咬、下唇轻颤、吞咽动作、假笑僵住、笑容慢慢消失
```

### 下颌与脸部肌肉

```text
下颌绷紧、脸颊肌肉僵住、鼻翼微微颤动、脸部血色褪去、太阳穴轻微跳动、喉结滚动、面部肌肉短暂停顿
```

### 肢体反应

```text
指节发白、手指攥紧衣角、肩膀微微发抖、身体僵住、后退半步、胸口起伏、呼吸变浅、背脊挺直、手指轻敲桌面、身体慢慢垮下
```

## 4. 情绪递进模板

### 从平静到崩溃

```text
近景，角色原本保持平静，眉心逐渐收紧，眼眶慢慢泛红，嘴唇抿紧后轻轻颤抖，一滴眼泪滑落，肩膀微微发抖，动作缓慢克制，柔和侧光，浅景深，consistent face, subtle micro expressions, no flickering
```

```text
close-up shot, the character tries to stay calm, brows slowly tightening, eyes gradually turning red, lips pressed together then trembling slightly, one tear rolling down the cheek, shoulders shaking subtly, slow restrained motion, soft side lighting, shallow depth of field, consistent face, subtle micro expressions, no flickering
```

### 从隐忍到愤怒爆发

```text
中近景慢推，角色沉默盯着对方，眉头压低，下颌逐渐绷紧，鼻翼扩张，手指慢慢攥成拳，眼神从克制变得锋利，冷色硬光，低压氛围，consistent face, natural expression, fluid motion
```

```text
medium close-up slow push-in, the character silently stares at the other person, brows lowering, jaw gradually tightening, nostrils flaring, fingers slowly clenching into a fist, eyes shifting from restraint to sharp anger, cold hard lighting, tense atmosphere, consistent face, natural expression, fluid motion
```

### 从心动到克制

```text
柔光近景，角色短暂抬眼看向对方，眼神变得柔软，嘴角几乎要笑又压下，眼睫轻颤，手指停顿在杯沿，随后轻轻移开视线，温暖逆光，浅景深，consistent face, delicate micro expression
```

```text
soft close-up shot, the character briefly looks at the other person, eyes softening, the corners of the mouth almost smiling but held back, eyelashes trembling slightly, fingers pausing on the cup rim, then gently looking away, warm backlight, shallow depth of field, consistent face, delicate micro expression
```

### 从震惊到麻木

```text
静止近景，角色听到真相后嘴唇微张，眼神定住，脸部肌肉僵住，几秒后眼神慢慢失焦，肩膀无力下垂，背景虚化，冷灰色调，no exaggerated expression, realistic face, no flickering
```

```text
static close-up shot, after hearing the truth, the character's lips part slightly, eyes freeze, facial muscles become still, after a few seconds the gaze slowly loses focus, shoulders dropping weakly, blurred background, cold gray tone, no exaggerated expression, realistic face, no flickering
```

## 5. 按短剧类型分类

### 霸总虐恋

```text
克制愤怒、强忍心痛、眼眶泛红但不落泪、下颌绷紧、冷漠表情下藏着痛苦、低声压抑、慢推近景、冷色办公室灯光
```

### 复仇爽剧

```text
冷笑、眼神锐利、嘴角极轻微上扬、压迫感直视、身体静止不动、低角度特写、硬光阴影、黑金色调
```

### 家庭伦理

```text
失望、委屈、欲言又止、嘴唇颤抖、眼眶湿润、手指攥紧围裙或衣角、暖色室内光、生活化中近景
```

### 悬疑反转

```text
警觉、怀疑、眼睛微眯、视线扫过线索、呼吸变轻、身体僵住、前景遮挡、低照度、冷绿色调、缓慢横移镜头
```

### 校园暗恋

```text
偷看、慌忙移开视线、脸颊微红、嘴角压不住的笑、手指无意识摩擦书角、阳光逆光、柔焦近景
```

### 古装权谋

```text
隐忍、克制、礼貌假笑、眼神冷淡、袖中手指攥紧、微微低头但目光上挑、烛光、屏风前景、对称构图
```

## 6. 镜头与表情搭配

| 镜头 | 适合表现 | 提示词重点 |
|---|---|---|
| 大特写 | 眼泪、嘴唇颤抖、瞳孔变化 | eye detail, trembling lips, skin texture |
| 侧脸近景 | 隐忍、孤独、心碎 | side profile, red eyes, restrained tears |
| 过肩镜头 | 对峙、心虚、关系拉扯 | over-the-shoulder, avoiding eye contact |
| 低角度近景 | 压迫、威胁、反击 | low angle, sharp gaze, tense jaw |
| 慢推近景 | 情绪升级、真相揭开 | slow push-in, gradual expression change |
| 慢拉远 | 失落、绝望、被抛弃 | slow pull-back, small lonely figure |
| 手部特写 | 克制、紧张、嫉妒 | clenched fingers, trembling hand, white knuckles |
| 前景遮挡 | 悬疑、窥视、隐秘情绪 | foreground obstruction, hidden expression |

## 7. 可复制完整模板

### 单人情绪特写模板

```text
close-up shot, slow push-in, [角色外貌一致性描述], [情绪状态], brows [眉毛细节], eyes [眼神细节], lips [嘴部细节], jaw [下颌细节], shoulders [身体反应], slow subtle motion, cinematic lighting, shallow depth of field, photorealistic, consistent face, natural facial anatomy, no flickering, no face distortion
```

### 双人对峙模板

```text
medium close-up, over-the-shoulder composition, [角色A] facing [角色B], tense silence, [角色A表情细节], avoiding or holding eye contact, fingers slowly clenching, cold side lighting, shallow depth of field, cinematic drama, consistent face, no extra hands, no distorted faces, no flickering
```

### 哭戏模板

```text
extreme close-up, the character tries not to cry, inner brows raised and pulled together, red watery eyes, lower lip trembling, lips pressed tightly, one tear slowly rolling down the cheek, shoulders shaking slightly, soft side light, quiet emotional atmosphere, realistic skin texture, consistent face, no exaggerated crying, no distorted mouth
```

### 愤怒模板

```text
low-angle close-up, slow push-in, the character suppresses anger, brows pressed down, eyes locked onto the opponent, jaw clenched, nostrils slightly flaring, white knuckles, heavy breathing, hard cold lighting, tense cinematic mood, consistent face, natural expression, no flickering
```

### 心动模板

```text
soft close-up, warm backlight, the character briefly glances at the other person, eyes softening, subtle smile almost appearing then held back, eyelashes trembling, cheeks slightly flushed, fingers pausing gently, shallow depth of field, romantic cinematic tone, consistent face, delicate micro expressions
```

### 黑化模板

```text
close-up shot, low-key lighting, the character's expression slowly turns cold, relaxed face with a faint controlled smile, eyes becoming sharp and unreadable, chin slightly lowered, body completely still, dark cinematic shadows, high contrast, consistent face, no exaggerated evil smile, no flickering
```

## 8. 负面提示词

### 通用负面词

```text
bad anatomy, distorted face, asymmetrical eyes, crossed eyes, extra teeth, deformed mouth, frozen face, plastic skin, uncanny smile, exaggerated expression, flickering, changing face, changing hairstyle, changing outfit, extra fingers, extra hands, blurred facial features
```

### 中文负面约束

```text
不要夸张表情，不要脸部变形，不要眼睛错位，不要牙齿异常，不要嘴巴畸形，不要假笑感，不要表情僵硬，不要换脸，不要换发型，不要换服装，不要闪烁，不要多手指
```

## 9. 常见问题修正

| 问题 | 修正方法 |
|---|---|
| 角色没情绪 | 把“悲伤/愤怒”改成眉、眼、嘴、下颌、手指、呼吸的细节 |
| 表情太夸张 | 加 `subtle micro expressions, restrained emotion, no exaggerated expression` |
| 哭戏假 | 写“一滴眼泪、眼眶泛红、下唇颤抖”，不要写“大哭” |
| 笑容假 | 区分“眼周参与的真笑”和“眼周无变化的假笑” |
| 脸变形 | 加 `natural facial anatomy, realistic eyes, no face distortion` |
| 镜头总是中景 | 把 `extreme close-up / close-up / low-angle` 放在提示词开头 |
| 情绪不连贯 | 每个镜头只推进一个情绪阶段，不要一条提示词写完整情绪转折 |

## 10. 最小可用提示词

```text
close-up shot, slow push-in, consistent character face, restrained sadness, brows gently pulled together, red watery eyes, lips pressed into a thin line, lower lip trembling slightly, shoulders stiff, soft side lighting, shallow depth of field, cinematic realism, subtle micro expressions, no exaggerated expression, no flickering, no face distortion
```

```text
近景慢推，角色强忍难过，眉心轻轻收紧，眼眶泛红，嘴唇抿成一条线，下唇轻微颤抖，肩膀僵住，柔和侧光，浅景深，电影感写实，细腻微表情，不要夸张表情，不要脸部变形，不要闪烁
```
