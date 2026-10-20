# 运镜词条库：英文模板、幅度速度语法与镜头时长反推

> 来源：公众号「AIGC无限流」2026-10《剧本一体化生成器 Skill 2.0》里的 48 条运镜库、分镜表时长规则与运镜避坑清单
> (https://mp.weixin.qq.com/s/a-586FwvJ9WFsS9mBv5WZQ)。按本项目重写：`camera-style-library` 管"选哪种运镜"，
> 本文管"怎么把这种运镜写成模型听得懂的一句话"，以及一个镜头该给几秒。

## 一、写法总则

1. **一镜一主运镜**：推完又环绕又俯仰，模型只保一个。复合最多两个不冲突的方向(环绕 + 微升、推 + 轻手持)。
2. **幅度宁小、速度宁慢**：先写 `small amplitude, slow`，不够再加。大幅快速最容易糊和撕裂；想要快节奏，缩短单镜时长而不是加快运镜。
3. **运镜单独成句，放提示词最后**：混在主体描述里会被忽略。生图提示词不带运镜；生视频提示词 = 生图提示词 + 空格 + 运镜句。
4. **写清镜头与主体的相对关系**：跟拍类必须写 `keeping a steady distance` / `at the same speed`，否则主体会径直冲向镜头。
5. **给镜头一个落点**：每个运动镜头写清终点停在什么上(`and settles on …` / `locks off on …`)，没落点看起来半途而废。
6. **主体稳、镜头动**：主体与镜头同时大幅动必糊。
7. **竖屏把幅度调高一档**：9:16 里运动会被压缩，`small` 写成 `large` 才看得出来。
8. **复合高级运镜(环绕 + 升降、希区柯克变焦)成功率约五成**：多生成几条挑质量，不要指望一次成。

幅度与速度只用四个词：`small amplitude` / `large amplitude`、`slow speed` / `fast speed`；固定机位写 `static shot`；
手持写 `shakes slightly` / `shakes strongly`。下面模板里的 `{主体}{动作}{环境}` 替换成本镜的具体内容。

## 二、48 条词条(词条 | 英文模板 | 幅度·速度 | 建议秒数 | 适配)

### A 固定与微动
- 固定机位 | `The camera holds a static shot as {主体} {动作}.` | — | 3–5 | 正反打、口播、情绪空镜
- 呼吸感微推 | `The camera pushes in with small amplitude at slow speed toward {主体}.` | small·slow | 4–6 | 内心戏、告白前、下定决心
- 轻微手持 | `The camera shakes slightly while following {主体}, keeping a natural handheld feel.` | slight | 3–5 | 纪实跟拍、紧张对峙
- 剧烈晃动 | `The camera shakes strongly as {事件} occurs.` | strong | 1–3 | 爆炸、受击、惊慌逃命

### B 推拉
- 推镜头 | `The camera pushes in with large amplitude at slow speed from a medium shot to a close-up of {主体}.` | large·slow | 4–6 | 情绪加强、揭示细节
- 急推 | `The camera pushes in with large amplitude at fast speed, snapping to an extreme close-up of {主体}.` | large·fast | 1–2 | 惊悚反转、惊吓点
- 拉镜头 | `The camera pulls out with large amplitude at slow speed, revealing {环境} around {主体}.` | large·slow | 4–6 | 交代环境、段落收尾、孤独感
- 急拉揭示 | `The camera pulls out with large amplitude at fast speed, abruptly revealing {真实环境}.` | large·fast | 2–3 | 真相大白、梦境惊醒
- 光学变焦推 | `The camera zooms in at slow speed while the camera body stays still.` | 机位不动·slow | 3–5 | 监控、偷窥、客观记录
- 希区柯克变焦 | `The camera pushes in while zooming out at the same time, keeping {主体} the same size as the background stretches.` | 推进与变焦须写"同时" | 3–5 | 重大打击、认知崩塌
- 前景遮挡揭示 | `The camera trucks right with small amplitude at slow speed, letting {前景遮挡物} slide out of frame to reveal {主体}.` | small·slow | 3–5 | 重要人物出场、悬念释放

### C 摇镜与俯仰
- 水平摇镜 | `The camera pans right with large amplitude at slow speed across {场景}.` | large·slow | 5–8 | 开场建立、空镜转场
- 甩镜 | `The camera pans right with large amplitude at fast speed, whipping past {起点} to {终点}.` | large·fast | 1–2 | 时间跳跃、动作衔接
- 垂直摇上 | `The camera tilts up with large amplitude at slow speed from {低处} to {高处}.` | large·slow | 4–6 | 仰视权威、渺小感
- 垂直摇下 | `The camera tilts down with large amplitude at slow speed from {高处} to {主体}.` | large·slow | 4–6 | 从环境落到人物
- 摇镜落幅定人 | `The camera pans left with large amplitude and settles on {主体}, holding a static shot.` | large→static | 4–6 | 引出关键人物、揭示隐藏者

### D 平移与跟随
- 横移 | `The camera trucks left with small amplitude at slow speed, moving parallel to {主体}.` | small·slow | 4–6 | 走廊行进、车窗外
- 侧面跟拍 | `The camera tracks {主体} with small amplitude, moving alongside at the same speed and keeping them centered.` | 与主体同速 | 4–8 | 行走、奔跑、骑行
- 背后跟拍 | `The camera follows {主体} from behind at slow speed, holding a steady distance as they move forward.` | slow | 4–8 | 探索未知、背影叙事
- 前置倒退跟拍 | `The camera tracks backward in front of {主体} at slow speed, keeping their face in frame as they walk forward.` | slow | 4–6 | 决心时刻、边走边谈
- 载具跟拍 | `The camera tracks {载具} at fast speed from a mounted position, keeping the vehicle in frame.` | fast | 3–5 | 追车、逃亡

### E 升降
- 升镜头 | `The camera pedestals up with large amplitude at slow speed, rising from {主体} to reveal {全景}.` | large·slow | 5–8 | 揭示全貌、情绪升华
- 降镜头 | `The camera pedestals down with large amplitude at slow speed, descending from {高空全景} to {主体}.` | large·slow | 5–8 | 上帝视角入场
- 摇臂大范围 | `The camera cranes up and pans right with large amplitude at slow speed, sweeping across {大场景}.` | large·slow | 6–10 | 史诗开场
- 天顶俯拍 | `The camera looks straight down at {主体} from directly above with a static shot.` | static | 3–5 | 棋局、案发现场

### F 环绕
- 半环绕 | `The camera moves in an arc shot around {主体}, orbiting about 180 degrees at slow speed.` | 180°·slow | 5–8 | 人物高光、对峙双方
- 360 度环绕 | `The camera orbits 360 degrees around {主体} at slow speed, keeping them centered in frame.` | 360°·slow | 6–10 | 变身、角色亮相
- 螺旋上升环绕 | `The camera orbits {主体} at slow speed while rising, spiraling upward around them.` | 环绕+升·slow | 6–10 | 觉醒、情绪顶点
- 低角度贴地环绕 | `The camera orbits {主体} at slow speed from a low angle close to the ground.` | 低角·slow | 5–8 | 反派登场、压迫感

### G 视角与 POV
- 第一人称 POV | `The camera adopts the point of view of {角色}, showing {所见} as they look around.` | 配轻手持 | 3–5 | 沉浸、惊悚探索
- 过肩 OTS | `The camera holds a static over-the-shoulder shot from behind {角色A}, framing {角色B} across from them.` | static | 3–5 | 对话、谈判、审讯
- FPV 穿越 | `The camera flies through {狭窄空间} at fast speed and emerges into {开阔空间}.` | fast | 3–5 | 空间转换、炫技转场
- 航拍 | `The camera flies forward as an aerial drone shot at slow speed above {地貌}.` | slow | 5–8 | 城市开场、旅程过渡
- 微距 | `The camera pushes in with small amplitude at slow speed into a macro view of {微小对象}.` | small·slow | 3–5 | 瞳孔、手部纹理、质感
- 镜面反射 | `The camera holds a static shot on the reflection of {主体} in {镜面}, with the reflection filling the frame.` | static | 3–5 | 双重人格、身份错位

### H 风格化与特殊
- 荷兰角 | `The camera holds a dutch angle shot with the frame tilted {15–30} degrees, as {主体} {动作}.` | 写清度数 | 3–5 | 失衡、危险预兆
- 镜头翻滚 | `The camera rolls clockwise at slow speed around the lens axis.` | roll·slow | 2–4 | 坠落、眩晕、梦境
- 子弹时间 | `The camera orbits {主体} at slow speed while their motion slows to a near freeze.` | 环绕+慢动作 | 3–5 | 战斗定格、变身
- 焦点转移 | `The camera holds a static shot as focus shifts from {前景} to {后景}.` | static+变焦点 | 3–5 | 发现背后有人、权力反转
- 一镜到底 | `The camera tracks {主体} continuously through {空间A} into {空间B} without cutting.` | 连续 | 8–10(单次上限) | 群戏调度
- 运动模糊慢门 | `The camera pans right at fast speed with heavy motion blur trailing across the frame.` | fast+拖影 | 2–4 | 回忆闪回、迷幻过渡
- 抽离式拉远 | `The camera pulls out with large amplitude at slow speed until {主体} becomes small within {巨大环境}.` | large·slow | 5–8 | 结局收束、人物渺小
- 穿物转场 | `The camera pushes in at fast speed through {物体表面} and emerges into {新空间}.` | fast | 2–4 | 时空跳转
- 电梯视角 | `The camera moves vertically at slow speed inside the elevator, rising from {楼层} to {楼层}.` | 垂直·slow | 3–5 | 阶层隐喻、密闭紧张
- 门缝窥视 | `The camera holds a static shot looking through a half-open door into {室内}.` | static | 3–5 | 偷窥、秘密被发现
- 摇臂俯冲 | `The camera cranes down with large amplitude at fast speed, diving from the sky toward {主体}.` | large·fast | 3–5 | 命运降临、英雄登场
- 推近锁定 | `The camera pushes in at fast speed and then locks off on {主体}, holding a static shot.` | 快推→static | 3–4 | 下决心、锁定目标
- 螺旋推进 | `The camera pushes in at slow speed while rolling, spiraling toward {主体}.` | 推+roll·slow | 4–6 | 催眠、意识沉入

## 三、六个组合公式(整句填入运镜位)

| 场合 | 英文 |
|---|---|
| 情绪递进 | `The camera pushes in with small amplitude at slow speed, with a slight handheld feel.` |
| 出场展示 | `The camera arcs around {主体} at slow speed while rising slightly.` |
| 开场建立 | `The camera pedestals down with large amplitude, then pans right at slow speed across the scene.` |
| 紧张追逐 | `The camera follows {主体} from behind at fast speed, shaking strongly.` |
| 结尾收束 | `The camera pulls out with large amplitude at slow speed and settles into a static shot.` |
| 揭晓反转 | `The camera pushes in with large amplitude at fast speed and locks off on {主体}.` |

## 四、镜头时长反推与拆镜(分镜表逐镜算，不拍脑袋)

单镜 2–8 秒，常规 3–5 秒；2 秒只给快速反应与插入镜头。时长由内容反推，而不是先定秒数再凑内容：

| 镜头类型 | 算法 | 典型 |
|---|---|---|
| 纯静态(单人 / 单动作 / 无台词) | 一个画面只讲一个信息点 | 2–3 s |
| 有旁白 | 旁白字数 ÷ 3.5–4(字/秒，气声偏慢) + 1 s 留白 | 14 字 ≈ 4 s |
| 有对白 | 台词字数 ÷ 4 + 0.5–1 s 反应停顿 | 10 字 ≈ 3 s |
| 纯动作 | 动作节点数 × 1.5 s | 3 节点 ≈ 4–5 s |
| 空镜 / 情绪镜 | 2–3 s；确需呼吸感最多 4 s 并注明理由 | 2–3 s |

达到任一条就必须拆镜：动作节点 > 4；旁白或对白 > 32 字；要交代 ≥ 2 个信息点(换主体 / 换地点 / 换事件)；
换运镜类型(推完又环绕 = 两镜)；按上表算出 > 8 s。宁可多几个短镜，不要一个硬撑的长镜；一个静态画面绝不给 8 秒以上。
本项目的模型秒数集合由 `durations.supported_shot_durations` 给出，算出的秒数落到集合里最近的值。

分镜图(关键帧)张数 ≈ 1(首帧) + 运镜复杂度 + 动作节点：固定单动作 1 张；推拉摇单向 2 张(首尾帧)；
移跟升降 3–4 张；环绕 / 多主体 / 大动作 4–5 张；6–8 秒复杂动作 5–6 张，封顶 6。

## 五、生视频提示词的七段顺序

`风格声明 → 主体与动作/表情 → 场景环境 → 景别 → 角度 → 光线氛围 → 运镜句(最后)`。
风格声明全片用同一句、一字不改；主体外观、服装用封闭式描述(颜色 + 款式 + 材质写死)；末尾可加稳定性约束
"保持主体外观与首帧一致，避免肢体变形、画面闪烁、多余文字"。
