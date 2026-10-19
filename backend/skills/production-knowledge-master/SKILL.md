---
name: production-knowledge-master
description: 八阶段短剧生产线的知识路由与教训进化中枢——各技能经 manifest.json 登记的知识章节按「章节键→阶段→预算」装载进各阶段上下文，并沉淀 learned/ 自动进化的历史生产教训
---

# production-knowledge-master

八阶段 AI 短剧生产线（drama_service：总导演策划 → 编剧剧本创作 → 角色设计师造型 →
镜头拆解 → 视觉总监多镜头生成 → 音频总监配音音效 → 合成发布渲染合流 → 宣发Agent引流）
的知识路由技能。知识正文**住在各自所属的技能里**（编剧类在 screenwriting-master，
分镜表演类在 shot-design-master，角色设定在 character-turnaround-consistency，
连续性在 shot-transitions-master，制作规范 / 质检 / 负面词 / 高光 / 画质在本技能的
references/），每个技能用 `manifest.json` 登记自己的章节：键、标题、文件、默认预算、
消费阶段。代码只认章节键，不认识任何文件名或路径。本技能包承载：

1. references/：本技能负责的五份知识章节，与 manifest.json；
2. 本路由说明（SKILL.md）：章节键 → 所在技能 → 阶段 → 预算的总览；
3. learned/：自动进化的历史生产教训（lessons.jsonl + evolution_log.jsonl）；
4. README.md：面向人的说明与教训审阅流程。

登记读取：`app/core/knowledge_registry.py`（扫描技能目录下每个 manifest.json，键全局唯一，
文件必须在技能目录内，写错即报错）。装载器：`app/core/production_knowledge.py`
（load_section / load_stage_sections / stage_sections / section_budgets / stage_lessons_block）。
技能目录取自 `settings.skills_root()`（环境变量 SKILLS_DIR 可改，默认 backend/skills）；
截断一律落在行边界，绝不留下半张表格；章节键即白名单，未知键、缺失文件或不合法的
manifest 都降级为空串、绝不抛异常阻塞流水线。agent_council 对全部登记章节做 SHA-256 指纹。
进化引擎：`app/core/knowledge_evolution.py`（harvest_from_qc / active_lessons /
promote_and_prune / evolution_report）。

新增或移动一份知识文档：放在仓库根部后运行 `backend/scripts/organize_knowledge.py`，
它按 `backend/skills/knowledge-routing.json` 把文档归入对应技能并写好 manifest；
也可以直接把文件放进技能目录、手工在 manifest.json 里登记。

## 八阶段路由表

各阶段通过 `load_section("<章节键>")` 装载知识源，默认预算取该章节在 manifest 里登记的 budget
（0 表示全文）。同一章节可被多个阶段消费，各自独立截断互不影响。最后一列列出
该章节在阶段 sys_prompt 中的段落标题（与 drama_service 现状逐字对照），迁移与审计时以此为准；
段落标题文案本身也属于「不得改动」的既有拼装结构。

| 阶段 | 角色 | 章节键 | 所在技能 / 文件 | 预算 | 进提示词的位置 |
|---|---|---|---|---|---|
| 1 总导演策划 | EXECUTIVE_DIRECTOR | golden-narrative | screenwriting-master/references/golden-narrative.md | 5000 | sys_prompt「【黄金叙事结构(单集与整部结构/情绪峰值/钩子公式)如下】」 |
| 1 总导演策划 | EXECUTIVE_DIRECTOR | production-guidelines | production-knowledge-master/references/production-guidelines.md | 5000 | sys_prompt「【全局短剧制作注意事项与关键元素规范如下】」 |
| 1 总导演策划 | EXECUTIVE_DIRECTOR | genre-summary | screenwriting-master/references/genre-summary.md | 5000 | sys_prompt「【短剧题材与爆款题材结构指导如下】」 |
| 2 编剧剧本创作 | WRITER | golden-narrative | screenwriting-master/references/golden-narrative.md | 5000 | sys_prompt「【黄金叙事结构(单集黄金结构/每集三件事/短剧公式/一集模板)如下】」 |
| 2 编剧剧本创作 | WRITER | performance-details | shot-design-master/references/performance-details.md | 5000 | sys_prompt「【短剧表演细节与具象物理动作指导如下】」 |
| 2 编剧剧本创作 | WRITER | continuity-design | shot-transitions-master/references/continuity-design.md | 5000 | sys_prompt「【跨镜头与场景动作连续性设计指导如下】」 |
| 2 编剧剧本创作 | WRITER | production-guidelines | production-knowledge-master/references/production-guidelines.md | 5000 | sys_prompt「【短剧注意事项与合规/剪辑节奏规范如下】」 |
| 2 编剧剧本创作 | WRITER | dialogue-pacing | screenwriting-master/references/dialogue-pacing.md | 5000 | sys_prompt「【台词语速情绪与停顿重音标注规范如下】」 |
| 3 角色设计师造型 | CHARACTER_DESIGNER | five-view-template | character-turnaround-consistency/references/actor-sheet-template.md | 5000 | sys_prompt「【五视图一致性角色卡设定规则与示例】」 |
| 3 角色设计师造型 | CHARACTER_DESIGNER | performance-details | shot-design-master/references/performance-details.md | 5000 | sys_prompt「【角色表情细节与身体微动作描述规范】」 |
| 4 分镜师分镜拆解 | STORYBOARD_ARTIST | scene-design | shot-design-master/references/scene-design.md | 5000 | sys_prompt「【场景设计指南(场景圣经/功能化场景/空间布局/光影道具叙事)如下】」 |
| 4 分镜师分镜拆解 | STORYBOARD_ARTIST | director-shot-guide | shot-design-master/references/director-shot-guide.md | 8000 | sys_prompt「【导演拍摄分镜完全指南与运镜标准如下】」 |
| 4 分镜师分镜拆解 | STORYBOARD_ARTIST | emotion-expression | shot-design-master/references/emotion-expression.md | 5000 | sys_prompt「【情绪与面部表情提示词库(把抽象情绪转为可观察微表情/眼神/肢体)如下】」 |
| 4 分镜师分镜拆解 | STORYBOARD_ARTIST | action-choreography | shot-design-master/references/martial-arts.md | 5000 | sys_prompt「【电影级武打镜头设计指南(力学受力反馈/五镜动作链/防越轴/慢动作卡点)如下】」 |
| 4 分镜师分镜拆解 | STORYBOARD_ARTIST | shot-continuity | shot-design-master/references/plot-shot-coherence.md | 5000 | sys_prompt「【情节与镜头连贯性提示词(六锚点/连续性圣经/承接上一镜/逐镜单动作)如下】」 |
| 4 分镜师分镜拆解 | STORYBOARD_ARTIST | continuity-design | shot-transitions-master/references/continuity-design.md | 5000 | sys_prompt「【连续性与180度轴线防跳轴规范如下】」 |
| 5 视觉总监多镜头生成 | VISUAL_DIRECTOR | visual-style | production-knowledge-master/references/visual-style.md | 全文 | 全文读入后由阶段 5 自行切片：`visual_style_doc[:1000]` 进 compile_image_prompt 的 visual_style 字段（首帧图与尾帧图两处拼装点） |
| 8 宣发Agent引流 | PR_AGENT | highlight-detection | production-knowledge-master/references/highlight-detection.md | 6000 | sys_prompt「【高光识别、强度和观众行为标签规范】」 |
| 8 宣发Agent引流 | PR_AGENT | production-guidelines | production-knowledge-master/references/production-guidelines.md | 5000 | sys_prompt「【平台、AI标识、版权、投放与指标规范】」 |
| 全阶段质检 | QC Hook（run_real_consistency_check） | consistency-checklist | production-knowledge-master/references/consistency-checklist.md | 3500 | user_prompt 尾部「请参考以下一致性检查清单……」清单段 |
| （不走章节装载） | 多角色 | negative-prompts | production-knowledge-master/references/negative-prompts.md | — | 见下节「负面提示词」 |

- 阶段 6（音频总监配音音效）与阶段 7（合成发布渲染合流）无 LLM 提示词章节，
  stage_sections() 对应空元组；历史生产教训以产物 dict 形式附加（见「进化机制」）。
- 预算是 manifest 登记的默认值，调用方可用 `load_section(key, budget=...)` 覆盖，
  但覆盖值必须与该调用点的既有截断保持一致——迁移是换管道，不是改内容。

## 负面提示词

负面提示词（negative-prompts，production-knowledge-master/references/negative-prompts.md）**不走章节装载**（表中预算为「—」的原因）。它在编译期被
人工蒸馏为 `agent_council.NEGATIVE_MODULE_WORDS` 模块词表（模块 id → 精选负面词串，
每模块只保留压制力最强的少数词），运行时由委员会按角色开出模块配药单
（negative_prompt_by_role），经 `agent_council.compile_negative_prompt` 编译成
`(避免：…)` 词串，最终注入以下**六个生成点**：

1. 阶段 3 五视图角色卡生成：`designer_negative` 经 `gateway.generate_character_sheet(extra_negative=...)` 拼入（model_gateway 的 sheet prompt 尾部）；
2. 阶段 4 九宫格分镜静帧 `img_prompt` 挂尾：`storyboard_negative`；
3. 阶段 5 每镜视频提示词的 `continuity_suffix`：`visual_negative_video`（与 CLONE_NEGATIVE 叠加，含时序模块 temporal_continuity）；
4. 阶段 5 首帧图 `img_prompt`：`visual_negative_image`（图像侧编译时剔除 temporal_continuity——静帧发时序词是纯噪声）;
5. 阶段 5 尾帧图 `end_prompt`：`visual_negative_image`（同上，图像侧）；
6. 多集连续生产线锚点首帧 `img_prompt`：`episode_negative_image`（VISUAL_DIRECTOR 配药单，图像侧剔除时序模块）。

另有两处只做产物登记不做编译：阶段 3/4 把模块 id 列表写入
`assets["3_negative_prompt_modules"]` / `assets["4_negative_prompt_modules"]`，
阶段 6 音频总监的模块清单写入产物 dict——它们是审计痕迹，不进生成提示词。
迁移与审计时：负面词的任何调整都改 NEGATIVE_MODULE_WORDS 词表，**不要**试图把
该 md 接进 load_section。

## 进化机制

learned/ 是本技能包唯一可写区，双文件结构：

- `learned/lessons.jsonl`：教训库，每行一条 LessonRecord —— `id`、`stage`(1-8)、
  `rule`(≤200字符祈使句)、`trigger`(qc_finding/repeat_failure/manual)、`evidence`、
  `score`、`hits`、`status`(candidate/active/retired)、`created_at`、`updated_at`；
- `learned/evolution_log.jsonl`：进化流水账，promote_and_prune 的每次晋升/退休变更
  追加一行，供归档与回溯。

生命周期 candidate → active → retired：

1. **收割**：run_real_consistency_check 产出质检报告后调用
   `harvest_from_qc(stage, report, task_id, llm=...)`，从低分/失败项蒸馏候选教训；
   写入前按规则文本去重（规范化精确匹配 + 字符 3-gram Jaccard ≥ 0.6 视为同一条
   → hits+1、score 上调，不新增）。无 llm 或调用失败返回空列表，fail-soft，
   绝不阻塞流水线。
2. **晋升**：`promote_and_prune()` 把 hits ≥ 2 的 candidate 晋升为 active。
3. **淘汰**：每阶段 active 上限 **12 条**，超限按分数退休最低者（status=retired，
   不物理删除——审计需要）。
4. **注入**：`stage_lessons_block(stage, budget=900)` 取该阶段 active 教训
   （按 score*hits 降序，默认取前 6 条），组装成
   「【历史生产教训(自动进化，按命中率排序)】」块，追加进该阶段 sys_prompt；
   阶段 6/7 无 LLM，则放进产物 dict。预算 900 字符，行边界截断。

**为什么教训与正典物理隔离**：正典（各技能 references/ 下登记的知识章节）是人写的、经委员会 SHA-256
指纹校验的事实源，变更走人工评审 + 指纹更新流程；教训（learned/）是机器从质检
报告蒸馏的产物，按命中率自动晋升淘汰、随时可能被覆盖修正。两者信任等级与变更
流程完全不同——把机器产物混进指纹保护区会污染事实源、打碎 fail-closed 校验；
同一份正典存两处则必然漂移。所以教训永远只活在 learned/，每份正典只在它所属技能里存一份。

## 全流程铁律速查（蒸馏核心）

从 16 份正典各提取 1-2 条最高杠杆规则，作为**给人看的索引**——快速回忆某份文档
"最不能违背的那条"。此表**不进提示词**（进提示词的是 load_section 装载的正典原文
与 stage_lessons_block 的教训块），细节以各技能里的原文为准。

| 来源文档 | 铁律 |
|---|---|
| production-knowledge-master/references/consistency-checklist.md | 每阶段产物先过角色/性格/能力三重一致性核查；"同角不同脸、同脸不同装"即返工 |
| screenwriting-master/references/dialogue-pacing.md | 一句台词 = 文本+语速+情绪+停顿+重音，缺一不可；短剧语速比影视快 20-30%（基线 270-320 字/分钟） |
| production-knowledge-master/references/negative-prompts.md | 不要一次性堆满负面词——按场景挑模块叠加，关键项可加权（如 bad hands:1.4） |
| screenwriting-master/references/golden-narrative.md | 前 3 秒强钩子、每 30-60 秒一个冲突或反转、每集结尾留钩子——三者一个都不能少 |
| shot-design-master/references/director-shot-guide.md | 动作留在 AI 安全区：缓慢自然的动作稳定性最高；激烈对打必须拆镜而非单镜硬扛 |
| character-turnaround-consistency/references/actor-sheet-template.md | 每个角色先建五视图锚点（0°/45°/90°/135°/180°），所有出图出视频引用锚点，不得凭文字重新生成 |
| production-knowledge-master/references/production-guidelines.md | 黄金 3 秒法则：开头直接进事件核心，禁止铺垫/旁白/空镜开场；每集结尾 5 秒必设悬念 |
| shot-design-master/references/martial-arts.md | 武打按"出招-受击"正反打拆镜，每镜写物理受力反馈（重心沉降、扬尘、击退滑痕），拒绝单镜完成对打 |
| shot-design-master/references/performance-details.md | 表演 = 身体动作 + 面部驱动 + 口型同步分层生成；先锁角色参考再谈表演 |
| shot-transitions-master/references/continuity-design.md | 连续性优先级：角色 > 光影 > 色调 > 背景 > 运动；前后镜色调光线矛盾按最高优先级修 |
| shot-design-master/references/scene-design.md | 先定场景功能再定空间布局，先找光再定构图；场景是剧情压力的容器，不是漂亮背景 |
| production-knowledge-master/references/highlight-detection.md | 高光 = 观众情绪峰值（反转/逆袭/对抗/情感爆发……）；宣发主张只能来自正片真实高光 |
| production-knowledge-master/references/visual-style.md | 一部剧锁一种画质风格（帧率/色彩/画幅成套），题材定风格，跨镜不混搭 |
| shot-design-master/references/emotion-expression.md | 不写抽象情绪词，写可观察的面部肌肉/眼神/嘴部/呼吸/肢体（"眉心收紧、指节发白"） |
| shot-design-master/references/plot-shot-coherence.md | 每镜锁六锚点（人物/空间/动作/情绪/道具/光影），承接上一镜最后一帧，每条只推进一个小动作 |
| screenwriting-master/references/genre-summary.md | 先定题材类型再定调：题材决定爽点公式、视觉基调与目标人群，不做无类型定位的剧 |
