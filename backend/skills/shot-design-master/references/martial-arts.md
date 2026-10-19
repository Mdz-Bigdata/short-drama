# AI 短剧电影级武打镜头设计指南

> 解决 AI 生成动作场景“假打无力、关节穿模、物理力学崩坏”的系统方案
> 工作流：微动作物理拆解 + 力学负反馈提示词 + 动能运镜语言 + “出招-受击”正反打剪辑

📎 **关联文档**：总入口 [README](README.md)。本文件是**动作、格斗、武打、力学反馈、冷兵器与气浪特效**的权威规范；人物一致性提示词见 [三视图模板](AI短剧三视图解决人物一致性提示词模板.md)，跨镜头衔接见 [连续性设计指南](AI短剧连续性设计指南.md)，镜头语言见 [导演分镜指南](AI短剧与漫剧导演级拍摄分镜完全指南.md)，质检见 [一致性检查清单](<AI 生成短剧一致性检查清单.md>)。

---

## 一、 动作场景整体工作流架构

动作场景在 AI 视频生成（如即梦 Seedance 2.0、Kling、Runway Gen-3）中是崩坏率最高的区域。为了获得“拳拳到肉”的电影级质感，必须舍弃让 AI 在单镜中完成复杂对打的幻想，采用以下工业级工作流：

```
【动作资产创作流】
┌───────────────────┐      ┌───────────────────┐
│   动作姿态参考帧   │      │ 物理力学反馈提示词 │
│ Pose Reference/   │      │ (重心沉降/碎石飞溅/ │
│ controlnet_pose   │      │  碰撞闪烁/能动气浪) │
└─────────┬─────────┘      └─────────┬─────────┘
          │ 注入姿态/关键动作         │ 注入物理逻辑
          ▼                         ▼
┌──────────────────────────────────────────────┐
│        AI 视频动作层生成 (Kling/Seedance)     │
│        (单镜控制在 1.5 - 2.5s，禁止长段乱动)     │
└──────────────────────┬───────────────────────┘
                       │ 导出动作短片 (无声)
                       ▼
┌──────────────────────────────────────────────┐
│  动作镜头剪辑拆分 (正反打蒙太奇：“出招镜” + “受击镜”)  │
└──────────────────────┬───────────────────────┘
                       │ 剪辑组装对齐
                       ▼
┌──────────────────────────────────────────────┐
│      特效音效混合层 (Sfx: 兵器撞击/重击/尘土爆裂)   │
└──────────────────────────────────────────────┘
```

---

## 二、 动作力学拆解：用“受力反馈”代替“抽象动词”

### 2.1 核心痛点
AI 无法直接理解“降龙十八掌”、“飞踢”或“激烈格斗”这类高度抽象或写意的词汇，直接输入会导致 AI 生成“假人比划”或者角色身体漂浮、失去重力。

### 2.2 物理力学三大原则
要让打斗产生力量感，提示词必须描述**物理受力的发生过程与环境负反馈**：
1. **重心沉降（蓄力）**：在出招前，描述角色的身体重心下移、膝盖微屈、地面因踩踏受力而开裂或扬尘。
2. **动能传递（出招）**：描述发力部位的肌肉隆起、衣服因快速挥动产生的贴体褶皱、武器带起的气流气浪。
3. **受力反馈（击中）**：**这是力量感的灵魂**。不要写“打倒对方”，要写“重拳命中脸颊瞬间面部肌肉剧烈震颤、汗水与血沫飞溅、身体呈弧线被击退数米、双脚在地面擦出深深的划痕与尘土”。

### 2.3 物理力学反馈提示词表

| 动作阶段 | 物理微动作描述 (Positive Prompts) | 叙事/视觉目的 |
| :--- | :--- | :--- |
| **蓄力 (Anticipation)** | `shoulders tense, body weight shifts downward, feet stomping the ground creating minor cracks and swirling dust, clothes blowing backward due to energy buildup` | 表现招式爆发前的压迫感，积蓄张力。 |
| **武器挥砍 (Slash/Swing)** | `blade cutting through air, glowing kinetic wind trail, shockwave warping the air (refraction effect), speed lines flashing in background` | 表现冷兵器的锋利与速度，使武器轨迹可见。 |
| **拳脚命中 (Impact)** | `fist connecting with jaw, impact frame flashing white for 1 frame, sweat and water droplets flying off, facial muscles compression` | 突出“拳拳到肉”的物理重量，增加瞬间冲击力。 |
| **受击反弹 (Reaction)** | `character knocked backward, sliding on dirt leaving deep tracks, background blur, dust exploding behind upon wall impact` | 用被击退者的狼狈程度来反衬出招者的力量。 |
| **气浪与环境反馈** | `kinetic air blast dispersing nearby grass and pebbles, dynamic smoke trails curling around limbs, volumetric dust rising` | 利用环境（碎石、风沙、落叶）的形变作为力量的扩音器。 |

---

## 三、 动能运镜语言：动作戏的镜头法则

动作戏的刺激感很大程度上依赖于摄影机的运动。利用大模型的运动控制参数（或提示词），将镜头运动与物理碰撞对齐：

### 3.1 动作戏黄金运镜术语

*   **极速推焦 (Whip Zoom / Fast Push)**：在拳头或武器击中目标的瞬间，镜头以极快的速度推向撞击点。
    *   *提示词*：`whip zoom into the contact point, high-speed camera motion, sudden camera shake on impact`
*   **手持震颤 (Handheld Shake)**：模拟摄影师手持摄像机在战场奔跑的纪实感，震颤与受力瞬间同步。
    *   *提示词*：`handheld camera tracking, raw documentary style, dynamic screen shake synchronized with the heavy blow`
*   **低角度仰拍追踪 (Low-Angle Tracking)**：摄影机置于极低位置，仰视出招者或前冲的身体，放大角色的伟岸度与威慑力。
    *   *提示词*：`low-angle tracking shot, looking up at the hero charging forward, fast camera movement close to the ground`
*   **希区柯克变焦/拉镜头 (Dolly Zoom / Whip Pull)**：出招瞬间镜头拉远，突出招式在大环境中的爆裂范围。
    *   *提示词*：`dolly zoom effect, rapid camera pull back to reveal a shockwave blast dispersing the environment`
*   **子弹时间 (Bullet Time / Slow-Motion Detail)**：在兵器相碰或致命一击时，时间骤然变慢，360 度环绕展示凝固的细节。
    *   *提示词*：`bullet time style, extreme slow-motion (slow-mo), 360-degree orbit shot around the frozen clash of blades, sparks suspended in air`

---

## 四、 实战提示词模板（中英双语）

### 模板一：古风硬核武侠——刀剑碰撞与水墨残影

> **应用场景**：竹林或古建筑楼顶，两位斗笠剑客生死对决，重力量、重写意。
> **适用模型**：doubao-seedance-2-0-260128 图生视频/文生视频。

```
【正向提示词】
Cinematic action scene, low-angle tracking shot. Two martial artists in bamboo hats and black ancient robes clashing swords. 
The heavy steel blades strike together, generating intense sparks flying outward. Kinetic shockwave warps the air around them. 
One warrior slides backward on the wet ground, feet kicking up dirt and rain splashes. Volumetric fog in background. 
Extreme slow-motion during impact, camera whip pan tracking the trajectory of the sword. 
Epic lighting, octane render, Unreal Engine 5 render, cinematic 3D render quality, high-fidelity CGI.

【负向提示词】
(避免：照片、真实名人、证件照、写真、passport photo, headshot, photorealistic, real human skin pores, camera snapshot, deformed limbs, floating bodies, clean ground, static air)
```

### 模板二：现代硬核近战——拳拳到肉与力学形变

> **应用场景**：昏暗的地下拳馆或雨夜街头，写实近身格斗，重击面部，重挫败感。
> **适用模型**：Kling / Seedance 2.0。

```
【正向提示词】
Gritty action movie style, handheld camera. Close-up shot of a powerful fist connecting with the opponent's jaw. 
Slow-motion capture of the impact: sweat and water droplets flying off in a spray, facial muscles compressed under the force. 
The screen shakes violently upon connection. The opponent stumbles backward, crashing into wood crates, debris and dust exploding into the air. 
Rembrandt lighting, high contrast, deep shadows, cinematic 3D render, high-fidelity CGI.

【负向提示词】
(避免：照片、真实名人、写真、photorealistic, headshot, real human skin pores, camera snapshot, extra fingers, deformed face, floating action, no-impact fight, slow motion with no force)
```

### 模板三：科幻/玄幻动作——能动气浪与粒子碰撞

> **应用场景**：废土或科幻赛博街头，动作带起能量屏障或空气折射，重特效视觉冲击。
> **适用模型**：Kling / Seedance 2.0 / Agnes。

```
【正向提示词】
Sci-fi combat action, dolly zoom shot. A warrior in sleek exoskeleton armor executing a ground-slam attack. 
A massive circular energy shockwave blast expands outward, warping the space and air (refraction effect). 
Pebbles, dirt, and concrete debris are thrown into the air, suspended in high-speed camera slow-motion. 
Neon lights reflection on wet ground, volumetric smoke trails curling around armor, Unreal Engine 5 render, cinematic 3D render.

【负向提示词】
(避免：照片、真实名人、写真、photorealistic, headshot, real human skin pores, camera snapshot, low-resolution dust, static environment, no-impact slam)
```

---

## 五、 剪辑避坑与防崩溃机制（动作戏黄金法则）

由于 AI 生成多肢体高频互动的视频时，穿模（如胳膊长在一起、身体融为一体）的概率高达 90%。**动作短剧必须在剪辑层面拆分镜头：**

### 5.1 “出招-受击”分镜拆分法（Montage Edit）
不要强求 AI 在同一个镜头中生出“A打中B且B倒地”的动作。将动作拆分为三个镜头，后期进行蒙太奇拼接：

*   **镜号 1（出招镜，中景/特写，2s）**：
    *   *画面内容*：A 重心下沉，一记重拳朝摄影机方向猛烈轰出，带起一阵强风气浪，画面在出拳瞬间极速向前 Whip Zoom。
    *   *生成难度*：低。因为只有单人出招动作，完全不会穿模。
*   **镜号 2（受击镜，近景/特写，1.5s）**：
    *   *画面内容*：B 侧脸受重击，脸部发生物理压缩受力形变，头猛地向一侧偏转，水珠飞溅。
    *   *生成难度*：低。可以通过 LivePortrait 或特定受击关键帧插值快速生成。
*   **镜号 3（环境负反馈镜，远景/全景，2s）**：
    *   *画面内容*：B 身体成弧线向后倒飞，砸在地上向前滑行，地上擦起一片尘土，背景的货架或碎石崩落。
    *   *生成难度*：中等。远景中人物细节度低，主要展示“人体抛物线+物理碎裂特效”，极其容易跑通。

> 💡 **效果**：这三个镜头在时间轴上快速拼接（2s -> 1s -> 2s），配合**击中瞬间一帧的白屏闪烁（冲击帧）**和**爆裂的撞击音效（SFX）**，其视觉冲击力和“打击感”甚至会远远超越真实动作演员的套路打斗，呈现出极其强烈的电影级节奏！

## 六、 空间动作学：轴线原则与 180 度防越轴规约

### 6.1 越轴痛点
在 AI 视频生成中，由于每个镜头是独立渲染产生的，大模型极易发生“越轴（Crossing the Line）”问题：上一镜 A 在左、B 在右，下一镜突然变成 A 在右、B 在左。这会导致动作的方向感在剪辑时完全颠倒，让观众产生强烈的空间方向混乱。

```
【动作拍摄 180 度轴线规约】
             [角色 A] ───────────────── [角色 B]  (轴线 Axis)
                │                         │
  摄影机机位 1  🎥                        🎥  摄影机机位 2
  (A 在左, B 在右)                         (过肩视角 A -> B)
─────────────────────────────────────────────────────────────────
  [禁止越轴区]  ─────────────────────────────────────────────────
  摄影机机位 3  ❌ 🎥 (越轴机位：左右位置瞬间对调，造成穿帮)
```

### 6.2 防越轴约束规则
在撰写分镜提示词（Prompt）时，必须执行严格的**空间位置硬锚定**：
*   **屏幕左右固定锚定**：在每一个动作镜头的提示词里，明确标注角色的左右相对方位。
    *   *提示词*：`A is positioned on the left side of the frame, facing and striking towards the right; B is on the right side of the frame, facing left in a defensive posture.`
*   **过肩镜头（Over-the-shoulder, OTS）定向**：利用过肩视角作为安全过渡镜，锁死轴线。
    *   *提示词*：`Over-the-shoulder shot, looking from behind A's left shoulder on the left foreground at B who is standing on the right.`
*   **后期镜像翻转兜底**：如果 AI 生成的动作方向完美但位置越轴，**直接在后期剪辑软件（Premiere / CapCut）中水平镜像翻转视频**，简单且高效地拉回 180 度轴线。

---

## 七、 电影级动作景别切换公式（五镜动作链）

单调的景别会让武打动作显得机械无聊。动作导演推崇的“五镜动作链”公式，能在 10 秒内拉满视觉节奏：

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  第一镜 (全景) │ ──▶ │  第二镜 (中景) │ ──▶ │  第三镜 (近景) │ ──▶ │  第四镜 (特写) │ ──▶ │  第五镜 (POV)  │
│  Establishing│     │    Charge    │     │    Attack    │     │    Impact    │     │   Reaction   │
└──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘
```

1. **第一镜：全景对峙 (Establishing Clash, 2-3s)**
   - *目的*：展示双方的相对站位、体型差距以及场景氛围。
   - *画面*：大雨磅沱的竹林中，两名剑客斗笠低垂，按剑对视。
2. **第二镜：中景前冲 (Medium Shot Charge, 1.5s)**
   - *目的*：展示爆发速度和前冲身法。
   - *画面*：低角度摄像机前冲，侠客踏地起尘，身后的泥水飞溅。
3. **第三镜：近景交锋 (Close-up Attack, 1.5-2s)**
   - *目的*：展示招式的帅气度与动作线条。
   - *画面*：单人挥刀切入画面，刀锋在空气中拉出一道半月形的白色刀光气浪。
4. **第四镜：特写重击 (Extreme Close-up Impact, 1s)**
   - *目的*：传递极致的力量与物理重量（拳拳到肉）。
   - *画面*：拳头或刀靶重重砸在对方脸上，下巴瞬间产生挤压形变，汗水与雨水在强力下飞散。
5. **第五镜：第一人称受击 (POV Reaction, 2s)**
   - *目的*：增强观影的代入感与情绪张力。
   - *画面*：第一人称视线模糊、镜头伴随强震，看向上方缓缓收拳的胜者。

---

## 八、 冷兵器与能量交接光影特效进阶

要让刀光剑影、法术轰击产生高级电影感，必须引入专业的渲染和物理折射词汇：

*   **剑气折射与刀光气浪 (Blade Aura Refraction)**
    *   不要写“发光的蓝色剑气”。要写“刀刃挥动产生的空气折射气浪，如同热浪折射背景，剑气划过的轨迹空气扭曲（refraction trails, kinetic aura wave, heat distortion along the blade path）”。
*   **金属对撞微粒与火星 (Parry Embers & Kinetic Sparks)**
    *   兵器碰撞时应有反作用力产生的粒子飞溅。
    *   *提示词*：`intense orange sparks ejecting from the steel collision, glowing metal embers suspended in slow-motion, physics-based particle dispersal`
*   **逆光剪影与侧逆边缘光 (Contre-jour & Rim Lighting)**
    *   侧逆光是渲染动作轮廓的高级打光手法，特别适合在雨、雾、尘土中勾勒手部和武器边缘。
    *   *提示词*：`strong backlight (contre-jour) creating a dramatic silhouette, sharp rim lighting tracing the armor edges, light rays filtering through the thick dust and splinters`

---

## 九、 动作音效（SFX）与 Foley 拟音卡点表

动作戏“三分看画，七分听声”。无声或配音不对位的打戏会显得像“纸片人比划”。

| 动作类型 | 推荐 SFX/Foley 音效描述 | 对齐控制 (对齐画面的哪一帧) | 混音建议 |
| :--- | :--- | :--- | :--- |
| **重拳/重腿命中** | `Heavy blunt punch impact, organic low-frequency thud, bone cracking sound effect` | 重拳击中面部形变的**第一帧**。 | 适当切掉中高频，增强低音（Bass），产生钝击骨裂的物理分量感。 |
| **金属兵器格挡** | `High-pitched metallic sword clash, ringing steel resonance, weapon parry` | 兵器相交迸发出橙色火花的那**一瞬间**。 | 音频留置 0.5s 的高频余音颤鸣（Ringing tail），表现兵器对震。 |
| **空手挥舞/武器破风** | `Fast whoosh sweep, air tearing sound, blade swinging through air` | 动作开始加速前冲、刀光气浪浮现的**前 3 帧**。 | 声音先于画面命中发生，为撞击进行听觉蓄力。 |
| **受击飞出坠地** | `Heavy body fall, gravel debris rustling, dust explosion impact sound` | 身体后背或脚底接触地面、爆起尘土的**那一帧**。 | 混合沙石碎裂声与身体重击声，根据场景材质（木板/泥地）调整。 |

---

## 十、 动作时序时间戳控制与冲击帧技术（AI 动作微操）

想要做出富有卡点节奏和顿挫感的武打戏，必须利用最新的模型时间戳分配与视觉冲击帧技术：

### 10.1 动作时间戳引导 (Timestamp Motion Control)
针对 Kling、Runway 和火山 Seedance 2.0 等支持时序引导的大模型，不要将所有攻击和格挡动作杂糅在一个 Prompt 中。建议在提示词头部使用秒级时间戳分配动作：
*   **动作分配公式**：`[0:00-0:02] A charges forward aggressively; [0:02-duration] A swings a heavy right hook connecting with B's jaw.`
*   **底层原理解析**：AI 的扩散模型是在时序帧（Latent Space Frames）中按步扩散生成的。在提示词中显式带入秒级时段切片，能够引导模型在扩散前几步（Denoising Steps）将动作能量强行约束在对应的帧区间，**从根本上解决动作随机发生、无法卡点在特定时间片上的难题**。

### 10.2 瞬间冲击帧技术 (Impact Frame & Flash Effect)
好莱坞动作电影中，在拳拳命中的黄金帧，画面往往会发生 1 帧的强烈曝光、黑白交替或瞬间白光以突出打击力道。在 AI 视频提示词中，可以通过专门的特效词汇引导模型生成此视觉特效：
*   *提示词*：`1-frame flashing impact white screen, sudden momentary black and white flash, extreme dynamic range burst at the moment of contact`
*   **视觉生理原理**：当人的视网膜接收到极短时间（约 0.04s，即 24fps 下的 1 帧）的色彩/明暗骤变时，脑部视觉皮层会自然产生物理性的“碰撞负反馈”，从而在生理层面产生极其强烈的打击力量感。

---

## 十一、 Seedance 2.0 风格锚定与第三方网关合规清洗自愈（工程实践）

为了让打斗镜头能够在全自动流水线上切实落地，需要对各厂商 API 进行针对性的接口协议适配：

### 11.1 火山 Seedance 2.0 顶层传参与 style_caption 规范
火山 Ark (Seedance 2.0) 的请求结构和 1.x 有本质区别，必须在代码库和提示词模板里严格遵守以下规则以防 400 报错：
1.  **参数解耦**：`resolution`, `duration`, `ratio`, `watermark` 必须在 API 请求体的**顶层字段**传输，绝不能在 text 字段里使用 `--flags` 命令行参数。
2.  **强制 style_caption 风格锚定**：在 content 的文本对象中，**必须**携带 `style_caption` 字段（否则直接报 `InvalidParameter.BodyFormat`，『it must contain style_caption field』）。
3.  **写实排卡（Anti-Anime Filter）**：在 `style_caption` 中，显式通过负向提示排除动画、3D、插画与草图，强制大模型锚定在照片级写实电影剧照上：
    - *style_caption 推荐值*：`真实电影质感，实拍写真，photorealistic live-action cinematic film still, real human skin texture, natural lighting; 绝非动画、绝非卡通、绝非3D渲染、绝非插画、绝非草图 (not anime, not cartoon, not 3d render, not cgi, not illustration, not sketch)`

### 11.2 第三方网关安全清洗与过滤自愈 (Sanitizer)
*   **痛点**：第三方网关（如 Agnes、Gemini）的内容审核（Content Policy）极度敏感，如果将用来在火山防疑似真人的 `DEID_NEGATIVE` 敏感身份词（如 `passport photo`, `headshot`, `not a real person` 等）或激烈的戏剧打斗冲突词（如 `杀`, `死`, `暴力`, `重拳打脸`, `羞辱` 等）直接投递，网关会判定为违规并返回 400 拒绝出图/视频。
*   **自愈方案**：在将提示词发送给第三方网关前，必须经过**动作词清洗器 (Sanitizer)**。通过正则替换成对的中英文括号，并自动剔除所有暴力、血腥及身份敏感词（如将“重拳砸烂脸颊”清洗为“双手与手臂的快速物理碰撞”），保留正向的写实电影画风与分镜，从而实现全自动流水线不被网关拦截的安全自愈。

---

## 十二、 动作短剧制作 Checklist

*   [ ] **分镜拆分率 > 80%**：动作戏绝不使用超过 3 秒的长镜头，全片采用快切节奏。
*   [ ] **防越轴检测**：检查相邻镜头中，角色 A 与 B 的左右屏幕相对位置是否恒定，发生越轴的镜头在后期执行水平镜像翻转。
*   [ ] **物理动作带起环境反馈**：每一个打击或蓄力动作，必须伴随尘土、碎石、落叶、雨滴或水墨粒子等物理负反馈。
*   [ ] **画面/声轨帧级对齐**：兵器撞击（Clash）与重拳击中（Thud）的音效，必须与画面受力变形的第一帧精确对齐。
*   [ ] **防真人风控**：所有图生视频的首帧图必须包含 `DEID_POSITIVE` 的 CGI/3D 渲染字样，规避火山风控。
*   [ ] **打击瞬间慢动作（Slow-mo）卡点**：在重击命中瞬间，视频降速至 0.25x 播放（持续 0.5s），增加招式的分量感。
*   [ ] **冲击波与折射滤镜**：在重撞击帧添加 1-2 帧的画面轻微缩放或色偏，模拟空气冲击波。
*   [ ] **API 协议合规与 style_caption 检查**：确认 Volcano Ark 视频请求体包含了必填的 `style_caption` 字段用于风格写实锚定，第三方网关请求前经过了 Sanitizer 物理冲突词清洗。

---

## 十三、 AI短剧与漫剧影视级多维表现力设计矩阵

在全自动的 AI 短剧/漫剧生成管线中，为了消除 AI 廉价感、面瘫脸和背景塑料感，必须遵循以下六大影视表现力维度的控制规范：

### 13.1 电影级色彩与调色矩阵 (Color Grading & Palette)
色彩是电影情感的催化剂。不要使用抽象的 `beautiful color`，直接使用具体的调色和胶片风格：
1. **Teal and Orange (青橙色调 - 动作格斗黄金配色)**: 
   - *提示词*: `Teal and Orange color grading, high contrast cinema grading, warm highlights and cool cyan shadows, cinematic blockbuster look`
2. **Muted Greens & Bleach Bypass (低饱和灰绿/银盐保留 - 悲情/冷峻/肃杀)**: 
   - *提示词*: `bleach bypass film style, desaturated colors, muted mossy greens and cold blue tones, raw film texture`
3. **Golden Hour Warmth (黄金时刻 - 温馨/希望/回忆)**: 
   - *提示词*: `Golden Hour lighting, warm sunset glowing hues, soft orange light rays, Kodak Portra 400 film tones`
4. **Neon Teal & Magenta (霓虹紫青 - 赛博/虚幻都市)**: 
   - *提示词*: `neon color scheme, vibrant teal and magenta reflected glow on wet ground, cross-processed colors, cyber atmosphere`
5. **Monochromatic Sodium Vapor (单色钠灯 - 废墟/荒凉/历史厚重)**: 
   - *提示词*: `sodium vapor monochromatic tones, deep high-contrast dark-yellow lighting, gritty rusty textures`

### 13.2 角色微表情情绪控制引擎 (Micro-Expression & facial muscles)
AI 面部“恐怖谷”与“死人脸”源于没有面部微反应。将文学情绪词转换为面部肌肉骨骼指令：
*   **悲伤/哭泣/痛苦 (Sad/Crying/Pain)**: 
    - *提示词*: `lower eyelids slightly swollen and red, tears welling in the bottom of eyes, under-lip tensed and gently bitten by teeth, subtle chin muscles trembling` (下眼睑微红肿胀，泪水在眼眶打转，轻咬下唇，下巴细微颤抖)
*   **愤怒/狰狞/暴烈 (Angry/Fierce/Roar)**: 
    - *提示词*: `eyebrows knitted together tightly forming deep vertical wrinkles, nostrils flaring slightly, corners of the mouth pulled downward and tensed, teeth gritted, intense fierce glare` (眉头紧锁产生垂直褶皱，鼻翼扇动，嘴角下沉拉紧，咬牙切齿)
*   **震惊/恐惧/害怕 (Shocked/Scared/Shiver)**: 
    - *提示词*: `pupils dilated, eyelids wide open, mouth slightly agape, Adam's apple slowly bobbing, subtle body shivering under light` (瞳孔放大，眼皮圆睁，嘴角微张，喉结滚动)
*   **喜悦/邪魅/狂妄 (Joyful/Smirking/Arrogant)**: 
    - *提示词*: `one eyebrow slightly arched, single corner of the mouth curved upward in a smirking grin, gaze full of contempt, confident expression` (单侧挑眉，嘴角斜笑，眼神轻蔑)
*   **隐忍/克制/沉思 (Contemplative/Refraining/Reflective)**: 
    - *提示词*: `gaze downward and wandering, lips pressed tightly in a thin line, facial muscles slightly rigid and tense` (视线低垂游移，双唇紧闭，面部僵硬)

### 13.3 场景背景自愈规约 (Anti-Flat Background)
为防止 AI 生成的背景缺乏细节、光影对齐差、有贴纸塑料感，执行以下提示词规约：
*   **电影景深虚化 (Depth of Field)**: 
    - *提示词*: `cinematic depth of field, blurred bokeh background, 85mm f/1.8 lens effect`
*   **偏移构图法则 (Off-Center Rule of Thirds)**: 
    - *提示词*: `rule of thirds off-center composition, dynamic side perspective` (三分法偏心构图，侧向透视，避免大面积居中)
*   **做旧质感颗粒 (Film Grain)**: 
    - *提示词*: `subtle organic 35mm film grain, realistic surface textures, raw photo quality` (消除 AI 的平滑涂抹感)

### 13.4 影视级经典运镜与构图风格
在提示词中直接嵌入标准的电影调度指令：
*   **过肩镜头 (Over-The-Shoulder, OTS)**: `Over-the-shoulder shot (OTS), looking from behind foreground character's shoulder at the target` (锁定轴线，强化空间感)
*   **荷兰偏角 (Dutch Angle)**: `Dutch angle tilted camera frame, dramatic low-key lighting` (渲染反派、危机或心理不安)
*   **低角度跟踪 (Low-Angle Tracking)**: `low-angle tracking shot looking up, dynamic speed lines` (彰显伟岸或冲击力)

### 13.5 高级光影雕刻 (Cinematic Lighting)
*   **顶光与硬侧光 (Top-down & Hard Side-light)**: 
    - *提示词*: `dramatic top-down lighting mixed with hard side-light, emphasizing character muscles and sharp metallic edges`
*   **轮廓边缘光 (Rim Light)**: 
    - *提示词*: `sharp intense rim light outlining the figure's silhouette, strong contrast, dark shadow depth`
*   **体积光/丁达尔效应 (Volumetric Rays)**: 
    - *提示词*: `volumetric light beams (Tyndall effect) filtering through smoke and dust particles`

### 13.6 男频/玄幻题材特征道具视觉增强
*   **金属飞剑 (Flying Sword)**: 
    - *提示词*: `metallic flying sword floating in mid-air, ancient runes glowing on the blade, surrounded by crackling electric sparks, kinetic wind distortion trails`
*   **上古魔印 (Demon Seal)**: 
    - *提示词*: `rough black basalt seal with flowing magma-red molten runes, emitting dark volumetric smoke, micro space fissures warping the background`
*   **法宝法阵 (Magic Astrolabe)**: 
    - *提示词*: `rotating miniature gold astrolabe, galaxy-like stardust swirling inside, projection of transparent colored magic circles`


