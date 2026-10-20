# MiniMax H3 原生提示词契约

> 来源：`h3-prompt-writing` 官方技能包（`references/base-en.txt` + `references/ref-en.txt`）。
> 这是 H3 **字段级**的硬契约——字段名、顺序、标签、时间记法**必须逐字保留**，不要翻译成中文字段名。
> 本项目 H3 的单镜时长为 **4–15 秒**（与 `H3VideoRequest.duration_seconds` 的 `ge=4, le=15` 一致）。

**语言规则**：改写段落用**英文**书写；只有 `<d>` 里的台词歌词、以及画面中实际可见的文字保留原文，不翻译。

---

## 一、先判定输入模式

| 模式 | 含义 |
|---|---|
| `T2VA` | 纯文字，从零构建完整视听时间轴 |
| `I2VA` | 首帧图 + 从首帧向前发展 |
| `FL2VA` | 首帧图 + 尾帧图，描述两者之间的连续路径 |
| `L2VA` | 尾帧图，反推一个合理的前置状态并收敛到尾帧 |
| `Ref2VA` | 全参考模式（多素材），走六段式 |

前四种走 §二「基础模式」，`Ref2VA` 走 §三「六段式」。

---

## 二、基础模式契约（T2VA / I2VA / FL2VA / L2VA）

### 2.1 第一部分：对齐指令（T2VA 没有这一段）

```text
# I2VA
For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.

# FL2VA
How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot N) aligns with the S.SS-second mark of the target video.

# L2VA
How the reference pictures align with the target video — <Picture 1> (from [Shot N]) aligns with the S.SS-second mark of the target video.
```

`N` = 实际最后一镜的序号；`S.SS` = 有效视频时长，**精确到两位小数**。指令必须是最终提示词的第一行，后跟一个空行再接核心字段。

### 2.2 第二部分：三个核心字段（顺序固定）

```text
integrated_multimodal_description: [Shot 1] ...

overall_soundscape: ...

non_diegetic_music: ...
```

| 字段 | 写什么 |
|---|---|
| `integrated_multimodal_description` | 沿时间轴描述画面、动作、镜头、说话人、对白、演唱与画内音 |
| `overall_soundscape` | 全片环境声、物理动作声、非语言人声的总结（1–4 句英文，一段） |
| `non_diegetic_music` | 角色听不到、只有观众听得到的配乐（1–3 句英文） |

### 2.3 关键帧写法

| 模式 | 推荐结构 |
|---|---|
| I2VA | 首帧锚定 → 动作起始 → 连续发展 → 结果或反应 |
| FL2VA | 首帧状态 → 可观察的中间变化 → 差异逐步收窄 → 尾帧状态 |
| L2VA | 合理的前置状态 → 明确的动作与过渡路径 → 末镜逐步收敛 → 落到尾帧 |

FL2VA **通常用单镜**，好让模型从首帧连续插值到尾帧；除非用户明确要求，不要多镜。

---

## 三、Ref2VA 六段式契约

六个段落，**顺序固定**：

| 段落 | 用途 |
|---|---|
| `subject_definitions` | 定义被参考内容及其引用标签 |
| `summary` | 概述任务类型、目标视频与主要参考关系 |
| `retention_analysis` | 说明被参考内容如何保留、迁移或复用 |
| `detailed_description` | 按播放顺序描述画面、动作、镜头、声音、对白 |
| `overall_soundscape` | 总结环境声与物理声 |
| `non_diegetic_music` | 只有观众听得到的配乐 |

### 3.1 四类引用标签

| 标签 | 含义 |
|---|---|
| `<Subject N>` | 从素材里抽象出来、可在目标视频中复用或修改的**可见内容** |
| `<Picture N>` | 作为具体目标帧或分镜规划锚点的参考图 |
| `<Video N>` | 提供剪辑源、续写起点或整片时间结构的参考视频 |
| `<Audio N>` | 被拷贝或参考的音频信号 |

标签一旦分配，在六个段落里**含义保持不变**。

```text
<Subject 1> is the young woman in <Picture 1>, with long dark hair, a blue cardigan, and a thin silver necklace.
<Subject 1> is the woman whose appearance comes from <Picture 1> and whose walking motion comes from <Video 1>.
<Picture 2> is the first frame of [Shot 1], showing a woman seated beside a café window.
<Picture 3> is a storyboard reference for [Shot 1] and [Shot 2], defining their viewpoint, subject placement, and shot order.
<Video 1> is the source video for the target video edit.
<Audio 1> is the voice-timbre reference for <Subject 1> (S1).
```

图片如果只用来定义角色/场景/服装/风格，**不要**单开一条 `<Picture N>`，把它写进对应 `<Subject N>` 的定义里。
`<Video N>` 与 `<Audio N>` 各自独立编号，同一个源视频可以是 `<Video 1>` 和 `<Audio 2>`。

### 3.2 `summary` 的任务类型前缀

以方括号任务类型开头，多个用 ` + ` 连接且不重复：

| 任务类型 | 何时用 |
|---|---|
| `keyframe completion` | 图片作为首帧/关键帧/尾帧等具体帧锚点 |
| `reference generation` | 图/视频/音频只提供生成指导（角色、场景、风格、动作、运镜、分镜） |
| `video editing` | 直接修改一个已有源视频 |
| `video continuation` | 从已有源视频续写、延长、接续 |
| `audio reuse` | 音频信号被全部或部分复用 |
| `audio reference` | 不直接复制，只参考music style/timbre/内容/节拍/连续性 |

```text
[reference generation] ...
[video continuation + keyframe completion] ...
[video editing + audio reuse] The target video is an edited version of <Video 1>. ...
```

> 参考视频只提供运镜/剪辑/节奏时属于 `reference generation`，**不要**写成 `video editing`。

### 3.3 `retention_analysis` 的关系标记

可见内容（`<Subject N>` / `<Picture N>` / `<Video N>`）：

| 标记 | 含义 |
|---|---|
| `fully_preserved` | 定义的引用角色完整保留 |
| `partially_preserved` | 仍在使用，但部分特征被改变或只部分保留 |
| `attribute_transfer` | 特征被迁移到另一个可识别的目标主体 |
| `weak_reference` | 只保留风格、类别、构图或氛围上的宽泛相似 |

音频（`<Audio N>`）：

| 标记 | 含义 |
|---|---|
| `fully_copy` | 源音频完整作为目标视频的最终音轨 |
| `partially_copy` | 只复制部分时间轴或部分音层，或复制后有增删替换 |
| `reference` | 不直接复制，只参考音色、节奏、风格、对白内容或声音质感 |
| `weak_reference` | 只保留类别或氛围上的宽泛相似 |

```text
<Subject 1> (appears in [Shot 1], [Shot 3]): fully_preserved - ...
<Picture 2> ([Shot 1] first frame): fully_preserved - ...
<Video 1> (cut and pacing structure): weak_reference - ...
<Audio 1>: fully_copy - <Audio 1> is reused 1:1 as the target video's complete final audio track.
```

**不要**在 `retention_analysis` 里写 `(Sx)`。

### 3.4 `detailed_description` 与基础模式的差别

| 维度 | T2VA | Ref2VA |
|---|---|---|
| 主字段 | `integrated_multimodal_description` | `detailed_description` |
| 风格开场 | 写在 `[Shot 1]` 之后 | 在 `[Shot 1]` **之前**用一两句英文确立 |
| 引用信息 | 不用全参考标签 | 在首次出现与生效处插入 `<Subject N>` / `<Picture N>` / `<Video N>` / `<Audio N>` |
| 音频关系 | 只描述目标视频自身的声音 | 在对应镜头引用 `<Audio N>` 并说明是复制还是参考 |

生成类任务的 `detailed_description` 通常 **350–500 个英文单词**。对白密集时以装下完整口白时间轴为准，不必机械凑字数。

帧锚点的自然写法：

```text
the shot begins from <Picture 1>
the shot's keyframe corresponds to <Picture 2>
the shot ends on <Picture 3>
```

---

## 四、镜头、运镜与切点（两种模式共用）

### 4.1 镜头与切点

首镜 `[Shot 1]` **不带时间戳**；后续镜头用严格递增的切点时间：

```text
[Shot 2] At 00:03.500, the camera cuts to...
```

普通切换用 `the camera cuts to` / `the shot cuts to` / `the shot transitions to` / `the shot changes to` / `the shot switches to`。用户明确要求时才用 cross-dissolve、fade、wipe。

> 切镜必须带来主体、空间、状态、视点或时间上的**新信息**。只是距离或角度略变，应该用运镜而不是切镜。

### 4.2 运镜三要素：类型 + 幅度 + 速度

| 维度 | 可用表达 | 说明 |
|---|---|---|
| 类型 | `Zoom In / Zoom Out` | 机身不动，焦距变化 |
| 类型 | `Push In / Pull Out` | 机身前进 / 后退 |
| 类型 | `Pan Left / Pan Right` | 机位不动，镜头水平转动 |
| 类型 | `Truck Left / Truck Right` | 摄影机水平平移 |
| 类型 | `Tilt Up / Tilt Down` | 机位不动，镜头垂直转动 |
| 类型 | `Pedestal Up / Pedestal Down` | 整个摄影机上升 / 下降 |
| 类型 | `Arc Shot` | 绕主体弧线运动 |
| 类型 | `Tracking Shot` | 跟随移动主体 |
| 类型 | `Static Shot` | 机位与镜头都不动 |
| 类型 | `Shake Slightly / Shake Strongly` | 轻微 / 强烈晃动 |
| 类型 | `POV` | 主体视角 |
| 类型 | `Roll Clockwise / Roll Counterclockwise` | 绕镜头轴滚转 |
| 幅度 | `with small amplitude` / `with large amplitude` | 中等幅度可省略 |
| 速度 | `at slow speed` / `at fast speed` | 常速可省略 |

运镜要写成镜头内的**自然英文动作**，不要在句尾堆标签：

```text
The camera pushes in with small amplitude at slow speed toward the folded letter in her hands.
The camera pans right with large amplitude at fast speed, revealing the open doorway.
The camera holds a static shot as the runner exits the frame.
```

---

## 五、说话人、对白与画面文字

### 5.1 说话人 ID

发声主体用稳定 ID `(S1)`、`(S2)`；多人齐声用 `(S1,S2)`。同一说话人跨镜保持同一 ID；从不发声的角色不给 ID。
ID 按**目标视频里实际发声事件的顺序**分配一次，之后复用。

首次出现时要交代可辨识身份：角色类型、年龄、性别、是否在画内、音高、音色、语速、口音。
**说话人的身份短语、ID、动作、语气写在 `<d>` 外面；`<d>` 里只放语言标签和实际台词内容**，逐字保留原文与标点，不翻译不改写。

```text
The young woman with a quiet, breathy voice (S1) says: <d>[English] I get off at the next station.</d>
The two children (S1,S2) shout together, <d>[English] Wait for us!</d>
```

Ref2VA 里被参考主体说话时，视觉标签与说话人 ID 同时保留：

```text
<Subject 2> (S1) turns toward the woman and says, <d>[English] Last summer, I went to my grandfather's house.</d>
```

### 5.2 画外音

固定短语 `says in an off-screen voiceover`，且**每个画外音 `<d>` 之后必须说明对应角色嘴唇闭合**：

```text
The man (S1) says in an off-screen voiceover: <d>[English] I still remember that road.</d> while his lips remain completely closed.
```

### 5.3 跨切点与截断

同一句台词跨越切点时，在两部分的衔接处都用 `<scenetrans>`，并明确说明音频跨切延续；被片尾截断的语音用 `<cutoff>`。
延续可用：`continues seamlessly across the cut` / `continues uninterrupted into the next shot` / `carries over from the previous shot` / `remains audible across the transition`。

### 5.4 画面文字

画面里真实可见的横幅、招牌、标签、字幕、霓虹字，放进**英文双引号**，逐字保留原文与标点，不翻译：

```text
A red neon sign reading "营业中" glows above the doorway.
```

### 5.5 复用参考音频的台词

直接复用参考音频的对白/旁白/歌词，或用户明确要求重演时，`<d>` 内**逐字保留源词与原语言**。听不清的片段写 `[unclear]`，不要猜测或转述。标点标准化为 `,` `.` `?` `!`，去掉重复波浪号、emoji、项目符号与装饰性标点；陈述/疑问/感叹句在 `</d>` 前分别以 `.` `?` `!` 收尾。
只参考音色、节奏、情绪或语气时，**不要**把源台词搬进目标视频。

---

## 六、声音两段的边界

- `overall_soundscape`：全片环境声、物理动作声、非语言人声（风、雨、车流、脚步、衣料、撞击、呼吸、笑声、喘息）。**对白、演唱、画内音乐不在这里重复**，它们属于主描述字段。只有用户明确要求全片静音时才写 `N/A`。
- `non_diegetic_music`：只写乐器编制、速度、节奏、力度变化；**不要**用抽象情绪词，也不要解释配乐的情绪功能。角色能听到的演唱、乐器、收音机、电视、手机音乐属于画内事件，写进主描述。没有配乐时写 `N/A`。

```text
overall_soundscape: Steady rain taps against the café windows while low room ambience continues underneath. The entrance bell rings once, followed by wet footsteps and the soft scrape of a chair.

non_diegetic_music: Sparse piano notes at a slow tempo, joined by sustained low strings that gradually increase in volume before fading out.
```

参考音频同时提供两类内容时，在各自对应的段落分别说明关系：

```text
overall_soundscape: The copied ambience layer from <Audio 1> continues throughout the target video.
non_diegetic_music: <Audio 2> is directly reused as the complete audience-only score.
```

---

## 七、完整范例（I2VA）

```text
For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.

integrated_multimodal_description: [Shot 1] Live-action, cinematic, the young woman shown in <Picture 1> remains beside the rain-covered train window, preserving her appearance, clothing, seat position, and the carriage layout. The camera trucks right with small amplitude at slow speed as she lifts her gaze from the folded letter toward the passing city lights. Her reflection moves across the glass while the quiet, breathy young woman (S1) says: <d>[English] I get off at the next station.</d> She folds the letter along its existing crease.

overall_soundscape: The train wheels produce a steady metallic rhythm beneath a low ventilation hum. Rain ticks against the window while paper rustles softly in her hands.

non_diegetic_music: Sustained cello notes at a slow tempo with widely spaced piano tones, gradually decreasing in volume.
```

---

## 八、常见错误

| 错误 | 正确做法 |
|---|---|
| 把字段名译成中文 | 字段名、标签、关系标记一律保留英文原文 |
| 首镜写了时间戳 | `[Shot 1]` 不带时间戳，从 `[Shot 2]` 起才写 `At MM:SS.mmm` |
| 把语气、身份写进 `<d>` 里 | `<d>` 内只有语言标签 + 台词本身 |
| 用 `cinematic`、`beautiful` 这类抽象词充数 | 换成具体的视觉与听觉细节 |
| 时长与描述不匹配 | 描述总时长必须等于请求时长（H3 为 4–15 秒） |
| 参考标签前后不一致 | `<Picture 1>` 等标签在所有段落里保持同一含义 |
| 画外音没写嘴唇闭合 | 每个画外音 `<d>` 之后补一句嘴唇保持闭合 |
| 在 `retention_analysis` 里写 `(Sx)` | 该段不出现说话人 ID |
| 对白在 soundscape 段重复 | 台词歌词只出现在主描述字段的 `<d>` 内 |
