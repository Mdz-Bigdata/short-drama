# AI影视剧负面提示词

## 说明

这是一份面向 AI 影视剧、短剧、预告片、电影感海报、剧情分镜、角色定妆、文生视频、图生视频场景的详细负面提示词清单。

使用原则：

1. 不要一次性把所有负面词全部堆满，应按场景筛选。
2. 先使用“通用负面提示词”，再叠加“人物”“服装”“镜头”“场景”“视频时序”等模块。
3. 写实影视风格优先压制卡通感、塑料感、低清晰度、结构错误、时序漂移。
4. 若模型支持权重，可将最关键问题加权，例如：`bad hands:1.4`、`deformed face:1.3`。

---

## 一、通用负面提示词

适合所有 AI 影视剧画面、角色海报、剧情镜头、短视频镜头。

```text
worst quality, low quality, normal quality, lowres, blurry, out of focus, soft focus,
pixelated, noisy, grainy, jpeg artifacts, compression artifacts, oversharpen, overprocessed,
overexposed, underexposed, bad lighting, flat lighting, muddy colors, washed out, dull colors,
oversaturated, color banding, chromatic aberration, lens dirt, sensor dust, watermark, logo,
text, subtitles, captions, UI, interface, frame, border, cropped, cut off, bad composition,
off-center composition, empty frame, cluttered background, messy scene, unnatural pose,
deformed, distorted, malformed, disfigured, mutation, broken anatomy, bad anatomy,
extra limbs, extra fingers, missing fingers, fused fingers, missing limbs, disconnected limbs,
long neck, twisted body, broken body, duplicated body, duplicate person, clone face,
unnatural expression, dead eyes, asymmetrical face, bad perspective, warped perspective,
wrong shadows, inconsistent shadows, inconsistent reflections, fake reflections, plastic skin,
waxy skin, uncanny valley, cartoonish, CGI look, game render, 3d render, toy-like, doll-like
```

---

## 二、人物负面提示词

适合角色定妆、人物特写、双人对手戏、群像海报、情绪镜头。

### 1. 面部问题

```text
bad face, deformed face, asymmetrical face, distorted face, melted face, blurry face,
double face, duplicate face, extra face, poorly drawn face, disfigured face,
wrong facial proportions, oversized forehead, tiny chin, warped jaw, crooked mouth,
misaligned eyes, cross-eyed, uneven eyes, lazy eye, dead eyes, empty eyes, glassy eyes,
extra eyes, missing eyebrows, uneven eyebrows, blurry eyelashes, malformed nose,
broken nose, extra nostrils, bad lips, fused lips, uneven teeth, extra teeth, bad ears,
extra ears, missing ears, asymmetrical ears, strange smile, creepy expression
```

### 2. 手部与肢体问题

```text
bad hands, poorly drawn hands, malformed hands, mutated hands, extra fingers,
missing fingers, fused fingers, broken fingers, twisted fingers, giant hands,
tiny hands, extra arms, missing arms, broken arms, dislocated joints,
extra legs, missing legs, twisted legs, broken knees, malformed feet,
extra feet, floating limbs, detached limbs, duplicated limbs
```

### 3. 身体与姿态问题

```text
bad anatomy, bad body proportions, distorted torso, elongated torso, short torso,
long neck, broken spine, twisted waist, unnatural shoulders, uneven shoulders,
hunched posture, stiff pose, awkward pose, impossible pose, mannequin pose,
robotic pose, floating body, duplicated body parts, merged body, malformed silhouette
```

### 4. 皮肤与妆容问题

```text
plastic skin, waxy skin, over-smoothed skin, airbrushed skin, fake pores,
blotchy skin, patchy skin, oversaturated blush, smudged makeup, uneven makeup,
clown makeup, heavy beauty filter, fake eyelashes, strange lipstick edges,
unnatural skin tone, inconsistent skin tone, oily face, burned highlights on skin
```

---

## 三、双人、多人与群演场景负面提示词

适合对话戏、群像戏、宴会、打斗、街景、战场、朝堂、会议室等。

```text
duplicate people, cloned faces, repeated extras, copy-paste crowd, identical expressions,
merged bodies, overlapping bodies, intersecting limbs, missing person parts,
floating heads, broken interactions, incorrect eye lines, looking in wrong direction,
awkward spacing, crowd collision, tangled limbs, fused characters, inconsistent scale,
foreground character blur, background character collapse, malformed background people,
random extra hands, random extra faces, ghost people, transparent body, incomplete body
```

---

## 四、服装、发型、饰品、道具负面提示词

适合古装、现代剧、科幻剧、悬疑剧、都市剧、战争剧等定妆和镜头。

### 1. 服装问题

```text
bad costume, malformed clothing, torn clothing, clipping clothes, fused clothes,
extra sleeves, missing sleeves, asymmetrical clothing, unnatural folds, broken fabric,
plastic fabric, rubber clothing, floating clothes, warped clothes, texture stretching,
wrong period costume, modern clothing in historical scene, inaccurate wardrobe,
inconsistent costume details, changing costume, costume flicker, broken seams,
bad embroidery, fake fabric texture, cheap costume look
```

### 2. 发型问题

```text
bad hair, messy hair, floating hair, hair clipping, hair through face, hair through body,
extra hair strands, melted hair, plastic hair, wig-like hair, broken hairline,
asymmetrical hairstyle, changing hairstyle, hairstyle flicker, unnatural bangs,
hair covering eyes, hair merging with background
```

### 3. 饰品与道具问题

```text
broken accessories, fused jewelry, floating earrings, asymmetrical earrings,
warped crown, broken helmet, malformed glasses, bent glasses, duplicated props,
floating weapon, melted weapon, soft weapon, incorrect grip, impossible prop scale,
wrong prop material, low-detail prop, missing prop parts, prop flicker,
changing prop shape, historical inaccuracy, modern object in ancient scene
```

---

## 五、场景与美术设计负面提示词

适合室内戏、外景戏、古城、宫殿、赛博都市、废土、校园、医院、法庭等。

```text
bad background, blurry background, low-detail environment, empty environment,
flat set design, fake set, cheap set, unfinished background, inconsistent architecture,
warped walls, crooked doors, broken windows, floating furniture, melted objects,
incorrect scale, impossible room layout, perspective distortion, bent horizon,
repeated patterns, tiled textures, artificial plants, fake sky, broken clouds,
unnatural landscape, low-detail cityscape, malformed vehicles, floating buildings,
background artifacts, visual clutter, random objects, modern contamination,
period inaccuracies, style inconsistency, environmental flicker
```

---

## 六、镜头语言与摄影问题负面提示词

适合强调“电影感”“真实摄影机”“专业镜头语言”的场景。

```text
bad cinematography, poor framing, awkward framing, amateur camera,
security camera look, webcam look, phone camera look, surveillance angle,
flat composition, centered subject only, weak depth, no depth separation,
incorrect focus, focus hunting, unstable focus, soft image, accidental blur,
wrong lens distortion, fisheye distortion, stretched edges, bad bokeh,
fake depth of field, inconsistent depth of field, bad rack focus,
shaky camera, random zoom, abrupt zoom, camera jitter, Dutch angle misuse,
unmotivated camera angle, broken shot continuity, inconsistent shot scale,
wrong eyeline match, bad over-the-shoulder composition, poor blocking
```

---

## 七、光影与色彩负面提示词

适合写实电影感、夜戏、霓虹、悬疑、史诗感、情绪戏等。

```text
flat lighting, studio flat light, no contrast, muddy shadows, crushed blacks,
blown highlights, clipped highlights, overexposed face, underexposed face,
inconsistent lighting direction, multiple conflicting light sources, fake rim light,
unnatural skin highlights, green skin cast, magenta cast, cyan cast,
color contamination, random light leaks, fake volumetric light, bad god rays,
overly dramatic bloom, excessive glow, neon spill everywhere, unnatural HDR,
poor color grading, washed out image, desaturated skin, bad white balance,
inconsistent color temperature, flickering light, color shift between frames
```

---

## 八、质感与材质问题负面提示词

适合要求“真实电影摄影质感”“高级商业片质感”“胶片感但不脏”的画面。

```text
plastic texture, wax texture, rubber texture, toy texture, fake metal,
fake leather, fake silk, fake skin, poor fabric simulation, bad material response,
CGI shading, game-engine shading, low-poly look, 3d render feel, synthetic look,
oversmoothed surfaces, fake reflections, incorrect specular highlights,
cheap VFX, compositing artifacts, matte edges, green screen halo,
cutout subject, pasted subject, sticker look, inconsistent film grain,
excessive grain, muddy grain, dirty frame
```

---

## 九、文生视频专用负面提示词

适合 Runway、Kling、Pika、Luma、Sora 类视频模型，以及图生视频。

```text
frame flicker, temporal inconsistency, character drift, identity drift,
face drift, costume drift, hairstyle drift, object drift, background drift,
scene morphing, random transformation, shape shifting, unstable anatomy,
limb flicker, hand flicker, eye flicker, mouth flicker, facial warping,
melting motion, rubber motion, glitch motion, ghost trails, motion tearing,
frame interpolation artifacts, duplicate frames, missing frames, stutter,
judder, unnatural motion blur, excessive motion blur, frozen body parts,
floating motion, sliding feet, foot skating, body jitter, teleporting objects,
prop popping, object disappearance, object mutation, camera jump,
random camera movement, broken continuity, inconsistent lighting across frames,
texture crawl, pattern shimmer, background wobble, face replacement artifacts
```

---

## 十、剧情短剧/人物演绎专用补充负面提示词

适合强调“演技感”“真实人物表演”“影视剧表情管理”的提示。

```text
overacting, exaggerated expression, meme face, comedy face, cartoon reaction,
blank expression, emotionless face, lifeless performance, stiff acting,
awkward gesture, robotic gesture, unnatural eye movement, broken lip sync,
incorrect mouth shapes, fake crying, fake anger, fake smile, inconsistent emotion,
expression drift, emotional mismatch, wrong reaction timing
```

---

## 十一、古装/历史/仙侠题材补充负面提示词

```text
modern hairstyle, modern makeup, modern fabric, zipper, plastic ornament,
cheap armor, inaccurate hanfu, wrong dynasty costume, synthetic embroidery,
western fantasy contamination, game armor, cosplay look, stage play look,
cheap wig, plastic jewelry, modern architecture, modern props,
neon modern lighting in historical scene, historical inconsistency
```

---

## 十二、都市/现实主义题材补充负面提示词

```text
soap opera lighting, studio set look, cheap TV drama look, over-beautified face,
beauty filter, idol drama filter, artificial apartment, fake office,
implausible props, showroom furniture, stock-photo look, ad-like scene,
overposed characters, unrealistic wardrobe, too clean environment, fake realism
```

---

## 十三、悬疑/惊悚/犯罪题材补充负面提示词

```text
cheap horror effect, cheesy blood, fake blood texture, bad wound makeup,
unintended comedy, cartoon darkness, muddy darkness, unreadable shadows,
random gore, broken suspense atmosphere, oversaturated red, fake smoke,
fake rain, low-detail night scene, flashlight inconsistency, unstable darkness
```

---

## 十四、科幻/赛博/未来题材补充负面提示词

```text
cheap sci-fi, low-budget sci-fi, toy spaceship, fake hologram, bad neon,
overdesigned UI, floating meaningless interface, random glowing lines,
plastic armor, cosplay sci-fi, game cutscene look, low-detail mech,
illogical technology, repeated assets, fake reflections, cluttered cyberpunk,
oversaturated blue-purple palette, unreadable scene, noisy neon lighting
```

---

## 十五、战争/动作/打斗场景补充负面提示词

```text
fake action pose, frozen action, impossible combat stance, soft weapon,
rubber weapon, bad impact, no weight, no force, floating debris,
wrong muzzle flash, unrealistic recoil, duplicated soldiers, repeated explosions,
cheap explosion, fake smoke, low-detail fire, disconnected fight choreography,
body clipping, impossible collision, foot sliding, broken stunt motion
```

---

## 十六、可直接复制的组合模板

### 1. 通用影视写实版

```text
worst quality, low quality, blurry, lowres, out of focus, pixelated, noisy,
bad anatomy, deformed face, asymmetrical face, bad hands, extra fingers,
missing fingers, fused fingers, extra limbs, missing limbs, distorted body,
plastic skin, waxy skin, uncanny valley, cartoonish, CGI look, 3d render,
bad composition, flat lighting, overexposed, underexposed, muddy colors,
wrong shadows, inconsistent lighting, warped background, fake reflections,
watermark, logo, text, subtitles, cropped, cut off
```

### 2. 人物特写版

```text
bad face, distorted face, asymmetrical face, dead eyes, cross-eyed,
blurry face, melted face, bad lips, bad teeth, bad ears,
plastic skin, over-smoothed skin, heavy beauty filter, fake pores,
bad hair, wig-like hair, hair clipping, floating hair,
bad hands, extra fingers, fused fingers, malformed hands,
awkward pose, stiff pose, mannequin pose, bad lighting, flat lighting
```

### 3. 文生视频连续性版

```text
frame flicker, temporal inconsistency, character drift, identity drift,
face drift, costume drift, object drift, background drift,
facial warping, hand flicker, eye flicker, mouth flicker,
scene morphing, random transformation, glitch motion, ghost trails,
sliding feet, body jitter, teleporting objects, camera jump,
inconsistent lighting across frames, texture crawl, background wobble,
prop popping, object mutation, broken continuity
```

### 4. 古装影视版

```text
modern hairstyle, modern makeup, zipper, plastic ornament, cosplay look,
cheap wig, plastic jewelry, inaccurate hanfu, wrong dynasty costume,
synthetic embroidery, game armor, modern props, modern architecture,
face asymmetry, bad hands, extra fingers, bad anatomy,
flat lighting, fake set, cheap costume, waxy skin, CGI look
```

### 5. 科幻电影版

```text
cheap sci-fi, toy-like technology, fake hologram, low-detail mech,
game cutscene look, plastic armor, cluttered neon, oversaturated neon,
face distortion, identity drift, bad anatomy, fake reflections,
poor compositing, cheap VFX, matte edges, floating UI,
random glowing lines, warped perspective, unreadable scene
```

---

## 十七、使用建议

### 1. 基础搭配公式

```text
通用负面词 + 人物结构负面词 + 题材补充负面词 + 视频连续性负面词（仅视频）
```

### 2. 不同任务的推荐组合

- 角色海报：通用 + 人物 + 服装 + 光影
- 对话镜头：通用 + 人物 + 双人群像 + 镜头语言
- 古装定妆：通用 + 人物 + 古装补充 + 服装发型
- 动作戏：通用 + 人体结构 + 战争动作补充 + 视频连续性
- 文生视频：通用 + 人物 + 镜头 + 时序连续性

### 3. 关键压制项优先级

最常用的优先级通常是：

1. `bad anatomy`
2. `bad hands`
3. `deformed face`
4. `plastic skin`
5. `temporal inconsistency`（视频）
6. `identity drift`（视频）
7. `flat lighting`
8. `CGI look`
9. `warped background`
10. `text, watermark, logo`

---

## 十八、极简版负面提示词

适合长度受限的平台。

```text
worst quality, low quality, blurry, lowres, bad anatomy, bad hands,
extra fingers, missing fingers, deformed face, asymmetrical face,
plastic skin, waxy skin, CGI look, cartoonish, flat lighting,
warped background, text, watermark, logo
```

## 十九、强化版负面提示词

适合高要求影视级写实生成。

```text
worst quality, low quality, lowres, blurry, soft focus, out of focus, pixelated,
noise, jpeg artifacts, compression artifacts, overprocessed, oversharpen,
bad anatomy, deformed, distorted, malformed, disfigured, mutation,
extra limbs, missing limbs, disconnected limbs, duplicate body,
bad hands, malformed hands, extra fingers, missing fingers, fused fingers,
bad face, deformed face, asymmetrical face, melted face, duplicate face,
dead eyes, cross-eyed, wrong facial proportions, bad lips, bad teeth,
plastic skin, waxy skin, over-smoothed skin, uncanny valley,
wig-like hair, floating hair, hair clipping, melted hair,
bad costume, clipping clothes, plastic fabric, wrong period costume,
bad composition, awkward framing, flat lighting, overexposed, underexposed,
wrong shadows, inconsistent lighting, washed out, muddy colors,
warped background, fake set, low-detail environment, perspective distortion,
CGI look, 3d render, toy-like, doll-like, game render,
watermark, logo, text, subtitles, cropped, cut off
```

---

## 二十、纯中文负面提示词（适配可灵 / 即梦 / Vidu / Wan 等国产模型）

国产视频模型大多有独立的中文负面输入框，对中文识别良好。以下为可直接复制的中文模块。

### 1. 中文通用底包

```text
低质量, 最差质量, 模糊, 失焦, 低分辨率, 噪点, 颗粒感, 压缩失真, 过曝, 欠曝,
画面脏, 灰蒙蒙, 偏色, 过饱和, 构图混乱, 主体被裁切, 变形, 扭曲, 畸形, 结构错误,
比例失调, 多余的肢体, 缺失的肢体, 塑料感, 蜡像感, 假, 卡通感, 3D渲染感, 游戏画面,
水印, 文字, 字幕, logo, 签名, 黑边, 边框，屏幕不能反向展示
```

### 2. 中文人物模块

```text
脸部扭曲, 五官错位, 五官不对称, 斜眼, 死鱼眼, 眼神空洞, 双下巴异常, 嘴巴歪斜,
牙齿畸形, 表情僵硬, 面瘫, 表情狰狞, 皮肤蜡感, 过度磨皮, 假毛孔, 换脸痕迹, 面具感,
畸形的手, 多余手指, 缺失手指, 手指粘连, 六根手指, 手部扭曲, 多余头部，多余手臂, 断肢,
姿态僵硬, 姿势不自然, 假人姿势, 关节反向, 脖子过长, 头身比例错误
```

### 3. 中文时序连续性模块（视频专用）

```text
画面闪烁, 抖动, 卡顿, 掉帧, 拖影, 鬼影, 残影, 撕裂, 抽搐, 诡异蠕动,
人物长相前后不一致, 换脸, 身份漂移, 服装突变, 发型突变, 场景突变, 背景漂移,
物体忽大忽小, 颜色跳变, 光照不稳定, 脚底打滑, 违反物理的运动, 动作不连贯, 物体瞬移
```

### 4. 中文古装 / 都市 / 科幻补充

```text
古装: 现代发型, 现代妆容, 拉链, 塑料饰品, 廉价假发, 塑料首饰, 服饰形制错误,朝代混乱, 现代建筑, 现代道具, cos感, 舞台剧感
都市: 肥皂剧打光, 摄影棚感, 廉价电视剧感, 过度美颜, 偶像剧滤镜, 样板间家具, 广告感
科幻: 廉价特效, 玩具感飞船, 假全息, 塑料盔甲, 杂乱霓虹, 过饱和蓝紫, 游戏CG感, 无意义UI
```

### 5. 中文一体化模板（写实影视 · 直接复制）

```text
低质量, 模糊, 噪点, 压缩失真, 变形, 畸形, 结构错误, 比例失调, 多余的肢体, 缺失的肢体,
脸部扭曲, 五官错位, 死鱼眼, 表情僵硬, 皮肤蜡感, 过度磨皮, 畸形的手, 多余手指,
画面闪烁, 抖动, 拖影, 鬼影, 人物长相前后不一致, 换脸, 身份漂移, 场景突变, 光照不稳定,
灰蒙蒙, 偏色, 平光, 构图混乱, 塑料感, 卡通感, 3D渲染感, 假, 水印, 文字, 字幕, logo, 黑边
```

---

## 二十一、备注

不同模型对英文负面词兼容性通常强于中文，因此建议优先使用英文负面提示词；如果平台更适合中文，也可以将上面的模块翻译组合后使用。

这份文档更偏“写实影视剧”和“电影感”方向。如果目标是动漫、二次元、插画、实验影像、MV 风格，需要重新调整负面词策略。
