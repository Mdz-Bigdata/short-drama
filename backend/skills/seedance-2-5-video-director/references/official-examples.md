# Curated handbook examples

## Contents

- Provenance and use
- Basic multimodal
- Exact 30-second structure
- Long Video
- Video extension
- Video edit
- Clay Renderer
- Seamless transition
- Multi-grid storyboard
- Specialist snippets

## Provenance and use

- Source: `https://bytedance.larkoffice.com/wiki/NjnWwvf4BiFYFLk2RzrcEgaunGf`
- Source revision: `419`
- Curated: `2026-08-16`

These examples are normalized and shortened from the handbook to expose reusable structure. They are not an exhaustive mirror. Use them to understand specificity and ordering; replace all subjects, references, timing, and constraints with the user's request.

## Basic multimodal

```text
写实自然纪录片风格，电影级真实光影。清晨薄雾中的秋季湿地芦苇荡参考 @Image 1；红冠鹤的羽色、体态和比例参考 @Image 2。低机位中景，轻微手持呼吸感，主体始终位于画面中心。

0-3 秒：红冠鹤静立浅水，缓慢展开黑白双翼，翼风在水面推开涟漪；朝阳穿过薄雾形成自然体积光。
3-8 秒：红冠鹤轻跃，双足交替点水溅起水珠，随后轻盈落地收翼，抬头发出清亮长鸣。镜头小幅上下跟随跳跃轨迹。

保持自然景深，前景芦苇轻微虚化，主体清晰，背景晨雾与日出柔和虚化。仅保留流水、振翅与鹤鸣等自然环境声。
```

Pattern: visual intent → asset identity/scene roles → short timeline → camera, focus, and sound convergence.

## Exact 30-second structure

```text
30 秒、16:9、单镜头情绪短片。清晨河畔，一位古装女子与镜头对面的爱人告别。电影写实质感，浅景深，柔和自然光，近景主观视角，轻微手持呼吸感，不快速切镜。

人物为 22 岁成年东亚女性：冷调白皙但保留真实微毛孔与自然皮肤纹理；细长含泪眼、柔和下颌线；黑发低髻，以素玉簪固定；白色交领轻纱衣。表演克制，重点表现视线转移、呼吸、嘴唇轻颤、吞咽和一滴泪自然滑落。

0-3 秒【追问】：直视镜头，尚未落泪，轻声问：“你真的要走吗？”
3-10 秒【接受】：视线缓慢移开，深呼吸，将未说出口的话咽下。
10-20 秒【不舍】：重新看向镜头，眼眶逐渐湿润，保持克制，不夸张哭泣。
20-27 秒【告别】：嘴角勉强露出温柔微笑，一滴泪在此阶段才滑落。
27-30 秒【余韵】：她轻轻点头，镜头保持近景，停在含泪但平静的目光上。

全程锁定人物身份、发型、服装、河岸机位和清晨光向；无额外台词、无字幕、无 BGM、无夸张肢体动作、泪水不得提前出现。
```

Pattern: global world/character/performance lock → complete continuous timeline → timing-sensitive prohibitions.

## Long Video

```text
总时长 60 秒，16:9，电影写实、复古治愈风格。雨日下午的复古咖啡馆，固定机位记录木桌上的热咖啡和玻璃窗外雨景。

0-20 秒【安静开场】：镜头固定，咖啡热气缓慢上升；雨滴落在格纹玻璃上并汇聚下滑。无人进入画面，不切镜。
20-40 秒【细节推进】：镜头极慢推近咖啡杯；一片金色落叶飘过并贴在窗外玻璃上，焦点仍停在杯沿和热气。
40-60 秒【焦点转移】：焦点从前景咖啡缓慢转向窗外雨景，街灯在雨水中散成暖色光斑，画面随雨声逐渐变暗结束。

全程保持室内暖黄光与室外冷雨色的冷暖对比，只使用真实雨声和轻微环境声；无人物、无文字、无 BGM、无闪烁或突兀转场。
```

Pattern: total duration and ratio → broad readable acts → one controlled evolution → sound and stability convergence.

## Video extension

Natural continuation:

```text
参考 @Video 1 的原始内容，向后续写 5 秒。原视频内容保持不变，本提示仅作用于新增 5 秒。肌肉战士继续位于同一原始森林空间，承接边界帧中的步伐、身体朝向、镜头前移速度、斑驳日光和环境声；他突然察觉异常，停下脚步，目光变得锐利，顺势转入防御姿态并盯住前方。动作和镜头衔接自然流畅，不硬切，不重置站位，不让道具或角色凭空出现。
```

Transition continuation:

```text
参考 @Video 1，向后续写 10 秒并继续故事；原视频保持不变。连接点使用遮挡转场：近景中的战士保持防御姿态，一片正常大小的落叶随风接近并完全遮住镜头；镜头穿过叶片后自然拉开，揭示 @Image 2 的年轻游侠倚树举弓瞄准。保持遮挡方向、镜头运动和风向连续，从战士近景自然切换为游侠中景；禁止硬切和物体凭空出现。
```

## Video edit

Unmarked edit:

```text
在整段 0-8 秒内，将视频中的鲸鱼替换为白色东方龙；保持原有动作轨迹、主体尺度、镜头运动、场景、光影和其他元素不变。移除 BGM，保留其余指定现场声。
```

Marked edit:

```text
仅修改红色框内、红色箭头所指的咖啡杯：在 5-8 秒将它逐渐替换为一束红玫瑰。框外人物、桌面其他物品、背景、机位、光影、动作和声音保持不变；玫瑰需要符合原视频透视、遮挡、接触阴影和运动稳定性。
```

## Clay Renderer

Coarse model:

```text
参考 @Video 1 的相机轨迹、人物动作和物理光影变化，将白色人形模型完整映射为 @Image 1 的成年精灵女王；不要继承灰模材质、视口背景或辅助线。人物保持银白长发、白金刺绣长袍和水晶法杖，身份与服装全程一致。

场景渲染为精灵大厅，保持 @Video 1 的机位和空间调度。女王按灰模动作自然举起法杖，长发与宽大裙摆随气流产生连贯摆动；原视频光效转译为从地面升起的圣洁光柱，与法杖金色光芒呼应。

最终为电影级写实 CG，皮肤、金属刺绣和丝绸材质清晰，动作自然，无穿模、变脸、灰模质感、坐标轴或轨迹线。
```

Fine model:

```text
将 @Video 1 的完整白模动画渲染为最终成片。0-7 秒保持写实海洋夜景：深灰蓝风暴海面持续起伏，红白条纹灯塔按白模动画随巨浪俯仰；使用低饱和电影氛围、HDR 光照、体积雾、湿润高光、真实反射和动态阴影。

风雨、浪花和雾气保持统一风向与物理逻辑；相机、构图、灯塔位置和运动轨迹严格保留。仅保留海浪、狂风、雨声与偶发低沉雷声，无 BGM、无旁白、无视口网格、轨迹线、坐标轴或相机锥体。
```

## Seamless transition

```text
无缝连接 @Video 1 与 @Video 2，但不要修改两段原视频的既有内容。@Video 1 的镜头继续快速推向水洼中的圆形蓝紫霓虹倒影；圆形倒影占满画面后，自然过渡到 @Video 2 的金色太阳倒影。持续推镜过程中，雨夜水洼纹理由外向内逐渐变成森林湖面的水波，蓝紫色霓虹同步转为金色阳光，环境随之完成变化。

连接点锁定中央圆形倒影的形状、屏幕位置、大小、推近方向和速度；镜头运动连续，无黑帧、跳帧、硬切、闪烁、文字、标志或字幕。
```

## Multi-grid storyboard

```text
@Image 1 是包含 4 个连续镜头的完整分镜脚本，每一格代表一个完整镜头，而不是独立人物或场景。成年女性角色身份与服装参考 @Image 2；橘白小猫的品种、毛色、服装和比例参考 @Image 3，二者全程保持一致。

镜头 1（0-4 秒）：黄昏住宅区，低机位中景缓慢推近，小猫跳上垃圾桶寻找食物。
镜头 2（4-8 秒）：切至近景，小猫扒住桶沿翻找，耳朵轻动，突出饥饿和无助。
镜头 3（8-13 秒）：固定中景，女性在门口发现小猫并放下食物，小猫保持警惕地接近。
镜头 4（13-15 秒）：镜头缓慢拉远，小猫跟随女性走进暖光中的家门，停在安静庭院上结束。

采用温暖治愈的 3D 动画电影 CG 风格，保持时间、空间、人物位置、光向和动作连续；禁止变脸、比例漂移、毛色变化、服装变化以及新增无关人物或道具。
```

## Specialist snippets

BGM removal:

```text
移除 @Video 1 的背景音乐，仅保留清晰人声和真实室内环境声；原画面、原有字幕、人物动作和镜头保持不变。
```

Timbre binding:

```text
角色 A 在 6-9 秒说“我找到你了”，音色参考 @Audio 1，保留低沉音色、缓慢语速和压低呼吸的悬疑感；不要继承参考音频中的背景噪声或其他说话人。
```

Multiple-person lock:

```text
新娘身份参考 @Image 1，新郎身份参考 @Image 2，三位伴娘统一参考 @Image 3，三位伴郎统一参考 @Image 4。身份、数量、服装和主次关系全程清晰；禁止新郎新娘混脸、伴郎伴娘服装互换、重复人物和额外肢体。
```

Creative transfer:

```text
参考 @Video 1 的手机滑动动作、镜头节奏和转场逻辑，将其转译为围绕 @Image 1-5 内容展开的创意短片；保持目标图片的核心主体、空间结构和视觉风格，不继承参考视频中的人物身份、背景文字或标志。
```

Perspective reconstruction:

```text
将 @Video 1 的多机位切换改为固定正面机位，人物身份、动作时间、背景空间和原声保持不变；保持稳定中景，不产生新的侧面或俯拍镜头。
```

Green-screen composite:

```text
提取 @Video 2 的绿幕前景并合成到 @Video 1 的城市道路。当前景从镜头旁经过时，匹配道路透视、主体尺度、地面接触、阴影、运动模糊和相机下俯角；移除绿色溢色、边缘光晕、漂浮感和逐帧闪烁，原城市镜头的运动和空间保持不变。
```
