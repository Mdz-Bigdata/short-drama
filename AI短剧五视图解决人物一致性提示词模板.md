# AI 短剧：通过五视图解决人物一致性问题

> 本文已由三视图规范升级为五视图规范。文件名为兼容既有项目路径而保留，文档内容与代码统一使用“五视图”。

## 1. 核心原则

AI 短剧的人物一致性不能依靠每一镜重新描述角色，而应先建立稳定的角色视觉锚点。每个角色必须有一张严格的五视图角色设定板，五个视图从左到右固定为：

1. 正面（front view，0°）；
2. 正面四分之三（front three-quarter view，约 45°）；
3. 标准侧面（standard profile view，90°）；
4. 背面四分之三（rear three-quarter view，约 135°）；
5. 背面（back view，180°）。

五视图用于锁定：

- 身份 DNA：脸型、五官比例、痣/疤位置、纹身、年龄感和肤色，发型、发色、角色气质、时代背景；
- 头发：发际线、发型结构、长度、发色和头饰；
- 身体：身高、肩宽、体型、四肢比例和站姿基准；
- 服装：版型、层次、颜色、面料、纹样、鞋子和磨损状态；
- 标志物：眼镜、耳饰、项链、腕表、武器或剧情道具。

分镜、海报、角色动作、九宫格和运镜视频都必须引用这份角色锚点，不得仅凭文字重新生成。

## 2. 五视图硬性规范

### 2.1 画布与排列

- 一张横向画布，严格划分为五个等宽面板；
- 五个面板只能放同一个角色，顺序不可改变；
- 同焦段、同相机高度、同中性光、同纯色背景；
- 每格完整全身、自然站姿、双脚不裁切、身体无遮挡；
- 五个视图的角色高度和缩放比例一致。

### 2.2 身份一致性

五个视图必须保持同一脸型、同一五官比例、同一痣/疤位置、同一发际线、同一发型、同一服装、同一配饰和同一身材。角度变化只能揭示新的侧面或背面信息，不能重新设计角色。

### 2.3 禁止项

禁止重复角度、镜像脸、多人、额外肢体、手指异常、裁切脚部、坐姿、动态姿势、透视夸张、服装变体、发型变体、场景道具、文字、水印、边框标题和复杂背景。

## 3. 五视图提示词模板

### 3.1 项目标准中文模板

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

### 3.2 English template

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

### 3.3 代码对应模板

```python
def build_five_view_prompt(name: str, identity_dna: str, visual_style: str) -> str:
    """Build one strict five-panel turnaround prompt for a single identity."""
    return (
        f"为角色{name}制作同一人物、同一服装、同一发型、同一体型的五视图角色设定板。"
        "画布严格横向等宽五栏，五个视图按从左到右固定顺序："
        "正面、正面四分之三、标准侧面、背面四分之三、背面。"
        f"身份DNA：{identity_dna}。视觉风格：{visual_style}。"
        "五个视图必须是同一个人物，不得改变脸型、五官比例、痣/疤位置、发际线、发型、服装、配饰和身材；"
        "同焦段、同相机高度、同中性光、同纯色背景、完整全身、自然站姿、无遮挡。"
        "禁止重复角度、镜像脸、多人、额外肢体、裁切脚部、文字水印和场景道具。"
    )
```

## 4. 角色锁定卡

五视图生成并通过质检后，提取一份结构化角色锁定卡。后续所有镜头复制这份信息，不得自由改写关键字段。

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

### 禁止变化

- 不改变身份、脸型、五官比例、年龄感和肤色；
- 不改变发际线、发型、发色和头饰；
- 不改变服装版型、层次、颜色、材质和鞋子；
- 不改变体型、身高感和四肢比例；
- 不丢失或新增标志性配饰、伤疤、纹身和剧情道具。

## 5. 角色资产工作流

1. 每个角色单独生成五视图，禁止多人共用一张设定板。
2. 执行角度、身份、全身完整性和负面项质检。
3. 生成角色锁定卡并绑定五视图图片。
4. 儿童版、老年版、战损版、换装版作为新的“角色状态”，分别生成五视图；不得覆盖基础状态。
5. 每个分镜格按 `character_id + state_id` 引用角色，不通过姓名模糊匹配。

## 6. 单镜头提示词模板

```text
严格参考角色「[角色名称]」的五视图和角色锁定卡，保持同一身份、同一张脸、同一发型、同一服装、同一体型和同样的标志性配饰。

镜头 ID：[shot_id]
角色：[角色 ID / 状态 ID]
场景：[场景圣经 ID 与可见环境]
道具：[名称、归属、所在手/位置、状态]
特效：[类型、触发点、强度、与人物遮挡关系]
主体动作：[一个可完成的小动作]
可观察表情：[眉眼、嘴部、下颌、呼吸、手部等]
景别与机位：[景别、角度、焦段、相机高度]
构图与轴线：[人物左右关系、视线、动作轴线、前中后景]
灯光：[主光方向、色温、时间、天气]
运镜：[方式、方向、速度、起止点和叙事原因]
首状态：[画面开始时的准确状态]
尾状态：[画面结束时的准确状态]
连续性：[从上一镜承接什么，向下一镜交付什么]

一致性：上述角色、场景、道具、特效、轴线、首状态和尾状态为硬约束，不得替换、删除或新增。
```

## 7. 九宫格分镜图片规范

分镜图片必须是一张严格 3×3 九宫格，不得输出 2×2、2×3、单张长图或无编号拼贴。九格按从左到右、从上到下对应镜头 1–9；同时保留九张独立高分辨率分镜图，供视频模型作为参考。

### 7.1 九宫格资产清单

每个九宫格故事板必须先声明四类资产：

- 角色：角色 ID、状态 ID、五视图引用；
- 场景：空间布局、人物站位、主光方向、色温、时间、天气；
- 道具：外观、归属、位置、状态及连续性；
- 特效：种类、颜色、强度、触发时机和物理影响。

### 7.2 每格必填字段

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

### 7.3 九宫格总提示词

```text
生成一张严格 3×3、从左到右再从上到下阅读的九宫格电影分镜板，恰好九格。
每格只推进一个动作或一个信息单元，九格共同覆盖完整因果和情绪递进。
所有格严格继承同一角色五视图、场景圣经、道具归属、特效规则、180 度轴线、主光方向和色温。
每格的画面必须匹配该格的角色、场景、道具、特效、景别、机位、构图、动作、表情、首状态和尾状态。
禁止缺格、重复格、合并格、角色换脸、服装漂移、道具换手、左右翻转、光向跳变和无动机镜头。
```

## 8. 分镜到运镜的一致性契约

分镜提示词、分镜图片信息和运镜视频必须来自同一份 `ShotMotionContract`。视频提示词不得另写一套剧情。

### 8.1 不可改变的字段

- `shot_id`；
- 角色及五视图/状态引用；
- 场景、道具、特效；
- 景别、机位、焦段、构图、动作轴线和视线；
- 主体动作、表情、灯光；
- 首状态、尾状态、连续性输入/输出；
- 分镜图及参考素材清单。

系统把这些字段规范化为 JSON 并计算 SHA-256 指纹。视频计划必须携带相同 `contract_fingerprint`；任一字段修改后，旧视频计划自动过期并重新生成。

### 8.2 运镜提示词编译模板

```text
镜头 [shot_id]，严格依据契约 [contract_fingerprint] 和对应分镜图生成。
不得改变角色、场景、道具、特效、景别、机位、构图、轴线、灯光和首尾状态。
从「[start_state]」开始，角色执行「[subject_action]」，表情表现为「[expression]」。
相机以「[camera_movement]」运动，方向/速度/起止点为「[camera_path]」，目的为「[camera_reason]」。
以「[end_state]」结束，并向下一镜交付「[continuity_out]」。
保持真实物理运动、稳定面部、稳定手指、稳定服装纹理和连续背景；禁止无动机切镜、瞬移、变脸、道具换手和轴线翻转。
```

## 9. 视频生成模式自动判断

用户选择 `auto` 时，系统根据镜头控制目标、可用素材和运行时供应商能力自动评分。选择顺序不是固定品牌优先级，最终结果必须包含 `mode`、`provider`、`reasons` 和 `fallbacks`。

### 9.1 首尾帧生视频

同时提交首帧和尾帧，用于必须精准控制开始与结束画面的单个连续镜头。

适用条件：

- 合法首帧和尾帧都存在；
- 尾状态是硬性剧情锚点，例如落座、转身完成、道具到位或门完全关闭；
- 首尾画面属于同一镜头且场景/角色差异可连续过渡；
- 运行时模型档案确认支持首尾帧。

候选模型可包括 Seedance、MiniMax H3、Kling；具体版本以运行时配置和能力探测为准。

### 9.2 多图/宫格生视频

提交多张连续分镜图、九宫格拆分图或角色/场景/道具/特效参考图，适合多镜头叙事或需要多资产约束的镜头。

适用条件：

- 有两张以上具备明确叙事顺序的图片；
- 输入来自同一九宫格的连续分镜，或需要同时锁定多个视觉资产；
- 没有比“精确到达尾帧”更高的硬约束；
- 运行时模型确认支持所需图片数量和引用语义。

候选可包括 Grok（兼容用户输入别名 `Gork`）、HappyHorse、Seedance、MiniMax H3、Kling；LTX-2.3 只有在运行时档案确认多图引用语义后才进入该模式候选。

### 9.3 多模态全能参考/角色一致性生成

提交参考图片、视频或音频，分别锁定角色/美术风格、动作/运镜节奏、音乐/声音节奏。

适用条件：

- 存在动作或运镜参考视频；
- 存在需要严格跟随的节奏/声音参考，并且模型支持音频条件；
- 需要综合角色五视图、动作视频和音频节奏；
- 运行时模型确认支持对应媒体类型和数量。

候选可包括 Seedance、MiniMax H3、Kling O1 和 HappyHorse；每种输入是否能同时提交必须以具体模型/端点的运行时能力为准。

### 9.4 自动选择决策表

| 控制目标 | 必要输入 | 首选模式 | 降级 |
|---|---|---|---|
| 精准命中结尾画面 | 首帧 + 尾帧 | 首尾帧 | 首帧 |
| 九格/连续图片叙事 | 2–9 张有序图片 | 多图/宫格 | 首帧 |
| 锁定动作或运镜 | 参考视频 + 视觉参考 | 多模态 | 多图 |
| 锁定音频节奏 | 音频 + 视觉参考 | 多模态 | 多图，不谎称使用音频 |
| 只有一张分镜图 | 首帧 | 首帧 | 文生视频（仅显式允许时） |

若候选模型均不兼容，系统必须在付费调用前失败关闭，不能静默丢弃尾帧、参考视频或音频。

## 10. 人物一致性强化词库

### 正向词

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

### 负向词

```text
different person, identity drift, face variation, age change, hairstyle change, hair color change,
outfit change, missing accessory, added accessory, body proportion change, mirrored face,
duplicate angle, extra person, extra limbs, deformed hands, cropped feet, text, watermark
```

## 11. 常见问题

### 脸一致但衣服变化

把服装拆成版型、层次、颜色、材质、纹样、鞋子和磨损状态，绑定到角色状态 ID；不要只写“黑色西装”。

### 发型漂移

明确发际线、分缝、刘海、长度、卷度、发色和头饰位置，并在五个视图里逐项核对。

### 多人镜头混脸

为每个角色提供独立五视图，分镜中使用不同 `character_id`，明确左右站位、视线和服装，禁止仅用“男人/女人”区分。

### 道具换手或消失

在每镜 `start_state` 和 `end_state` 中声明道具归属、所在手、空间位置和状态，并让下一镜 `continuity_in` 原样承接。

### 运镜和分镜不一致

不要单独手写视频提示词。修改镜头契约后重新计算指纹、重新编译分镜图片提示词和运镜提示词；指纹不一致时禁止生成。

## 12. 最终工作流

1. 为每个角色/角色状态生成严格五视图；
2. 五视图质检并生成角色锁定卡；
3. 建立场景、道具和特效资产卡；
4. 生成恰好九格的 3×3 分镜契约；
5. 从契约生成九宫格总图及九张独立分镜图；
6. 计算每个镜头的契约指纹；
7. 从同一契约编译运镜提示词；
8. 自动判断首尾帧、多图/宫格、多模态或首帧模式；
9. 与运行时模型能力协商，记录供应商、模式、理由和降级链；
10. 指纹一致后生成视频，质检角色、场景、道具、特效、动作、轴线和首尾状态；
11. 不合格镜头只重做对应镜头，不破坏已通过镜头的契约；
12. 配音、音效与 BGM 合成后输出成片和完整溯源记录。

## 13. 交付检查清单

- [ ] 每个角色有独立五视图，且顺序严格正确；
- [ ] 五视图为横向五等宽栏、完整全身、同焦段、同高度、同光线、同背景；
- [ ] 每个故事板恰好为 3×3 九宫格；
- [ ] 每格包含角色、场景、道具、特效和完整镜头字段；
- [ ] 分镜图提示词和运镜提示词来自同一契约；
- [ ] 分镜计划与视频计划的 `contract_fingerprint` 一致；
- [ ] 自动模式选择有可读理由，模型能力不匹配时明确降级或阻断；
- [ ] 未支持的参考素材不会被静默忽略；
- [ ] 密钥只从服务端安全配置读取，不出现在文档、前端、日志和产物中。
