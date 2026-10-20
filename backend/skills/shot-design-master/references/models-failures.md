# 模型能力、质量锚点与失败诊断

---

## 一、单镜时长上限（硬约束）

一个镜头必须能被所选模型**一次生成出来**。超限就拆镜，不要压缩内容。
下表的上下限是**生成请求时长（层①）**：填进 `duration` 的数必须落在区间内，越界直接 400。
三层时长口径（请求 / 动作节拍 / 成片剪辑）见 §1.1。

| 模型 | 单镜上限 | 下限 | 备注 |
|---|---|---|---|
| MiniMax H3 / 海螺系（`minimax-h3`、`hailuo`、`MiniMax-Hailuo-2.3`） | **15 秒** | 4 秒 | 平台请求契约即 `4 ≤ duration ≤ 15` |
| Seedance 2.0（`seedance2.0`、`seedance-2.0`） | **15 秒** | 4 秒 | |
| Seedance 2.5（`seedance2.5`、`seedance-2.5`） | **30 秒** | 4 秒 | 另有 30–180 秒超长模式，需显式选择 |
| 未登记模型 | **10 秒** | 4 秒 | 保守值；宁可切碎也不要超限 |

> 代码侧的权威实现在 `backend/app/core/video_references.py` 的 `max_shot_seconds()`；
> 该表与 `providers/capabilities.py` 的 `max_duration_seconds` 及 `H3VideoRequest` 的字段边界保持一致。
> 注意 `seedance2.0` 与 `seedance2.5` 在供应商路由里属于**同一个 family**，只有版本号能区分时长能力。

### 镜头时长设计参考

> 下表是**成片剪辑时长（层③）**——剪辑台上一个镜头占多长。**这些数字一律不填进请求**：
> 不足 4 秒的镜头统一按 4 秒下单，多出来的素材在剪辑台裁掉。

| 镜头类型 | 成片时长 |
|---|---|
| 建立镜（远景/全景） | 3–4 秒 |
| 叙事镜（中景） | 2–3 秒 |
| 情绪镜（近景/特写） | 2–3 秒 |
| 台词镜 | 每 10 字约 2 秒 |
| 强调镜（特效/高潮） | 3–5 秒 |
| 转场镜 | 1–2 秒 |
| 高风险动作镜 | 1.5–2.5 秒 |

### 段落节奏

> 同为**成片剪辑时长（层③）**：说的是剪辑节奏，不是让你去下十几条 2 秒的生成请求。

| 段落类型 | 成片镜头时长 |
|---|---|
| 快节奏（动作、悬疑） | 以 1–2 秒镜头为主，快速剪辑营造紧张感 |
| 慢节奏（抒情、对话） | 3–4 秒，营造舒缓或沉思氛围 |
| 展示性（开场、过场） | 2–3 秒，平稳传递视觉信息 |
| 核心奇观（变身、大招） | 3–5 秒，完整呈现视觉概念 |

---

## 二、质量锚点尾串

每条视频提示词结尾都挂。风格词一旦选定，**全片不得更换**。

### 完整版（写实电影感）

```text
电影胶片质感，变形宽银幕镜头，青橙分级，硬光动机光源，暗部保留细节，35mm胶片颗粒，
自然运动模糊，高清，细节丰富，电影质感，硬光大光比，低饱和，画面铺满无黑边
```

### 可替换位

| 位置 | 可选值 |
|---|---|
| 色彩分级 | 青橙分级 / 冷蓝分级 / 暖金分级 / 高对比黑白 |
| 光质 | 硬光 / 柔光 / 漫射 |
| 颗粒 | 35mm胶片颗粒 / 16mm粗颗粒 / 数字无颗粒 |
| 光比 | 硬光大光比 / 中光比 / 低光比通透 |
| 饱和 | 低饱和 / 中饱和 / 高饱和撞色 |

### 精简版（上下文吃紧时）

```text
电影质感，{色彩分级}，暗部保留细节，自然运动模糊，高清，画面铺满无黑边
```

### 稳定性尾串（必挂，不可省）

```text
人物面部稳定不变形、五官清晰、动作连贯自然，不僵硬，无穿模无卡顿；
保持无字幕，避免生成任何文字或字幕，不要生成水印，不要生成 Logo；
视频全程禁止出现外形、着装、配饰完全一致的人物，禁止生成同款分身、双胞胎效果，
同一画面中仅保留单个对应人物，不出现人物重复复刻。
```

---

## 三、负面提示词（按模块取用）

| 模块 | 负面词 |
|---|---|
| 人脸 | `face distortion, changing face, inconsistent face, extra teeth, deformed mouth, unnatural smile, crossed eyes, dead eyes` |
| 肢体 | `extra fingers, missing fingers, deformed hands, extra limbs, rubber limbs, broken anatomy, twisted joints` |
| 动作 | `floating motion, sliding feet, stiff robotic movement, frame interpolation artifacts, 动作发虚` |
| 画面 | `flickering, warping background, morphing objects, low resolution, oversaturated, plastic skin, black bars, 黑边` |
| 文字 | `subtitles, captions, watermark, logo, text overlay, signature` |
| 分身 | `duplicated character, twin, clone, repeated identical person, mirrored duplicate` |
| 连贯 | `jump cut, time skip, teleporting, changing outfit, changing hairstyle, axis flip, broken eyeline, disappearing prop, scene reset` |
| 武器 | `weapon deformation, morphing blade, floating weapon` |

### 通用串（拼一条就够用）

```text
face distortion, changing face, extra fingers, deformed hands, extra limbs, broken anatomy,
floating motion, stiff robotic movement, flickering, warping background, morphing objects,
oversaturated, plastic skin, black bars, subtitles, captions, watermark, logo, text overlay,
duplicated character, twin, clone, jump cut, changing outfit, changing hairstyle, axis flip,
broken eyeline, disappearing prop, scene reset
```

---

## 四、失败诊断表

| 症状 | 成因 | 修法 |
|---|---|---|
| 面部漂移 / 换脸 | 提示词里重述了长相，与参考图冲突 | 删掉长相描述，只用 `<主体N>` 代号引用；挂 `consistent face` |
| 手指畸形 | 手部动作描述过细但没约束 | 减少手部特写；挂手部负面词；改用中景 |
| 越轴 / 左右翻转 | 未锁定站位 | 显式写 `{A}始终位于画面左侧`；挂 `axis flip` 负面 |
| 动作发虚 / 滑步 | 只写了动作名，没写受力 | 补物理反馈（重心、扬尘、擦地、衣料）；缩短镜头时长 |
| 武器形变 | 武器与手的关系没锁 | 写明 `{武器}恒定在{左/右}手，刃面朝向{方向}`；挂武器负面 |
| 镜头莫名切换 | 单镜里塞了多个动作或多个地点 | 拆镜，一镜只推进一个小动作 |
| 口型不同步 | 台词没用 `{}` 包裹，或时长不够 | 用花括号；按每 10 字 2 秒核对时长 |
| 画面黑边 | 画幅与素材比例不符 | 挂 `画面铺满无黑边`；统一画幅比例 |
| 风格漂移 | 各镜风格词不一致 | 把质量锚点尾串固定成常量，全片同一串 |
| 背景人物复制 | 群演没有约束 | 挂 `背景人物各不相同，不出现重复面孔` + 分身负面 |
| 主角旁边多出一个一模一样的人 | 多角色同框的典型失败 | 挂完整防分身串（见 §二 稳定性尾串） |
| 生成超时 / 内容被截断 | 单镜超过模型时长上限 | 按 §一 拆镜 |
| 情绪突变 | 中间的过渡镜被省略 | 按 `发现→反应→消化→决定→行动` 补镜 |
| 道具凭空消失 | 道具位置未锁 | 写明道具恒定手别与位置；挂 `disappearing prop` 负面 |

---

## 五、切镜决策速查

出现下列任一情况就切新镜：

1. 角色情绪显著转变（平静→震惊→愤怒，每一跳一镜）
2. 复杂动作（按 准备→执行→结果 拆）
3. 人物增减，或主导/从属、对话/聆听关系转换
4. 空间转场（另加 1–2 秒专用转场镜）
5. 时间跳跃（次日、多年后、并行时间线）
6. 说话人更替或长台词中的语气转折（视线乒乓）
7. 景别、机位角度或运动方式发生有意义的改变
8. 视觉特效独占瞬间（爆炸、关键道具特写）
9. **本镜预估时长超过所选模型上限**

---

# 附：完整词典与扩展条目

> 上文为速查版（分镜阶段按预算截断时优先保留）；以下为完整版。

> 本文件是**单镜时长上限、素材位上限、质量锚点尾串、负面词库、失败诊断**的权威源。
> 分镜切分（九宫格 → 单镜）必须先查 §1.1 拿到上限，再决定一个镜头能不能一次生成出来。
> 提示词组装的最后一步必须挂 §二（质量锚点尾串）的尾串 + §三（负面提示词模块库）的兜底负面串。出片不合格先查 §四（失败诊断），**禁止盲目重roll**。

## 0. 三条硬规则

| # | 规则 | 原因 |
|---|---|---|
| 1 | **每个分镜都必须能被所选模型「一次」生成出来** | 超上限的请求会被直接 400 拒绝；超长镜头必须先按 §1.2 拆分 |
| 2 | **一次只改一个维度** | 失败诊断的前提是可归因；整段重写会让你不知道哪条修法生效 |
| 3 | **两次修法无效就换路线，不要第三次重roll** | 见 §4.5 替代路线表；同一提示词第三次重试的边际收益接近零 |

---

## 一、视频模型能力与单镜时长上限

### 1.1 单镜时长上限（平台裁镜权威表）

| 模型 | 平台归一化别名（子串匹配，最长别名优先） | 单镜下限 | **单镜上限** | 超长模式 | 口径来源 |
|---|---|---:|---:|---|---|
| **MiniMax H3**（海螺） | `minimax-h3` / `minimax h3` / `hailuo` / `h3` | 4s | **15s** | 无 | 平台 `VIDEO_MODEL_MAX_SHOT_SECONDS`；`providers/capabilities.py` 记 `min_duration_seconds=4, max_duration_seconds=15`；`H3VideoRequest.duration_seconds` 声明 `ge=4, le=15`（默认 6s） |
| **Seedance 2.0** | `seedance2.0` / `seedance-2.0` / `seedance2` / `seedance` | 4s | **15s** | 无 | 平台 Ark 网关对 duration 做 `max(4, min(15, int(duration)))` 钳制；越界值（如 3s）会被 400 拒 |
| **Seedance 2.5** | `seedance2.5` / `seedance-2.5` | 4s | **30s** | **超长视频 30–180s**（单次生成，非强制 15s 切分） | 官方手册标准生成 4–30s；超长视频为独立模式 |
| **未登记 / 未知模型** | 任何未命中上表别名的模型 id | 4s | **10s（保守默认）** | 未知 | `DEFAULT_MAX_SHOT_SECONDS = 10`。切碎只是多几个镜头，切长会让请求直接失败 |

**下限统一为 4s**：`MIN_SHOT_SECONDS = 4` 是已知最严格的地板值，比它更短的镜头会在提交时被拒。

**三层时长口径（不要混用）：**

| 口径 | 含义 | 取值 |
|---|---|---|
| **生成请求时长** | 一次 API 调用的 `duration` | **≥ 4s（地板，更短直接 400）且 ≤ 模型上限** |
| **动作单元时长** | 一次调用里承载的动作量 | 2–4s 只做 1 个动作节拍；🟢 低危可到 5s |
| **成片剪辑时长** | 时间线上一个镜头的呈现长度 | 1–3s（转场 1–2s、高风险动作镜 1.5–2.5s、命中慢动作 0.5s） |

> **成片剪辑时长 ≠ 生成请求时长。** 1.5–2.5 秒的动作镜不是向模型请求 1.5 秒，而是**请求 4 秒素材、在剪辑台上裁出 1.5 秒**。本文件与 SKILL.md 中所有 <4s 的数字一律属于第三层，不得直接写进请求体。

**Seedance 2.5 帧数锚点**：标准生成使用 **97–721 帧** 覆盖 4–30 秒。官方示例按 **24fps** 给帧锚（30 秒 = 720 帧）。只有当提示词或制作单确立了 24fps 时才可假设该帧率。

**三层时长口径（全技能唯一权威；任何一处出现的秒数，先归到这三层之一再读）**

本技能里的秒数分属三个互不通约的层。混层是所有时长矛盾的总根源：把剪辑台上的 1.5 秒当成请求参数填进
`duration`，请求直接 400 被拒；把 4 秒的请求地板当成动作节拍，一段里就会塞进两个动作单元，中段必糊。

| 层 | 名称 | 数值 | 谁消费它 | 越界后果 |
|---|---|---|---|---|
| **①** | 生成请求时长（request duration） | **≥ 4s 且 ≤ 本节该模型上限**，整数秒 | 模型 API 的 `duration` 字段 | 低于 4s 或高于上限，请求被 400 拒，不产生任何素材 |
| **②** | 动作单元 / 节拍时长（action beat） | **2–4s**；🟢 低危动作（对峙、慢动作、影子暗示）可放宽到 **5s** | 提示词内部的时间轴（`0-2秒：…` / `2-4秒：…`） | 短于 2s：糊动（motion mush）、动作被整段跳过；长于上限：帧间位移累积，关节与道具形状崩坏 |
| **③** | 成片剪辑时长（cut duration） | **1–3s**（转场镜、打击慢动作可到 0.5s） | 剪辑台时间线的 in / out 点 | 无越界后果——它从层①的素材里裁出来，**永不作为请求参数** |

**三层的换算关系**：一次层①请求（例如 4s）内部排 1–2 个层②动作单元，出片后在剪辑台裁成一个或多个层③镜头。
所以「1.5 秒的高风险动作镜」的正确做法是：**按 4s 下单生成，剪辑台只留 1.5s，其余 2.5s 丢掉**——
而不是提交一条 `duration=1.5` 的请求。层③永远不上传。

| 技能里的常见说法 | 属于哪层 | 正确读法 |
|---|---|---|
| 转场镜 1–2 秒 | ③ | 成片上占 1–2 秒；生成时仍按 4s 下单 |
| 高风险动作镜 1.5–2.5 秒 | ③ | 快切节奏，剪辑台裁出；生成时仍按 4s 下单 |
| 叙事中景 2–3 秒 / 情绪特写 2–3 秒 | ③ | 成片节奏参考；生成请求取 4s |
| 快节奏段落以 1–2 秒镜头为主 | ③ | 剪辑节奏，不是十几条 2 秒请求 |
| 每段 2–4 秒只做 1 个动作单元 | ② | 提示词内部的节拍；整段作为一次请求提交时取 4s |
| 一个 5 秒镜头 = 一个动作 | ② | **仅限 🟢 低危动作**；🟡 / 🔴 压回 2–4s |
| 每个独立物理动作留时 2–4 秒 | ② | 下限保动作被看清，上限保动作不崩 |
| 建立镜 3–4 秒 / 强调镜 3–5 秒 | ②→① | 节拍写 3–5s，请求向上取到 ≥ 4s |
| H3 4–15s、Seedance 2.5 4–30s | ① | 唯一能填进 `duration` 的数 |

**一条镜头同时有三个时长是正常的**，分镜表里必须分栏写清楚：请求 4s / 节拍 2s / 成片 1.5s。
只写一个数字，下游一定会拿错那一层。

### 1.2 超长镜头拆分规则（总时长守恒）

平台 `split_shot_seconds(duration, model)` 的行为，写分镜时必须按同一逻辑预判：

| 步骤 | 规则 |
|---|---|
| 1 | `cap = max_shot_seconds(model)`；`total ≤ cap` → 不拆，返回单段 |
| 2 | `total > cap` → 段数 `parts = ceil(total / cap)` |
| 3 | `base, remainder = divmod(total, parts)`，前 `remainder` 段各 +1 秒 |
| 4 | **总时长恒定不变**——一个镜头因为要拆分而改变整集时长是 bug，不是特性 |

**拆分示例：**

| 原镜时长 | 模型 | 拆分结果 | 说明 |
|---:|---|---|---|
| 22s | Seedance 2.5（cap 30） | `[22]` | 不拆 |
| 22s | Seedance 2.0（cap 15） | `[11, 11]` | 2 段均分 |
| 22s | MiniMax H3（cap 15） | `[11, 11]` | 同上 |
| 40s | Seedance 2.5（cap 30） | `[20, 20]` | 不是 `[30, 10]`——均分更稳，避免 10s 段内容密度崩塌 |
| 25s | 未知模型（cap 10） | `[9, 8, 8]` | 保守默认下会切成 3 段 |

**拆分后的接缝必须写交接状态**，否则第 2 段会重置位置/朝向/动量（见 §4.2 第 14 行）：

```text
参考@视频1，向后延长[新增秒数]秒。提示词仅作用于新增部分，原视频保持不变。
交接状态：@视频1的尾帧中，[角色位置、朝向、动作动量、镜头运动、光线、声音]。
0-X秒：[无切镜地延续动作与运镜]。
X-N秒：[新增事件和收束]。
保持@视频1的[身份、服装、场景地理、光照、色调、声音]一致；禁止生硬切镜、位置重置或物体凭空出现。
```

### 1.3 各模型素材位与请求参数（本平台适配器口径）

| 维度 | MiniMax H3 | Seedance 2.0（Ark 适配器） | Seedance 2.5（官方手册） |
|---|---|---|---|
| 参考图 | ≤ 9 | ≤ 9 | **≤ 30** |
| 参考视频 | ≤ 3 | ≤ 3 | **≤ 10** |
| 参考音频 | ≤ 3 | ≤ 3 | **≤ 10** |
| 混合文件总数 | **≤ 12**（`mixed_files`；结构化绑定 `reference_bindings` 同为 ≤ 12） | 按分项限制 | **手册未规定 12 文件混合总上限**——不要把 2.0 的混合总量规则复用到 2.5 |
| 首帧 / 尾帧 | 独立字段 `first_frame` / `last_frame` | content 内 `role: first_frame` / `last_frame` | 首尾帧为独立模式 |
| 分辨率 | `720p` / `1080p` / `2k`（默认 `1080p`） | 顶层 `resolution` 字段 | **480p / 720p**（参数表口径） |
| 画幅 | `9:16` / `16:9` / `1:1`（默认 `9:16`） | 顶层 `ratio` 字段 | 由平台设置项控制；超长视频允许在开头重申时长与画幅 |
| 原生音频 | `native_audio` 默认开 | — | 支持纯音频多模态生成（图/视频不再是必需项） |
| 水印 | — | 顶层 `watermark: false`，成片不打可见水印 | — |
| 提示词长度 | `prompt` ≤ 20000 字符 | — | **手册未声明字数上限**，不执行旧的 500 字 / 1000 词限制 |
| 随机种子 | `seed` 0–2147483647 | — | — |
| 支持模式 | text / first_frame / first_last_frame / multi_reference / multimodal | 同左 | 见 §1.4 模式清单 |
| 平台接入状态 | `integrated` | `integrated` | `integrated`（**具体端点配置为各 Seedance 版本的权威口径**） |

**Seedance 2.0 请求协议红线**（违反直接 400）：

| # | 红线 | 报错 / 后果 |
|---|---|---|
| 1 | `resolution` / `duration` / `ratio` / `watermark` **必须走请求体顶层字段** | 写成 text 里的 `--flags` 命令行参数会被拒 |
| 2 | content 文本对象**必须携带 `style_caption` 字段** | 否则报 `InvalidParameter.BodyFormat`（`it must contain style_caption field`） |
| 3 | `duration` 必须落在 4–15 | 分段产生 3s 这类越界值会被 400 拒，平台已做钳制 |
| 4 | 严禁在动作描述里裸写 `[asset-xxx]` | 底层模型不能关联无语义 Asset ID，必须通过 `@图片N` / `<主体N>` 桥接 |

**平台默认 `style_caption`（写实排卡 / Anti-Anime Filter）：**

```text
真实电影质感，实拍写真，photorealistic live-action cinematic film still, real human skin texture, natural lighting, 35mm film grain, shallow depth of field; 绝非动画、绝非卡通、绝非3D渲染、绝非插画、绝非草图 (not anime, not cartoon, not 3d render, not illustration, not sketch)
```

### 1.4 Seedance 2.5 官方硬限明细（手册口径，与 §1.3 平台口径冲突时以端点配置为准）

**输出时长：**

| 模式 | 时长 | 备注 |
|---|---:|---|
| 标准生成 | 4–30s | `duration=-1` 可能代表平台自动时长；用户要求精确时长时**不要**使用 |
| 超长视频 | 30–180s | 独立「超长视频」模式，一次生成，非强制 15s 切分 |
| 视频延长的源片 | ≤ 30s | 只有不超过 30s 的源 / 当前结果才能被延长 |
| 单次新增延长量 | 4–30s | UI 上的时长指的是**新增区间**，不是最终总长 |
| 延长后结果 | ≤ 60s | 上限示例：30s 源 + 30s 延长 |

**图片输入：** 单张 < 30MB；宽高比 0.4–2.5；宽高 300–6000px；格式 jpeg / png / webp / bmp / tiff / gif / heic / heif；30 图工作流建议控制在 4K 以内。

**视频输入：** 单条名义 2–30s（实际容差 1.8–30.2s）；全部参考视频总时长名义 ≤ 30s（容差 ≤ 30.2s）；格式 mp4 / mov；分辨率 480p–4K；宽高比 0.4–2.5；宽高 300–6000px；总像素 409,600–8,295,044；单条 ≤ 200MB；帧率 24–60fps。

**音频输入：** 单条 ≤ 30s；全部参考音频总时长 ≤ 30s；格式 wav / mp3；单条 ≤ 15MB。

**支持模式清单：** 全能参考 / 智能编辑 / 超长视频 / 首尾帧 / 视频延长 / 本地视频高级编辑 / 已生成结果的视频编辑 / 空间视角修改 / BGM 分离移除 / 创意迁移 / 多角色参考 / 音色参考 / 绿幕编辑 / 粗细白模控制 / 两段素材无缝转场 / 多格分镜输入。

**语言行为：**

| 层级 | 语种 |
|---|---|
| 优先优化 | 中文、英文、西班牙语、印尼语、马来语 |
| 支持覆盖 | 泰语、阿拉伯语、葡萄牙语、越南语、日语、韩语 |

支持母语导演式提示词。目标语言台词与字幕必须显式写出准确文本，并绑定说话人与发音 / 演绎意图。

**素材 token：** 使用平台 UI 实际插入的 token，中文界面典型为 `@图片1`、`@视频1`、`@音频1`。**不要**推断编号必须停在旧版 9 / 3 / 3 上限。

### 1.5 稳定性建议区间（质量建议，非上传拒绝限制）

| 场景 | 稳定区间 | 高风险区间 |
|---|---|---|
| 来自视频 / 音频的不同主体数 | 1–5 | 6–10，可能需要更多次尝试 |
| 主体视频 / 音频参考时长 | 5–10s | 更长的参考可能降低稳定性 |
| 来自图片的不同主体数 | 1–8 | 9–12，可能需要更多次尝试 |
| 用于编辑的视频 | ≤ 20s | 更长的片段可能降低编辑保留度 |
| 视频编辑用参考图 | 1–5 | 6–8 可能降低稳定性 |

> 超过 5 个主体时，**把多角度视图拆到多张图**：多张单视图图片比一张多视图拼贴稳定得多。
> 平台侧素材配置建议：4–5 个素材（角色图 1–2 张 = 大头照 + 全身照，场景图 1，运镜视频 1，音频 1），**不建议把素材位用满**。

### 1.6 明确标注为「未验证 / 存疑」的项

| 项 | 仓库口径 | 执行策略 |
|---|---|---|
| `720P+` | UI 走查里出现该标签，参数表只写 480p / 720p | **按参数表执行**，在单独验证前不得声称官方支持 1080p |
| `duration=-1` | 可能代表平台自动时长 | 用户要求精确长度时**不要**使用 |
| 提示词字数上限 | 手册未声明任何上限 | **不执行**旧的 500 字符 / 1000 词限制 |
| Maya / Blender 白模插件 | 手册有链接，但未文档化 CLI 命令与模型通道名 | 未经官方核实，**不得把旧 CLI 命令当作 2.5 事实发布** |
| 12 文件混合总上限 | 是 Seedance **2.0** 的规则 | 校验时按 2.5 的**分项**限制走，不复用 2.0 的混合总量规则 |
| 逐文件图片 / 音频规格 | 出现在手册「未变更」规格列 | 当作当前有效运行限制，通过更新数据源来同步变化，不要静默猜测 |
| 身份绑定与审核细则 | 手册演示了照片级真人生成，但未定义全部身份绑定 / 审核规则 | 区分虚构生成人物与真人肖像；可识别真人需授权，公众人物 / 版权角色 / 品牌 / 暴力 / 性内容按当前平台政策执行 |

### 1.7 其他模型族（本平台尚未接入，走保守 10s）

| 族 | 别名 | 图 / 视频 / 音频位 | 接入状态 | 备注 |
|---|---|---|---|---|
| kling | `kling-o1` / `kling o1` / `kling3` / `kling-3` / `kling` | 7 / 3 / 3 | `adapter_required` | 所查 O1 指南未把音频列为条件输入 |
| grok | `grok-imagine-video` / `grok imagine` / `grok` / `gork` | 7 / 0 / 0 | `adapter_required` | `Gork` 归一化为 Grok 的用户侧别名 |
| happyhorse | `happyhorse-1.1` / `happyhorse-1.0` / `happy horse` | 9 / 3 / 3 | `adapter_required` | 公开端点各不相同，提交前必须做能力探测 |
| ltx_2_3 | `ltx-2.3` / `ltx2.3` / `ltx-2-3` | 9 / 0 / 1 | `adapter_required` | 多图分镜路由取决于配置的 LTX 2.3 运行时能力 |
| custom（未知） | 任意未命中别名 | 1 / 0 / 0 | `capability_probe_required` | **未知模型对高级参考模式 fail closed**，能力配置好之前只走 text / first_frame |

---

## 二、质量锚点尾串

### 2.1 尾串三段式结构

任何一条最终提示词的结尾都由三段拼成，顺序固定，**不可打乱**：

```text
[风格锚：画风 + 画幅 + 调色 + 颗粒 + 快门 + 光比 + 饱和 + 铺满]
；[稳定锚：面部 + 五官 + 动作 + 穿模卡顿]
；[兜底锚：字幕 + 水印 + Logo + 分身双胞胎]
```

| 段 | 治什么病 | 是否默认必挂 |
|---|---|---|
| **风格锚** | 塑料感 / 廉价电视剧感 / 风格漂移 / 黑边 | 必挂（题材替换调色词，见 §2.5） |
| **稳定锚** | 面部漂移 / 五官糊 / 动作僵硬 / 穿模卡顿 | 必挂 |
| **兜底锚** | 凭空字幕 / 水印 Logo / 同款分身双胞胎 | 水印 Logo 必挂；字幕、双胞胎按场景挂载 |

### 2.2 完整质量锚点尾串（满配版 · 直接复制）

```text
电影胶片质感，变形宽银幕（anamorphic 2.39:1），青橙分级（teal and orange color grading），35mm胶片颗粒，自然运动模糊（180°快门），硬光大光比，低饱和，画面铺满无黑边；人物面部稳定不变形、五官清晰、动作连贯自然，不僵硬，无穿模无卡顿；保持无字幕，避免生成任何文字或字幕；不要生成水印；不要生成 Logo；视频全程禁止出现外形、着装、配饰完全一致的人物，禁止生成同款分身、双胞胎效果，同一画面中仅保留单个对应人物，不出现人物重复复刻。
```

**竖屏 9:16 项目专用版（删掉宽银幕，避免模型自己加 letterbox 黑边）：**

```text
电影胶片质感，9:16竖屏满幅构图，青橙分级（teal and orange color grading），35mm胶片颗粒，自然运动模糊（180°快门），硬光大光比，低饱和，画面铺满无黑边、无边框、不加letterbox；人物面部稳定不变形、五官清晰、动作连贯自然，不僵硬，无穿模无卡顿；保持无字幕，避免生成任何文字或字幕；不要生成水印；不要生成 Logo；视频全程禁止出现外形、着装、配饰完全一致的人物，禁止生成同款分身、双胞胎效果，同一画面中仅保留单个对应人物，不出现人物重复复刻。
```

### 2.3 尾串词条逐条释义（每个词治哪个病）

| 词条 | 英文/参数对照 | 治什么 | 什么时候必须删 |
|---|---|---|---|
| 电影胶片质感 | `cinematic film still` | 廉价电视剧感、肥皂剧打光 | 三渲二 / 卡通 / 动态漫画项目 |
| 变形宽银幕 | `anamorphic 2.39:1` | 构图平庸、缺电影感 | **竖屏 9:16 项目必删**（与「画面铺满无黑边」直接冲突） |
| 青橙分级 | `teal and orange color grading, warm highlights and cool cyan shadows` | 色彩发灰、无商业大片感 | 悲情 / 肃杀 / 年代题材（换 §2.5 其他调色锚） |
| 35mm 胶片颗粒 | `35mm film grain` | 数码塑料感、过度平滑 | 电商 / 产品锐利质感；三渲二 |
| 自然运动模糊 | `natural motion blur, 180° shutter` | 动作抽帧、瞬态崩坏 | 需要逐帧锐利定格的镜头 |
| 硬光大光比 | `hard key light, high contrast lighting` | 平光（`flat lighting`）、无立体感 | 柔和治愈 / 日系文艺题材 |
| 低饱和 | `desaturated / muted colors` | AI 过饱和、廉价艳俗 | 竖屏高饱和快节奏题材（喜剧、甜宠） |
| 画面铺满无黑边 | `full bleed, no letterbox, no border` | 黑边、边框、主体被裁 | 刻意做 letterbox 风格时 |
| 人物面部稳定不变形 | — | 面部漂移、换脸、面具感 | 从不删 |
| 五官清晰 | — | 五官错位、糊脸、死鱼眼 | 从不删 |
| 动作连贯自然，不僵硬 | — | 假人姿势、机械感、面瘫 | 从不删 |
| 无穿模无卡顿 | — | 肢体穿模、掉帧、抽搐 | 从不删 |
| 保持无字幕 | — | 凭空生成的乱码字幕 | **文字生成任务（广告语 / 字幕 / 气泡）必删**，否则自相抵消 |
| 不要生成水印 / Logo | — | 训练数据残留的水印、角标 | 从不删（默认必挂） |
| 禁止同款分身双胞胎 | — | 群演复制粘贴、同款角色重复 | 单人单主体镜头可删 |

### 2.4 尾串分级裁剪表 —— 什么时候裁、裁到哪一级

> **裁剪的唯一动机是抢注意力权重。** 提示词越长，前面的镜头指令权重越低（镜头指令失效的三大成因之一）。当一条提示词已经很长、或运镜 / 时间戳指令开始不生效时，**先裁尾串，不要裁正文**。

| 级别 | 用在哪 | 内容 |
|---|---|---|
| **满配版** | 单镜独立生成、首镜定调、关键帧 Stage 1 | §2.2 全量 |
| **标准版** | 路径 B 三段论的第三段（全片挂一次，分镜内不重复） | `电影胶片质感，[调色锚]，35mm胶片颗粒，硬光大光比，低饱和，画面铺满无黑边；人物面部稳定不变形、五官清晰、动作连贯自然，不僵硬，无穿模无卡顿；保持无字幕，不要生成水印，不要生成 Logo。` |
| **精简版** | 路径 A 单镜简单请求；长提示词末尾折叠 | `高清电影质感，画面稳定无变形，保持无字幕，不要生成水印，不要生成 Logo。` |
| **极简版** | 提示词已逼近注意力窗口、运镜指令开始失效 | `暖色调电影质感，画面稳定无变形，无字幕、无水印。` |
| **Stage 2 版** | 关键帧两阶段法的 I2V 动作层 | **只保留稳定锚 + 兜底锚，删掉全部风格 / 光影 / 调色锚**（光影已锁在 Stage 1 的定帧里，重复写会让运镜改光） |

**裁剪触发条件表：**

| 触发信号 | 动作 |
|---|---|
| 运镜 / 时间戳指令不生效 | 尾串降一级；把镜头指令上移到一句话概述之后 |
| 走关键帧两阶段法的 Stage 2 | 强制降到 Stage 2 版 |
| 走 Seedance 2.0 且已填 `style_caption` | 风格锚放 `style_caption`，正文尾串只留稳定锚 + 兜底锚，**不要两处重复写风格** |
| 文字生成任务 | 删掉「保持无字幕」整句 |
| 单人 / 单主体镜头 | 删掉双胞胎兜底整句 |
| 三渲二 / 卡通 / 动态漫画 | 删掉全部写实材质与胶片词，换 §2.6 的 NPR 锚 |
| 路径 B 三段论 | 尾串**只在第三段挂一次**，禁止每个分镜重复挂 |

### 2.5 按题材替换调色锚（风格锚里唯一需要换的槽位）

| 调色方案 | 适用 | 可直接复制的提示词 |
|---|---|---|
| **Teal and Orange（青橙 · 动作格斗黄金配色）** | 动作、格斗、商业大片 | `Teal and Orange color grading, high contrast cinema grading, warm highlights and cool cyan shadows, cinematic blockbuster look` |
| **Bleach Bypass（低饱和灰绿 / 银盐保留）** | 悲情、冷峻、肃杀 | `bleach bypass film style, desaturated colors, muted mossy greens and cold blue tones, raw film texture` |
| **Golden Hour Warmth（黄金时刻）** | 温馨、希望、回忆 | `Golden Hour lighting, warm sunset glowing hues, soft orange light rays, Kodak Portra 400 film tones` |
| **Neon Teal & Magenta（霓虹紫青）** | 赛博、虚幻都市、夜景 | `neon color scheme, vibrant teal and magenta reflected glow on wet ground, cross-processed colors, cyber atmosphere` |
| **Monochromatic Sodium Vapor（单色钠灯）** | 废墟、荒凉、历史厚重 | `sodium vapor monochromatic tones, deep high-contrast dark-yellow lighting, gritty rusty textures` |

**色调层公式（三层光影结构的第三层）：**

| 风格 | 色调公式 |
|---|---|
| 灾难 / 压迫 | 冷蓝底调 + 熔岩红高光 |
| 赛博朋克 | 冷蓝底调 + 霓虹紫红高光 |
| 仙侠 / 奇幻 | 暗青底调 + 金色/荧光高光 |
| 末日 / 恐怖 | 灰绿底调 + 暗红强化 |
| 暖色 / 史诗 | 暗棕底调 + 橙金高光 |
| 高级灰 | 低饱和灰调 + 微暖高光 |
| 梦幻 / 童话 | 柔粉底调 + 金色微光 |
| 社媒鲜亮 | 高饱和底调 + 强对比高光 + 微暖偏移 |

### 2.6 品质冲突矩阵（组装尾串时必须交叉检查）

> 矛盾的品质词组合会让模型输出四不像。

| 冲突对 A | 冲突对 B | 为什么冲突 | 解决方案 |
|---|---|---|---|
| **变形宽银幕 2.39:1** | **9:16 竖屏 + 画面铺满无黑边** | 模型会自己加 letterbox 补足宽银幕比例 | **竖屏项目删宽银幕**，改写「9:16 竖屏满幅构图」 |
| IMAX 65mm 极致清晰 | VHS 模拟降解 | 一个要极致锐利，一个要刻意降解 | 二选一，不可混用 |
| UE5 写实光追 | 水墨宣纸笔触 | 一个物理渲染，一个抽象二维 | 二选一；要融合写「3D渲染水墨质感」 |
| 胶片颗粒 + 有机噪点 | 锐利数码电商质感 | 一个要粗粝不完美，一个要完美无瑕 | 电商禁胶片，影片禁数码锐 |
| 手持晃动 / Handheld | 绝对对称构图 | 运镜与构图逻辑矛盾 | 对称构图强制用三脚架 / 云台 |
| Slow Motion 慢镜头 | Speed Ramp 变速 | 同一时间切片内不可同时慢和加速 | 分时间切片使用，不在同段重叠 |
| 三渲二 Cel-Shade / 卡通渲染 | 写实 PBR 材质 / SSS / 皮肤毛孔 / 微瑕疵 | 一个刻意简化光影材质，一个追求物理精确 | 二选一；三渲二提示词**禁用写实材质词** |
| 硬光大光比 | 平光 / soft flat lighting | 光比逻辑矛盾 | 二选一 |
| 低饱和 | 高饱和竖屏浓艳 | 饱和度目标相反 | 按载体选：竖屏短剧倾向高饱和，院线质感倾向低饱和 |

> 若用户坚持矛盾组合，在导演阐述中主动说明取舍和风险，不要静默丢弃其中一条。

### 2.7 反塑料感 / 反 AI 假脸禁用词表

**以下泛化词应替换为物理描述：** `4K` / `8K` / `masterpiece` / `best quality` / `ultra HD` / `超清晰` / `杰作` / `极致画质`。
（若 `4K` 只是描述输入参考文件规格，不要误判为输出分辨率或硬错误。）

**为什么：** 这些词缺少可执行的光线、材质与运动信息，会挤占提示词注意力，且不能稳定保证真实质感。

**正确做法：** 用 **物理介质型号 + 光学瑕疵 + 有机质感** 替代。真实感来源于不完美（Organic Imperfections）。

**动作抽象词同样禁用：** `激烈打斗` / `激烈格斗` / `精彩对决` / `酣战` / `飞踢` / `降龙十八掌` / `fierce fight` / `intense combat` / `epic battle`。

**替代方向：** 一律换成可见的具象物理词——`拳风破空`、`剑气斩击`、`掌击命中躯干`、`前臂格挡后下沉半寸`、`地面碎裂`、`身体弓形后弹`。

**原因与画质词相同：** 这些词不含任何可执行的力学、方向或接触信息，只会挤占提示词注意力，模型用「假人比划」填补歧义。写实题材另补一条负面词 `不要卡通化的物理效果 / no cartoonish physics`。

**四条 AI 表情陷阱（写实项目严禁出现）：**

| 陷阱 | 修正 |
|---|---|
| 完美对称的面部表情 | 真人面部永不完全对称——用 `左侧嘴角微微上扬` 替代 `嘴角上扬` |
| 情绪瞬间切换、没有过渡 | 真人需要 0.3–1.5 秒肌肉过渡——**至少留 1–2 秒过渡** |
| 皮克斯式夸张表情（嘴巴大张、眉毛飞天、眼睛圆瞪） | 除非动画风格，写实中严禁 |
| 面瘫式静态面部（持续数秒完全不动） | 真人始终有微小呼吸起伏、眨眼、肌肉波动 |

**有机瑕疵词（每条提示词至少用 1–2 个）：**

| 类别 | 瑕疵 | 英文提示词 |
|---|---|---|
| 光学 | 胶片红色光晕 | `Cinematic halation` |
| 光学 | 变形宽银幕眩光 | `Anamorphic lens flares` |
| 光学 | 桶形畸变 | `Barrel distortion` |
| 光学 | 周边暗角 | `Natural optical vignetting` |
| 物理 | 毛孔皮肤 | `Realistic skin texture with visible pores and micro-imperfections` |
| 物理 | 汗水反光 | `Sweat glistening on skin surface` |
| 物理 | 微尘飘浮 | `Floating dust particles caught in light` |
| 物理 | 织物微纤维 | `Fabric micro-fiber detail under light` |
| 物理 | 发丝光泽 | `Individual hair strands catching light` |
| 环境 | 雨滴玻璃 | `Rain droplets trickling down glass surface` |
| 环境 | 凝结水雾 | `Condensation fog on cold surfaces` |
| 环境 | 落叶碎屑 | `Scattered leaves and organic debris` |
| 环境 | 光柱灰尘 | `Dust motes drifting through shafts of light` |

**两套可直接复制的反塑料感组件：**

```text
# 人像反塑料感套件
Shot on Kodak Portra 400, realistic skin texture with visible pores, sweat glistening on forehead, cinematic halation, fine organic film grain, floating dust particles in warm backlight
```

```text
# 夜景反塑料感套件
Shot on Cinestill 800T, anamorphic lens flares, red halation around neon signs, rain droplets on lens surface, natural optical vignetting, visible film grain
```

### 2.8 胶片型号锚点（比笼统「胶片质感」精准得多）

| 胶片型号 | 英文提示词 | 色彩签名 | 最佳场景 |
|---|---|---|---|
| 柯达 Portra 400 | `Shot on Kodak Portra 400` | 温润自然肤色，柔和过渡，低对比 | 人像 / 情感戏——绝杀 AI 蜡像脸 |
| Cinestill 800T | `Shot on Cinestill 800T` | 暖色调，霓虹高光处红色晕影（halation） | 夜景 / 赛博朋克 / 霓虹街头 |
| 柯达 Vision3 500T | `Shot on Kodak Vision3 500T` | 电影工业标准色彩，宽容度，自然还原 | 通用叙事 / 院线质感 |
| 富士 Pro 400H | `Shot on Fuji Pro 400H` | 清冷淡雅，薄荷绿偏移，柔和高光 | 日系文艺 / 小清新 |
| 柯达 Ektachrome E100 | `Shot on Kodak Ektachrome E100` | 高饱和幻灯色彩，锐利颗粒 | 复古广告 / 60–70 年代美学 |

> **全片只选一种胶片型号**，写进连续性圣经。不同镜头用不同胶片型号是风格漂移的主要成因之一。

### 2.9 尾串放置位置规则

| 场景 | 尾串放哪 |
|---|---|
| 路径 A 单镜（一段式） | 折叠在整句末尾，一两句串联即可，**不要分块罗列** |
| 路径 B 三段论 | 集中挂在**第三段**，全片一次；分镜内部不重复 |
| 关键帧两阶段 Stage 1（T2I 定帧） | 风格锚 + 光影 + 材质**全部集中在这里** |
| 关键帧两阶段 Stage 2（I2V 动作） | **只留稳定锚 + 兜底锚**；补一句 `运镜指令仅控制摄影机轨迹，不改变光源位置或色调基准` |
| Seedance 2.0 API | 风格锚走顶层 `style_caption`；正文尾串只留稳定锚 + 兜底锚 |
| 超长视频（30–180s） | 允许在**开头**重申时长与画幅；尾串仍挂在末尾的「全局连续性」段 |

---

## 三、负面提示词模块库

### 3.1 使用四原则

| # | 原则 |
|---|---|
| 1 | **不要一次性堆满所有负面词**，按场景筛选模块 |
| 2 | 先用「通用底包」，再叠加「人物」「肢体」「文字水印」「分身」「物理时序」等模块 |
| 3 | 写实影视优先压制：卡通感、塑料感、低清晰度、结构错误、时序漂移 |
| 4 | 若模型支持权重，把最关键问题加权：`bad hands:1.4`、`deformed face:1.3` |

**基础搭配公式：**

```text
通用负面词 + 人物结构负面词 + 题材补充负面词 + 视频连续性负面词（仅视频）
```

### 3.2 通用负面词串（中文 · 平台默认 · 直接复制）

> 国产模型（即梦 / 可灵 / Vidu / Wan / Seedance）多有独立中文负面输入框，中文识别良好。

```text
低质量, 最差质量, 模糊, 失焦, 低分辨率, 噪点, 压缩失真, 过曝, 欠曝, 画面脏, 灰蒙蒙, 偏色, 过饱和, 平光, 构图混乱, 主体被裁切,
变形, 扭曲, 畸形, 结构错误, 比例失调, 多余的肢体, 缺失的肢体, 断肢, 塑料感, 蜡像感, 假, 卡通感, 3D渲染感, 游戏画面,
脸部扭曲, 五官错位, 五官不对称, 斜眼, 死鱼眼, 眼神空洞, 嘴巴歪斜, 牙齿畸形, 表情僵硬, 面瘫, 皮肤蜡感, 过度磨皮, 换脸痕迹, 面具感,
畸形的手, 多余手指, 缺失手指, 手指粘连, 六根手指, 手部扭曲, 多余头部, 多余手臂, 姿态僵硬, 假人姿势, 关节反向, 脖子过长, 头身比例错误,
画面闪烁, 抖动, 卡顿, 掉帧, 重影, 鬼影, 时序拖影, 撕裂, 诡异蠕动, 人物长相前后不一致, 换脸, 身份漂移, 服装突变, 发型突变, 场景突变, 背景漂移,
物体忽大忽小, 颜色跳变, 光照不稳定, 脚底打滑, 违反物理的运动, 动作不连贯, 物体瞬移,
水印, 文字, 字幕, logo, 签名, 黑边, 边框, 画面被裁切,
人物重复复刻, 同款分身, 双胞胎效果, 群演复制粘贴, 背景人物重复, 同一画面出现两个相同角色
```

**极简版（长度受限平台）：**

```text
低质量, 模糊, 变形, 畸形, 结构错误, 多余的肢体, 脸部扭曲, 死鱼眼, 表情僵硬, 皮肤蜡感, 畸形的手, 多余手指,
画面闪烁, 时序拖影, 换脸, 身份漂移, 场景突变, 光照不稳定, 塑料感, 卡通感, 3D渲染感, 水印, 文字, 字幕, logo, 黑边
```

### 3.3 分类模块（中文）

| 模块 | 何时挂 | 词串 |
|---|---|---|
| **人物 · 面部** | 任何有脸的镜头 | `脸部扭曲, 五官错位, 五官不对称, 斜眼, 死鱼眼, 眼神空洞, 双下巴异常, 嘴巴歪斜, 牙齿畸形, 表情僵硬, 面瘫, 表情狰狞, 皮肤蜡感, 过度磨皮, 假毛孔, 换脸痕迹, 面具感` |
| **人物 · 肢体** | 有手部 / 大幅动作 | `畸形的手, 多余手指, 缺失手指, 手指粘连, 六根手指, 手部扭曲, 多余头部, 多余手臂, 断肢, 姿态僵硬, 姿势不自然, 假人姿势, 关节反向, 脖子过长, 头身比例错误` |
| **画面 · 画质光影** | 默认必挂 | `低质量, 最差质量, 模糊, 失焦, 低分辨率, 噪点, 压缩失真, 过曝, 欠曝, 画面脏, 灰蒙蒙, 偏色, 过饱和, 平光, 构图混乱, 主体被裁切, 塑料感, 蜡像感, 卡通感, 3D渲染感, 游戏画面` |
| **文字 · 水印** | 非文字生成任务必挂 | `水印, 文字, 字幕, logo, 签名, 黑边, 边框, UI, 界面, 台标, 角标` |
| **分身 · 群像** | 多人 / 群演场景必挂 | `人物重复复刻, 同款分身, 双胞胎效果, 群演复制粘贴, 背景人物重复, 同一画面出现两个相同角色, 长相接近的角色, 表情完全一致的群演, 肢体交叠穿模, 幽灵人, 半透明身体, 残缺人体` |
| **物理 · 时序**（视频专用） | 所有视频任务必挂 | `画面闪烁, 抖动, 卡顿, 掉帧, 重影, 鬼影, 时序拖影, 撕裂, 抽搐, 诡异蠕动, 人物长相前后不一致, 换脸, 身份漂移, 服装突变, 发型突变, 场景突变, 背景漂移, 物体忽大忽小, 颜色跳变, 光照不稳定, 脚底打滑, 违反物理的运动, 动作不连贯, 物体瞬移, 无动机切镜, 镜头无故漂移, 变焦抽搐, 背景拉扯, 背景融化` |
| **道具 · 武器** | 武打 / 持械镜头必挂 | `软塌的武器, 橡胶质感兵器, 融化的兵器, 兵器忽长忽短, 兵器形状改变, 道具闪烁, 道具换手, 握持方式错误, 悬浮的武器, 道具比例失真` |
| **表演** | 情绪戏 / 对白戏 | `表演浮夸, 表情夸张, 表情包脸, 卡通式反应, 面无表情, 无生命感的表演, 演技僵硬, 动作机械, 眼神游移不自然, 口型对不上, 嘴型错误, 假哭, 假笑, 情绪不连贯, 情绪跳变, 反应时机错误` |

> **「残影」分两种，负面词只压其中一种。** 上表压的是**时序伪影**（帧插值鬼影、重影、时序拖尾、撕裂）：`ghost trails, duplicate frames, frame interpolation artifacts, motion tearing`。
> **刻意的速度残影**（`motion trail / afterimage / 衣袂横拖 / 速度线`）是动作戏的**正向词**，写在正文里，**不得同时出现在负面串中**——同时出现会正负相消，出招轨迹整条消失（见 §3.7「正负不冲突」）。
> 同理，`excessive motion blur` 已从时序串中移除：它与尾串的「自然运动模糊（180° 快门）」直接打架，压掉的正是动作戏要的那一部分模糊。

### 3.4 分类模块（英文 · 适配需要英文负面框的模型）

**通用底包：**

```text
worst quality, low quality, normal quality, lowres, blurry, out of focus, soft focus, pixelated, noisy, grainy,
jpeg artifacts, compression artifacts, oversharpen, overprocessed, overexposed, underexposed, bad lighting, flat lighting,
muddy colors, washed out, dull colors, oversaturated, color banding, lens dirt, sensor dust,
watermark, logo, text, subtitles, captions, UI, interface, frame, border, cropped, cut off,
bad composition, cluttered background, messy scene, unnatural pose,
deformed, distorted, malformed, disfigured, mutation, broken anatomy, bad anatomy,
extra limbs, extra fingers, missing fingers, fused fingers, missing limbs, disconnected limbs,
long neck, twisted body, broken body, duplicated body, duplicate person, clone face,
unnatural expression, dead eyes, asymmetrical face, bad perspective, warped perspective,
wrong shadows, inconsistent shadows, inconsistent reflections, fake reflections,
plastic skin, waxy skin, uncanny valley, cartoonish, CGI look, game render, 3d render, toy-like, doll-like
```

**面部：**

```text
bad face, deformed face, asymmetrical face, distorted face, melted face, blurry face, double face, duplicate face,
extra face, disfigured face, wrong facial proportions, warped jaw, crooked mouth, misaligned eyes, cross-eyed,
uneven eyes, dead eyes, empty eyes, glassy eyes, extra eyes, uneven eyebrows, malformed nose, bad lips, fused lips,
uneven teeth, extra teeth, bad ears, extra ears, asymmetrical ears, strange smile, creepy expression
```

**手部与肢体：**

```text
bad hands, poorly drawn hands, malformed hands, mutated hands, extra fingers, missing fingers, fused fingers,
broken fingers, twisted fingers, giant hands, tiny hands, extra arms, missing arms, broken arms, dislocated joints,
extra legs, missing legs, twisted legs, broken knees, malformed feet, extra feet, floating limbs, detached limbs, duplicated limbs
```

**多人 / 群像（分身兜底）：**

```text
duplicate people, cloned faces, repeated extras, copy-paste crowd, identical expressions, merged bodies,
overlapping bodies, intersecting limbs, missing person parts, floating heads, broken interactions,
incorrect eye lines, looking in wrong direction, awkward spacing, crowd collision, tangled limbs, fused characters,
inconsistent scale, background character collapse, malformed background people, random extra hands, random extra faces,
ghost people, transparent body, incomplete body
```

**文生视频 / 图生视频时序：**

```text
frame flicker, temporal inconsistency, character drift, identity drift, face drift, costume drift, hairstyle drift,
object drift, background drift, scene morphing, random transformation, shape shifting, unstable anatomy,
limb flicker, hand flicker, eye flicker, mouth flicker, facial warping, melting motion, rubber motion, glitch motion,
ghost trails, motion tearing, frame interpolation artifacts, duplicate frames, missing frames, stutter, judder,
unnatural motion blur, frozen body parts, floating motion, sliding feet, foot skating,
body jitter, teleporting objects, prop popping, object disappearance, object mutation, camera jump,
random camera movement, broken continuity, inconsistent lighting across frames, texture crawl, pattern shimmer,
background wobble, face replacement artifacts
```

**动作 / 武打 / 战争：**

```text
fake action pose, frozen action, impossible combat stance, soft weapon, rubber weapon, bad impact, no weight, no force,
floating debris, wrong muzzle flash, unrealistic recoil, duplicated soldiers, repeated explosions, cheap explosion,
fake smoke, low-detail fire, disconnected fight choreography, body clipping, impossible collision, foot sliding, broken stunt motion
```

**表演：**

```text
overacting, exaggerated expression, meme face, comedy face, cartoon reaction, blank expression, emotionless face,
lifeless performance, stiff acting, awkward gesture, robotic gesture, unnatural eye movement, broken lip sync,
incorrect mouth shapes, fake crying, fake anger, fake smile, inconsistent emotion, expression drift,
emotional mismatch, wrong reaction timing
```

**镜头语言：**

```text
bad cinematography, poor framing, awkward framing, amateur camera, security camera look, webcam look, phone camera look,
flat composition, weak depth, incorrect focus, focus hunting, unstable focus, wrong lens distortion, fisheye distortion,
stretched edges, bad bokeh, fake depth of field, bad rack focus, shaky camera, random zoom, abrupt zoom, camera jitter,
Dutch angle misuse, unmotivated camera angle, broken shot continuity, inconsistent shot scale, wrong eyeline match, poor blocking
```

**题材补充：**

| 题材 | 词串 |
|---|---|
| 古装 / 仙侠 | `modern hairstyle, modern makeup, modern fabric, zipper, plastic ornament, cheap armor, inaccurate hanfu, wrong dynasty costume, synthetic embroidery, game armor, cosplay look, stage play look, cheap wig, plastic jewelry, modern architecture, modern props, historical inconsistency` |
| 都市 / 现实 | `soap opera lighting, studio set look, cheap TV drama look, over-beautified face, beauty filter, idol drama filter, artificial apartment, fake office, showroom furniture, stock-photo look, ad-like scene, overposed characters, too clean environment, fake realism` |
| 悬疑 / 惊悚 | `cheap horror effect, cheesy blood, fake blood texture, bad wound makeup, unintended comedy, cartoon darkness, muddy darkness, unreadable shadows, random gore, oversaturated red, fake smoke, fake rain, low-detail night scene, flashlight inconsistency, unstable darkness` |
| 科幻 / 赛博 | `cheap sci-fi, toy spaceship, fake hologram, bad neon, overdesigned UI, floating meaningless interface, random glowing lines, plastic armor, cosplay sci-fi, game cutscene look, low-detail mech, repeated assets, cluttered cyberpunk, oversaturated blue-purple palette, noisy neon lighting` |

### 3.5 按任务挂载矩阵

| 任务 | 通用 | 面部 | 肢体 | 群像分身 | 文字水印 | 时序 | 武器 | 表演 | 题材 |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| 角色定妆 / 五视图 | ● | ● | ● | ● | ● | ○ | ○ | ○ | ● |
| 单人静态镜头 | ● | ● | ○ | ○ | ● | ● | ○ | ○ | ● |
| 对话镜头（双人） | ● | ● | ○ | ● | ● | ● | ○ | ● | ● |
| 群像 / 宴会 / 战场 | ● | ● | ● | ● | ● | ● | ● | ○ | ● |
| 武打 / 动作 | ● | ● | ● | ● | ● | ● | ● | ○ | ● |
| 情绪特写 | ● | ● | ○ | ○ | ● | ● | ○ | ● | ● |
| 文字生成（广告语 / 字幕 / 气泡） | ● | ● | ○ | ○ | **删「字幕」项，只留 watermark/logo** | ● | ○ | ○ | ● |
| 视频延长 / 编辑 | ● | ● | ○ | ● | ● | ● | ○ | ○ | ○ |

（● = 必挂，○ = 按需）

### 3.6 关键压制项优先级

1. `bad anatomy`　2. `bad hands`　3. `deformed face`　4. `plastic skin`　5. `temporal inconsistency`（视频）
6. `identity drift`（视频）　7. `flat lighting`　8. `CGI look`　9. `warped background`　10. `text, watermark, logo`

### 3.7 负面词红线

| 红线 | 说明 |
|---|---|
| **正向优先于负向** | 先写「保留什么」再写「不迁移什么」。`完全参考@视频1` 这类无排除项的绑定是素材污染的头号成因 |
| **正负不冲突** | 尾串写了「35mm 胶片颗粒」就不能在负面里写 `film grain`；写了「硬光大光比」就不能写 `high contrast` |
| **文字任务不挂字幕兜底** | 否则正负相消，字幕出不来 |
| **第三方网关需先过 Sanitizer** | Agnes / Gemini 类网关审核极敏感：`passport photo` / `headshot` / `not a real person` 等身份词，以及 `杀` / `死` / `暴力` / `重拳打脸` / `羞辱` 等冲突词会被判违规 400。发送前必须用动作词清洗器替换（如「重拳砸烂脸颊」→「双手与手臂的快速物理碰撞」），保留正向写实画风与分镜 |

---

## 四、失败诊断

### 4.1 诊断流程（禁止盲目重roll）

| 步 | 动作 |
|---|---|
| 1 | **识别症状** —— 看输出，对到 §4.2 的某一行 |
| 2 | **追溯成因** —— 判断是提示词哪一段引起的 |
| 3 | **定点修法** —— **只改相关那一段**，不要整段重写 |
| 4 | **两次迭代无效 → 换路线** —— 查 §4.5 |

> 结构化诊断提升通过率；盲目重roll 只是浪费算力。**一次迭代只测一条修法。**

### 4.2 失败诊断主表：症状 → 成因 → 修法

| # | 症状（画面表现） | 成因 | 提示词层修法 | 流程 / 后期层修法 | 两次无效 → 替代路线 |
|---|---|---|---|---|---|
| 1 | **面部漂移**：镜头 5 的人和镜头 1 明显不是同一个人；同角不同脸、同脸不同装、年龄感变化 | 身份只写在文字里没有视觉锚；身份属性散落在提示词各处；视频 / 创意迁移参考污染外貌；长片未在幕边界重申不变量 | 提供清晰正面打光的身份参考图并显式绑定范围：`@图片1 → 角色A的面孔、发型、体型 → 全片`；加 2–3 个跨镜持久的**唯一物理标记**（疤痕 / 配饰 / 纹身 / 服装细节）并写进连续性圣经；长片在**每一幕开头**重申身份；用视频参考时写 `不要迁移@视频1中的人物外貌` | 人脸参考用 **大头照 + 全身照**，**禁用三视图 / 多视图**（易触发 ID 漂移与双胞胎）；锁定优先级：**首帧垫图 ＞ LoRA/FaceID ＞ 固定 Seed ＞ 纯文字**；同一场景所有镜头集中在一个 batch 生成 | **关键帧两阶段法**：先 T2I 出定帧锁身份，再作为 `@图片1` 走 I2V |
| 2 | **手指畸形**：多指 / 少指 / 粘连；手臂反关节；肢体与物体融合；动作中途比例突变 | 动作描述太笼统，模型用伪影填补歧义；动作在给定时长内超出物理可信度；多个动作同时叠加 | 因果链拆解：`右手从口袋中缓慢抽出信封 → 五指握住信封上缘 → 手臂向前平伸递出`，禁止只写「拿出信封」；**指明左右手与手指**；同时并发的肢体动作降到 1 主 + 1 辅（3 个并发显著提升畸形率）；手部关键时加 `双手始终保持自然的五指结构` | **能藏则藏，非必要不特写手部**；负面词 `bad hands:1.4` 加权 | 粗白模 previs 先锁运动骨架，再走白模渲染管线 |
| 3 | **越轴**：上一镜 A 在左 B 在右，下一镜突然 A 在右 B 在左，方向感颠倒 | 每个镜头独立渲染，模型不继承上一镜的空间关系；提示词未声明轴线与方位 | 三段论里写**强方位约束**：`左侧角色穿灰蓝色作训服`、`@图片2 中的女生位于画面左侧`；显式写 `角色A看向右侧，角色B看向左侧`；用 **OTS 过肩镜头**作安全过渡镜锁死轴线：`Over-the-shoulder shot (OTS), looking from behind foreground character's shoulder at the target`；配合**固定机位** | 相邻镜头逐一比对 A/B 的左右屏幕相对位置是否恒定；**后期水平镜像翻转**（Premiere / CapCut）是最简单高效的兜底 | 建场景 Top-Down 视图标注所有机位，或插入中性正面 / 俯视镜后再换侧 |
| 4 | **动作发虚 / 糊动**：动作幅度不足、方向不明；人物像在「挪」而不是在「做」；运镜存在但泛泛无方向 | 动作缺强度修饰词；运镜指令泛化（只写「镜头跟随」）；短时间窗塞了太多微动作 | 每个动作加**强度修饰**：`猛然起身` 而非 `起身`，`explosive stride` 而非 `moves forward`；写清**方向 / 速度 / 距离**：`向画面左侧大步迈出三步` 而非 `走过去`；运镜用「一级动作 + 二级修饰」：`快速手持跟拍` 而非 `镜头跟随`；**每个独立动作至少留 2–3 秒** | 情绪外化成具体身体细节（悲伤 → 肩膀微微颤抖、眼眶泛红、手指攥紧衣角），不写抽象情绪词 | 拆成两个更短的片段，用无缝转场拼接 |
| 5 | **武器形变**：刀剑软塌 / 橡胶感 / 忽长忽短 / 中途变形；握持方式错误、道具换手 | 兵器没有材质、长度、刚体锚；高速挥砍帧模型不知道它是刚体；打击瞬间无环境反馈 | 写死物理属性：`直刃长剑，钢制刃身反光，剑长约一米，刚体不可弯折，全程不改变形状与长度`；挥砍加轨迹锚：`blade cutting through air, glowing kinetic wind trail, shockwave warping the air (refraction effect), speed lines flashing in background`；负面挂 `soft weapon, rubber weapon, melted weapon, floating weapon, changing prop shape, prop flicker` | 每个打击 / 蓄力动作必须带**环境物理负反馈**（尘土、碎石、落叶、雨滴、水墨粒子）；重击命中瞬间降速 0.25x 持续 0.5s；撞击帧加 1–2 帧轻微缩放或色偏模拟冲击波 | 粗白模锁定兵器轨迹后再渲染 |
| 6 | **镜头莫名切换**：要求单镜到底却出现跳剪；运镜指令完全没执行（`dolly zoom` 出成静态；`orbit` 变成简单摇） | 一镜叠加多种运镜；英文运镜术语触发内容安全误判（裸写 `Dolly` / `Crane` / `Aerial` 被误读为人名/品牌）；运镜指令埋在长提示词深处丢失注意力权重；运镜路径在所述空间里物理不可能 | **一镜一运镜**（推 / 拉 / 摇 / 移 / 固定 / 跟拍择一），禁止叠加；用安全表述 `推轨推进` / `dolly tracking shot` 替代裸写 `Dolly`；把运镜指令**上移**到一句话概述之后或每个时间戳节拍的第一元素；显式写 `全程单镜到底，不切镜，不跳剪`、`禁止无动机切镜`；确认运镜物理可行（360° 环绕需要主体周围有足够空间）；**缩短提示词**（先裁 §2.4 尾串） | 事件密度降到 2–3 秒一个动作 | 提供演示该运镜的视频参考并绑定 `@视频N仅参考运镜轨迹` |
| 7 | **口型不同步**：台词与嘴型明显对不上；语速过快糊嘴；语速过慢出现「停顿脸」 | 生成时输入的不是最终台词；台词时长与镜头时长不匹配；改台词后未重生；多语言配音未重新适配口型 | **生成视频时就输入最终台词**；台词用 `{}` 包裹（`{你好，世界}`），小语种标注语种；显式写 `口型与目标语言发音同步`；把语速当**时长约束**写：`[镜头3秒-中速-口型清晰] "我，不会走。"`（3 字一顿，卡满 3 秒）；角色不说话时也要写微表情 / 呼吸，别让脸僵住 | 用中景 / 侧面镜头降低口型可见度；后期 Wav2Lip / Sync Labs / HeyGen 修正；改台词后**必须重新检查口型** | 转头、遮挡、远景等弱化口型暴露的机位重拍该镜 |
| 8 | **画面黑边**：上下或左右出现 letterbox 黑边；主体被裁切；画面没铺满 | 提示词同时出现「变形宽银幕 / 2.39:1 / letterbox」与竖屏画幅；正文画幅与顶层 `ratio` 参数冲突；横屏素材裁成竖屏 | **竖屏 9:16 项目删掉「变形宽银幕」**，改写 `9:16竖屏满幅构图`；尾串保留 `画面铺满无黑边、无边框、不加letterbox`；负面挂 `黑边, 边框, 主体被裁切, letterbox, cropped, cut off` | 画幅走**顶层 `ratio` 字段**，不要在正文里再声明一次相冲的比例；**从分镜阶段就按 9:16 设计构图**，禁止横屏拍完裁竖屏 | 重新出定帧，用正确画幅的首帧驱动 I2V |
| 9 | **风格漂移**：镜头间光线方向 / 色温 / 画风突变；暖调黄金时刻突然变冷蓝；动漫场景漂到写实 | 光影参数写在动作层而不是锁在视觉锚里；运镜提示词无意中重新定义了光源；不同镜头用了不一致的品质锚 / 胶片型号；中途更换基础模型 / CFG / 采样器；非写实风格未显式锚定 | 连续性圣经里把光源当不变量写死：`主光始终来自画面左上方30°、色温5600K暖白`；显式写 `运镜不改变光源方向或色调基准`；**全片选定同一个胶片型号 / 渲染引擎**并写进圣经；动漫 / 非写实场景**必挂风格锚定**（`2D 日漫风格` / `3D 国风漫画` / `赛博朋克冷蓝紫色调`） | **全片统一模型、CFG、采样器和风格词**——中途更改直接导致严重漂移；后期加「视觉胶水」统一层：一致的 Film Grain + 统一暗角 + 轻微 Bloom + 统一锐化；Deflicker 插件去闪烁；降低 CFG Scale 可减少帧间跳变 | **关键帧两阶段法**：出一张定义光影的 hero frame，作为该序列所有镜头的首帧参考 |
| 10 | **背景人物复制**：群演复制粘贴、同款分身、双胞胎；同一画面出现两个相同角色；背景人物崩坏 | 群演没有个体化描述，模型平铺复制；上传了三视图 / 多视图人物参考；同框人数过多导致 FaceID 失效 | **必挂双胞胎兜底串**：`视频全程禁止出现外形、着装、配饰完全一致的人物，禁止生成同款分身、双胞胎效果，同一画面中仅保留单个对应人物，不出现人物重复复刻`；给每个可见群演至少一条差异化描述；配合**强方位约束 + 固定机位** | **同框人数：主视角 2–4 人最佳，上限 ≤ 5 人**；参考人物 > 4 时先分组生图（每组 ≤ 4 人）再图生视频；人脸参考禁用三视图 / 多视图；用浅景深虚化背景降低注意力 | 拆成多镜单人正反打，避免多人同框 |
| 11 | **循环 / 静止**：人物重复同一个 2–3 秒动作；或人物完全冻结而镜头继续运动 | 提示词描述的是静态状态没有推进与因果；动作写成单一姿势而非有始有终的序列；时长过长而内容不够 | 保证每个节拍都有**状态变化**（首帧和尾帧必须不同）；动作写成过程而非状态：`她的手从桌面缓慢滑向信封边缘，指尖停在封口处` 而非 `她的手放在桌上`；长静默镜头补微动作（呼吸节奏、眼球微动、发丝被风吹、环境运动）；**每 3–5 秒至少一个新动作或变化** | 内容密度与时长匹配 | 缩短生成时长匹配内容密度，再用视频延长补第二段内容 |
| 12 | **时间线压缩**：本该 15 秒的事挤进 5 秒；动作仓促不完整；部分描述的事件被跳过 | 时长内塞了太多事件；时间分配不符合动作的物理现实；时间戳区间对内容不现实地短 | 用时间预算法：建置 10–15%、发展 25–35%、转折 10–20%、高潮 20–30%、收束 10–20%；数一下每个时间戳节拍里有几个独立动作，**5 秒窗内超过 2–3 个就会压缩**；关键时刻（情绪转折、揭示）至少留 3–5 秒专属时长 | 延长总时长或减少事件数 | 拆成两次生成，规划好交接点，而不是硬塞进一条提示词 |
| 13 | **素材污染**：参考视频的背景替换了预期场景；音色参考的内容覆盖了剧本台词；角色参考的服装跑到别的角色身上 | 参考绑定缺显式排除项；`完全参考@视频1` 没有告诉模型该忽略什么；两个参考对同一维度给出冲突属性 | 每个参考必须三字段绑定（**转什么 / 用在哪 / 不转什么**）：`参考@视频1的手部拉花动作（08–14秒）；不迁移人物外貌、背景、音轨和字幕`；冲突时声明优先级：`场景以@图片2为准；发生冲突时@图片2优先`；音色参考永远分角色：`@音频1仅参考声线，不作为BGM`；**正向白名单写法**（比堆负面词更省注意力）：显式声明「人物数量、武器形态、服装细节、场景元素、光感色调**全部以参考图为准，不增不减**」，再列出允许的动态元素——`动态元素仅限：衣袂残影、雨水飞溅、霓虹反光、速度线`，**未列入白名单的元素一律不生成** | 减少参考数量；5 个以上参考仍污染时，精简到 2–3 个核心参考，其余用文字描述 | 换成关键帧两阶段法，把参考的影响锁死在 Stage 1 |
| 14 | **动作不接续**：上一镜人物在走，下一镜突然站着；拆分后第二段位置重置 | 拆分 / 延长时未写交接状态；分镜脚本未记录每镜首尾动作状态 | 用 §1.2 的延长模板显式写**交接状态**（角色位置、朝向、动作动量、镜头运动、光线、声音）；分镜脚本里逐镜记录首尾状态 | 尾帧接首帧法（提取上一镜最后一帧作下一镜首帧）；加 2–4 帧动作补间；用运动转场（甩镜 Whip Pan / 推拉旋转）的运动模糊遮盖不连续 | 合并为一个更长的单镜（若不超模型上限） |
| 15 | **脚底打滑 / 物体瞬移 / 背景融化** | 运动幅度超出模型稳定区间；背景无空间锚；单镜时长过长；**运动幅度越大，模型越容易在空隙里脑补出参考图里没有的人物、道具与家具**——i2v 场景优先选「保风格 + 保人物」双重保留，运动幅度选**中**而不是大 | 优先**低缓连续小动作**，规避狂奔 / 大跳 / 剧烈翻滚等高爆发动态；补动作过渡衔接（`借着转身惯性顺势抬手`）；负面挂 `脚底打滑, 物体瞬移, 背景融化, sliding feet, foot skating, background wobble` | 缩短单镜时长；场景用参考图强约束；浅景深虚化背景 | 用白模锁动线后重渲 |
| 16 | **画面崩坏 / 特效糊成一团**：多种特效同时出现时人物边缘融化、特效互相穿插、主体被完全淹没 | 同一镜叠加了多种叙事特效（冲击波 + 剑气 + 雷光 + 抽色 + 粒子），模型的计算被分散到互相冲突的渲染目标上；粒子描述过重压过主体 | **一镜只留 1 种叙事特效**，其余特效摊到相邻镜；环境粒子只保留同一类（火星 / 灰尘 / 水花 / 碎屑择一），加 `subtle particle effects, main subject clearly visible`；特效必须标方向，不标方向的能量特效会被默认画成环绕 | 多种特效改在剪辑 / 合成层分层叠加，不要交给生成 | 拆成两镜：一镜给动作、一镜给特效奇观 |

### 4.3 复杂度分级与首发成功率（排镜时用来定风险）

| 层级 | 例子 | 相对成功率 | 建议 |
|---|---|---|---|
| Tier 1：静态环境 | 风景、建筑内景、产品 hero | 最高 | 可靠，单次生成即可 |
| Tier 2：单主体简单动作 | 一个人走路、转身、坐下 | 高 | 标准提示词通常够用 |
| Tier 3：单主体复杂动作 | 舞蹈、武打、精细手部操作 | 中 | 必须用强度修饰词 + 因果链 |
| Tier 4：多主体简单交互 | 两人对话、并肩行走 | 中 | 用角色台账 + 方位追踪 |
| Tier 5：多主体复杂交互 | 打斗、群舞、人群 | 较低 | 考虑关键帧两阶段法或白模管线 |
| Tier 6：极端物理 | 爆炸、流体、破坏、高速载具 | 最低 | 用 VFX 锚点，先用短片段试拍 |

> **长片项目**：先用简化测试提示词（更少动作、更短时长）验证基线，再加复杂度。避免因为一个根本性约束而让精心写的复杂提示词整条失败。

**平台侧镜头时长基准（读数前先按 §1.1 归层，「口径层」列已标好）：**

| 镜头类型 | 建议时长 | 口径层 |
|---|---|---|
| 竖屏普通镜头 | 1.5s – 4s | ③ 成片剪辑 |
| 高风险动作镜头 | 1.5s – 2.5s | ③ 成片剪辑 |
| 特定情绪长镜头 | ≤ 8s | ① 生成请求（取 4–8s，再与模型上限取更小值） |
| 动作戏 | **成片单镜绝不超过 3 秒**，分镜拆分率 > 80%，全片快切 | ③ 成片剪辑 |

> **这张表里只有「特定情绪长镜头」那一行能填进 `duration`。** 其余三行是层③剪辑台的 in / out 长度：
> 按 §1.1 的层① 4s 下单生成，多出来的素材在剪辑台裁掉。把 1.5s / 2.5s / 3s 当成请求参数提交，
> 会低于 `MIN_SHOT_SECONDS = 4` 的地板而被直接 400 拒——连素材都拿不到，谈不上快切。
> 「与模型上限取更小值」这条运算**只对层①成立**；层③的数字与模型上限不发生任何关系。

### 4.4 连续性保证度优先级（算力受限时按此取舍）

```text
角色 ＞ 光影 ＞ 调色 ＞ 背景 ＞ 动作
```

优先确保**角色脸部与服装**的一致性；背景物品位置漂移可接受「主要物品一致、细节可忽略」，并用浅景深虚化降低观众注意力。

### 4.5 替代路线速查

| 卡在哪 | 换到哪条路线 |
|---|---|
| 身份怎么都稳不住 | 关键帧两阶段（T2I 定帧 → I2V） |
| 复杂手部 / 身体交互总畸形 | 粗白模 previs 锁运动骨架 → 白模渲染管线 |
| 复杂动作序列反复发虚 | 拆成两个更短片段 + 无缝转场 |
| 光影 / 风格反复断裂 | 出一张 hero frame 定义光影，作为该序列所有镜头的首帧参考 |
| 运镜指令怎么写都不执行 | 提供演示运镜的视频参考，绑定 `@视频N仅参考运镜轨迹` |
| 事件塞不进时长 | 拆成两次生成 + 规划交接点 |
| 5 个以上参考持续污染 | 精简到 2–3 个核心参考，其余转文字描述 |
| 内容密度撑不满时长 | 缩短生成时长 → 用视频延长补第二段 |
| 越轴无法在生成端解决 | 后期水平镜像翻转 |
| 口型无法在生成端对齐 | 改中景 / 侧面机位 + 后期口型同步工具 |

### 4.6 出片前 60 秒快检清单

```text
□ 单镜时长 ≤ 所选模型上限（H3/2.0 = 15s，2.5 = 30s，未知 = 10s），且 ≥ 4s
□ 超长镜头已按 ceil 均分拆开，总时长未变
□ 素材数未超该模型的图/视频/音频位（H3 另有 12 文件混合总限）
□ Seedance 2.0：resolution/duration/ratio/watermark 在顶层字段，style_caption 非空
□ 提示词里没有裸写 [asset-xxx]，@图片N 后没有紧接动词/方位词
□ 一镜只有一种运镜；没有「推+拉+摇+移」叠加
□ 尾串已挂：风格锚 + 稳定锚 + 兜底锚（按 §2.4 选级别）
□ 竖屏项目：尾串里没有「变形宽银幕/2.39:1」，有「画面铺满无黑边」
□ 品质冲突矩阵已过一遍（胶片 vs 数码锐、写实材质 vs 三渲二、慢镜 vs 变速…）
□ 多人场景：双胞胎兜底已挂，同框 ≤ 5 人，强方位约束 + 固定机位
□ 非文字任务：字幕兜底已挂；文字任务：字幕兜底已删
□ 每个参考都有「转什么 / 用在哪 / 不转什么」三字段
□ 每 3–5 秒至少一个新动作或状态变化；5 秒窗内动作 ≤ 3
□ 相邻镜头的 A/B 左右屏幕相对位置恒定（防越轴）
□ 台词已是最终版本，语速与镜头时长匹配（口型）
□ 全片同一模型 / 同一胶片型号 / 同一风格锚（防漂移）
□ 第三方网关：提示词已过 Sanitizer 冲突词清洗
```