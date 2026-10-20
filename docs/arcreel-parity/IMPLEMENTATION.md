# ArcReel 能力对照：实现

全部为清洁室实现：按 `RESEARCH.md` 归纳的行为在本项目既有架构（任务 JSON + 八阶段流水线）
里重做，不引入 ArcReel 的代码、提示词、Schema 或界面。

## 1. 源文库：整本源文与逐集原文

**语义（ArcReel ADR 0031 / 0036）**：一份文件在项目里扮演一种角色——

| 角色 | 含义 | 进入第 2 阶段的方式 |
|---|---|---|
| `source` 整本源文 | 一份或多份文件按顺序拼成整本，由分集规划切成集 | 拼接后作为引擎的 `source_text` |
| `episode` 逐集原文 | 每个文件就是一集自己的原文，排在切出的集之后 | 作为 `own_episodes` 逐条进入账本 |
| `reference` 参考资料 | 只给人读 | 不进入 |

每个源文件记录体裁 `novel`（改编）/ `screenplay`（逐字提取），导入时按内容自动识别，可改。
账本条目新增 `source_origin`（`cut` / `own` / `none`）、`source_text`、`source_kind`、`source_name`。
引擎按**每集**的来源决定读什么、按什么口径规划（`ScreenwritingEngine.entry_kind`），
混合体裁的项目整体按小说口径。渲染时自带原文的集逐字呈现自己的原文。

- 角色默认从文件名推断（`story` / `小说` / `全本` → 整本源文；`episode_3` / `第3集` → 逐集原文），
  人可以改；逐集原文的顺序：显式 `order` > 文件名里的集号 > 上传顺序，界面可前移 / 后移。
- 源文件内容、角色、体裁、顺序任一改变，已写好的结构化剧本标记为过期（`stale`）。
- 请求集数同时覆盖逐集原文：整本源文切出 `episode_count - 逐集数` 集；整本源文切不完时集数自动增长。
- 旧路径（自由文本引擎）也从文库取源文：整本源文 + 按集号编排的逐集原文合成一份手动剧本。

代码：`backend/app/core/screenwriting/{models,engine,renderer}.py`、`backend/app/service/screenwriting_service.py`
（`library_sources` / `source_for_task` / `ordered_documents`）、`backend/app/service/drama_service.py`（文库 CRUD）、
`frontend/src/features/writer/{ScriptLibrary.tsx,scriptLibraryApi.ts,ScreenwritingPanel.tsx}`。
接口：`GET/POST/PATCH /api/drama/{task_id}/script-documents` 新增 `role` / `source_kind` / `order`；
响应带 `position`（播出位次）与 `episode`（账本分配的集号）。

## 2. 批量视频准入

**语义（ArcReel ADR 0061）**：第 5 阶段开始前把全部镜头一起评估，结论三选一：

- `admitted`：全部可生成；
- `confirmation_required`：唯一的未决事项是剧本时长不在模型档位内，需按“剧本 N 秒 → 请求 M 秒 × 几镜 · 费用”确认档位；
- `blocked`：零任务、零费用；每镜列出自己的问题码（`needs_replan`、`mixed_speech`、`missing_assets`、
  `unresolvable_model`、`provider_not_ready`、`active_task`），通过的镜标为 `generation_batch_admission_withheld`。

每镜报价 `generate` / `reuse`（已有未过期片段，免费）/ `blocked`；预估费用来自定价表，
任一镜未定价则该档位不显示总额。确认过的档位记在项目配置 `confirmed_request_durations` 里。

代码：`backend/app/core/video_admission.py`；第 5 阶段入口 `DramaService._assert_stage_prerequisites`；
接口 `POST /api/drama/{task_id}/shots/admission`；界面 `ShotVisualWorkspace` 顶部的准入面板。

## 3. 供应商调用台账与参考费用

**语义（ArcReel ADR 0009 / 0053 / 0076）**：每次供应商调用（文本 / 图片 / 视频 / 语音）是一条记录：
目的、供应商、模型、成功与否、消耗单位（token / 张 / 秒 / 千字）、参考费用与币种。

- 网关的 `call_llm` / `generate_image` / `generate_character_sheet` / `generate_video` 各记一条；
  文本调用从响应里读 token 数。
- 记录写在当时运行的项目上（`task["usage_records"]`，上限 5000 条），阶段执行与逐集制作
  通过 `usage_ledger.bind_task` 绑定；项目外的调用留在内存。
- 价格不写进代码：`backend/runtime/model_pricing.json`（或 `MODEL_PRICING_PATH`）按模型声明
  `per_million_tokens` / `per_image` / `per_second` / `per_thousand_characters`，样例在
  `backend/app/data/model_pricing.example.json`。未定价的模型照记，汇总里单列“未定价调用数”。
- 汇总按币种分列，从不相加；主币种是金额最大的那个。

代码：`backend/app/core/usage_ledger.py`、`backend/app/core/providers/pricing.py`；接口 `GET /api/drama/{task_id}/usage`。

## 4. 口播归属、旁白交付与字幕草稿

**语义（ArcReel ADR 0089）**：一镜只有一种口播。

- `speech_mode(scene)`：`character_speech` / `narrator_voiceover` / `silent`；混合即 `mixed_speech`：
  模型重写时退回，人工保存时标记 `needs_replan`，批量准入时阻断。
- 项目配置 `narration_delivery`：`use_tts`（默认，与原行为一致）或 `post_production`
  （第 5 / 6 阶段只合成角色台词，旁白留给后期；旁白从不进入视频提示词）。
- 字幕草稿：每镜的台词与旁白按句切分（中文按 。！？…，英文按 .!? 后空格），按阅读量在该镜时长内分配，
  `GET /api/drama/{task_id}/subtitles?episode=N&format=srt|json`。它是起点，不是对齐音频的成品。

代码：`backend/app/core/screenwriting/speech.py`、`backend/app/core/subtitles.py`、`violations.py`。

## 5. 资产名即身份：改名级联与合并

**语义（ArcReel ADR 0057）**：角色 / 场景 / 道具没有独立 id，名字就是它在剧本规划、分解表、
设定集与分镜里的引用方式。

- 改名是一次原子级联：编剧库存、分镜规划与正式剧本（出场列表、说话人）、小说体正文、
  分解表（角色、关系、场次出场、拍摄资产）、角色设定集与设定图、第 4 阶段分镜的出场列表全部改写；
  已按旧名生成的视频片段标记为过期（准入时按“重新生成”报价）。旧名留作别名。
- 合并把失败方的全部引用指向保留方，失败方的名字成为保留方的别名；保留方缺的描述由失败方补上。
- 两者都先给出预览（各处引用计数、涉及集数、将过期的镜头），确认后才写入；名字比较忽略首尾空白与
  Unicode 归一化差异；改成已存在的名字会被拒绝并提示用合并。

代码：`backend/app/core/asset_identity.py`；接口 `POST /api/drama/{task_id}/assets/rename|merge`
（`dry_run` 只预览）；界面 `frontend/src/features/writer/AssetIdentityPanel.tsx`（人物关系图下方）。

## 6. 视频任务续查与片段复用

**语义（ArcReel ADR 0006 / 0007）**：供应商一旦接单就在计费，重启后绝不重投。

- 网关在供应商接单的那一刻把任务号记到项目上（`5_jobs`，键为「镜号:候选序号」），连同请求指纹
  （运镜契约指纹、秒数、参考模式）；任务结束再记下片段地址或失败原因。火山 Ark、MiniMax H3 与
  Kling / Grok / fal / LTX 适配器都接了。
- 服务启动时，对所有「已接单、未记结果」的任务按供应商续查到结束，记下片段；无法续查的供应商
  标失败并写明原因。续查只轮询，不提交。
- 第 5 阶段每生成完一镜就把结果持久化，中断最多丢在途的那一镜；重跑时同一请求（契约指纹相同、
  参考模式相同、未过期）直接复用上一轮片段或续查取回的片段，不再向供应商付费。

代码：`backend/app/core/video_jobs.py`、`ModelGateway._ark_wait / resume_video_job`、
`DramaService.resume_interrupted_video_jobs`、`backend/main.py` 启动钩子。

## 7. 单镜重做与自定义供应商

- **单镜重做**：`POST /api/drama/{task_id}/shots/{shot_id}/regenerate` 把该镜片段标记为过期并忘掉它的任务记录；
  重跑第 5 阶段时只重做这一镜，其余镜头按第 6 节复用。镜头工作区有「重做本镜」按钮。
- **自定义 OpenAI 兼容端点**（ArcReel ADR 0008 / 0068 的收敛版）：模型配置中心的文本与图片分类新增
  `custom_openai`，接受任意公网 HTTPS 根地址（仍禁止 http、非标端口与内网地址），模型目录从 `/models` 读取，
  调用走 OpenAI 兼容的 `/chat/completions` 与 `/images/generations`。视频仍只走有适配器的供应商。

## 8. 分集账本操作：手工切分、建 / 移 / 删集、候选重规划

**语义（ArcReel ADR 0031 / 0032）**：分集账本是「一集是什么」的唯一记录；人可以直接改它，模型只在写出新集时参与。

- **纯状态操作**（`backend/app/core/screenwriting/ledger_ops.py`，不调模型）：按位置拆分一集、移动两集之间的边界、
  并入下一集（可一并吞掉中间未切分的原文）、把未切分原文切为一集、从某集之后清空、新建一集（自带原文或按大纲）、
  移动一集（切出集必须保持原文顺序）、删除一集、改自带原文。每个操作返回新状态、它丢弃了哪些已写出的集、
  新建了哪些集、以及全局重编号映射；账本号、`episodes` 键、场景号 `E{n}S..`、待重拆标记与违约记录一起改号。
- **影响预览与确认**：丢弃已写出的集必须在 `confirm_discard` 里点名（否则 409 并列出集号）；界面先取
  `POST …/ledger/impact?episode=` 看该集有多少分镜 / 是否有正文，再问一次。下游（角色 / 分镜 / 成片）归档沿用
  `update_script` 的 `confirm_invalidate` 语义。操作后未写出的集立刻由引擎 `write_missing` 写出
  （`write_now=false` 则只改账本）；`config.episode_count` 以账本长度为准。
- **候选重规划**：`POST …/screenwriting/replan {from_episode}` 从该集原文起点重新按锚点规划到源文末尾，结果作为
  候选放在账本旁（绑定账本布局指纹与源文指纹）；`candidate` 对比给出新旧集数、平均字数、每个新集与旧集的关系
  （边界不变 / 重新划分 / 新增）以及会被替换的已写出集。采纳时新切分集插入原位置并写出；被替换的已写出旧集默认
  留在末尾（无原文、`stale`），`delete_replaced` 则直接丢弃；账本或源文变过则候选不可采纳。放弃即删候选。
- 路由：`GET …/screenwriting/ledger`、`GET …/ledger/source?start=&end=`、`POST …/ledger/impact`、`POST …/ledger/ops`、
  `POST …/replan`、`POST …/replan/adopt`、`POST …/replan/discard`。
- 界面：编剧面板顶部「分集账本」区（`EpisodeLedgerTools.tsx`）：每集的来源 / 原文首尾 / 字数 / 状态与操作按钮，
  未切分段一行一个可「切为一集」，拆分编辑器按句子或字符位置选断点并预览前后文，候选对比面板可采纳或放弃。

## 9. 审核确认门（软门）与违约草稿隔离

**语义（ArcReel ADR 0080 / 0002）**：写出的集要有人确认；确认绑定规划指纹，改了就得复审；违反规则的草稿不混进正式剧本，修好才算数；修复不能把东西改坏。

- **审核状态**（`backend/app/core/screenwriting/review.py`，不调模型）：每集五态 `missing / draft / pending / changed / confirmed`。
  确认记录 `state.reviews[n] = {revision, confirmed_at, by}` 绑定该集 `plan_revision`；之后任何分镜编辑、修复或重写都会换指纹，
  状态自动回到 `changed`。账本重编号时记录跟着改号，删集的记录随之消失。
- **软门**：第 3 阶段起步前把 `review.gate_record` 写到 `assets["2_review_gate"]`（`soft: true`、`passed`、`pending / changed / drafts`、
  一句话 `message`），未全部确认只记日志、不抛错；工作流下一步提示在「接下来是第 3 步」后点名未确认集并说明不拦截。
  本项目按用户决定做软门；要改成硬门只需在 `_assert_stage_prerequisites` 里对 `passed=False` 抛 `StagePrerequisiteError`。
- **草稿隔离**：引擎多轮仍过不了的软违约（口播超最长档、非逐字、混合口播；源文模式还含集太短）不再只是降级成警告，
  而是写进 `episodes[n].draft = {reasons, origin: model|repair|edit, attempts}`；人工编辑留下软违约同样成草稿，改干净即解除。
  草稿不能确认（409，列出原因）。
- **AI 修复与不劣化**：`POST …/screenwriting/episodes/{n}/repair` 把草稿原因与上一版规划 JSON 附在规划提示词后让模型重写
  （正文与视觉层随之重做），通过则解除隔离；仍不通过但违约条数减少则存为新草稿；没有减少则 `RepairNotImproved`，原草稿原样保留、
  接口返回 `repair.improved=false`。修复走 `update_script`，下游归档沿用 `confirm_invalidate`。
- 路由：`GET …/screenwriting/review`、`POST …/screenwriting/episodes/{n}/review {action: confirm|reopen}`、`POST …/episodes/{n}/repair`；
  状态接口的每集摘要与单集响应带 `review`，状态接口另有 `reviewSummary`。
- 界面：编剧面板顶部审核进度条（已确认 x/y、软门说明），每集徽标，展开集内「确认本集 / 复审确认 / 重新打开 / AI 修复违约」，
  草稿原因列表；有未保存改动时不能确认。

## 10. 持久化生成队列：分桶限流、依赖、只取消排队项

**语义（ArcReel ADR 0083 / 0043 / 0006）**：付费调用进队列，队列落盘；按供应商 × 媒介限并发；项可依赖项；只有排队中的能取消。

- **队列**（`backend/app/core/generation_queue.py`）：项 `{key, label, family, medium, depends_on, status, meta…}`，状态
  `queued → running → done | failed`，另有 `cancelled`（撤回）与 `skipped`（依赖失败 / 取消而连带）。桶 = `供应商族/媒介`，
  上限先取 `GENERATION_CONCURRENCY_<媒介>`（video 2 / image 3 / audio 2 / text 3），再取 `GENERATION_CONCURRENCY_<媒介>_<族>`。
  `run()` 在共享线程池里派发可运行项（依赖全部 done 且桶未满），每次变化都把快照 `persist` 到 `assets["5_queue"]`；
  工作线程继承调用方的 contextvars，台账与视频任务记录因此仍落到正确的项目。
- **第 5 阶段**：先串行为每镜准备提示词 / 契约 / 参考（不调供应商），再入队三项：`frames:N`（缺首帧或需精确尾帧时，图像桶）
  → `video:N`（候选依次生成，任一失败即停，视频桶）→ `assemble:N`（配音与入片，音频桶）。每镜装配完成即按镜序写回
  `assets["5"]`，中断只丢在途的镜；失败项汇总后抛错，重跑复用已完成的。
- **取消与暂停**：`POST …/queue/{key}/cancel` 把撤回请求记在库里，运行器在下一次派发前执行；运行中的项不能取消
  （已付费），完成后结果保留。`…/queue/cancel-queued` 撤回全部排队项。工作流「暂停」在阶段内即停止派发（剩余项标 `paused`）。
  撤回过的运行以明确原因结束，已完成的保留，重跑只补剩余。
- **重启**：启动时 `reconcile_generation_queues` 把死进程留下的 `running` 项回到 `queued`，除非供应商任务号仍在
  （由 `video_jobs` 续查）。
- **仓储修复**：`save_task` 以库里的 `usage_records`、`assets["5_jobs"]`、`assets["5_queue"]` 为准合并，阶段线程的进度保存
  不再覆盖 sink 写入；`storyboard_concurrency` 的线程池同样继承上下文。
- 界面：镜头工作区「生成队列」区块：计数、各桶 `运行/上限`、逐项状态与依赖、排队项的「取消」、「取消全部排队」、刷新。

## 11. 多凭据、声明式视频端点与 ComfyUI

**语义（ArcReel ADR 0016 / 0054 / 0051 / 0067 / 0081）**：一个供应商可以有多把 Key，按任务类型分桶轮换；视频供应商可以用数据声明；ComfyUI 以工作流为单位接入。

- **凭据池**（`app/core/credential_pool.py`，表 `model_configuration_credentials`）：每个模型配置除主 Key 外可加备用 Key，
  每把可限定任务类型桶（text / image / video / audio，空为任意）。调用取本桶可用的 Key 轮换；供应商以 401 / 403 / 429
  拒绝的 Key 冷却 `CREDENTIAL_COOLDOWN_SECONDS` 后再参与，其它错误不换 Key。网关文本 / 图片的运行时分支与视频适配器
  都走 `_with_credentials` / 同样的轮换；Key 只以密文落库，列表只给尾号与冷却状态。
- **文本模型**：文本分档已于 2026-10-15 移除。每次文本调用都用项目所选的文本模型；该模型未在配置中心启用时，
  阶段开始时改用全局选择的文本模型（配置中心第一个启用的文本模型）并写回项目，网关对未启用的模型名同样改走它，
  不再落到环境变量里的旧 Key。
- **声明式视频端点**（`app/core/providers/declarative_video.py`）：`VideoEndpointSpec` 用 JSON 描述 提交（方法 / 路径 /
  请求体模板，`{{prompt}}` 等占位符保持类型）→ 读 `job_id_path` → 轮询（状态路径、成功 / 失败值、片段 URL 路径）；
  `DeclarativeVideoAdapter` 复用现有适配器的任务循环与 `video_jobs` 登记。配置中心 `PUT /settings/video-endpoints/{family}`
  保存（Key 加密），注册表让路由 `normalize_video_provider` 按模型 ID 认出该族，模式与参考上限来自声明，缺 Key 时不就绪。
- **ComfyUI**（`app/core/providers/comfyui.py`）：服务地址、工作流（API 格式）与绑定来自环境变量（ComfyUI 多在内网，
  不走公网 URL 校验）；`status()` 报告 配置 / 工作流 / 绑定 三项，缺一不就绪，不就绪时网关不发任何请求；就绪后
  `POST /prompt` → `GET /history/{id}` → `/view` 取图或片段，项目里把图像 / 视频模型选为 `comfyui` 即可。用户目前没有工作流，
  界面只显示状态与接入步骤。
- 路由：`POST/PATCH/DELETE /api/model-configurations/{id}/credentials[/{cid}]`、
  `PUT/DELETE /…/settings/video-endpoints/{family}`；`GET /api/model-configurations` 返回每配置的 `credentials` 与 `settings`。
- 界面：模型配置中心「备用凭据」（每配置）、「声明式视频端点」（视频页）、「ComfyUI 状态」（图像 / 视频页）。

## 12. 剪辑时间线、配乐库、剪映草稿与素材审看

**语义（ArcReel ADR 0090 / 0095）**：成片不是一键黑盒，而是一条人能改的时间线；配乐来自库；可以导出到剪映继续剪；每条素材有人审看。

- **时间线**（`app/core/edit_timeline.py`，存 `assets["7_timeline"]`）：片头卡、每镜一条（入 / 出点、字幕、配音、静音、候选版本、
  转入转场、审看结论与备注）、配乐（无 / 第 6 阶段生成 / 配乐库，音量与台词闪避）、环境音。首次读取时从第 5 / 6 阶段构建；
  第 5 阶段片段变了（指纹不同）则刷新，未变的镜保留已有裁剪与审看；每次编辑 `revision + 1`。`render_plan` 把它翻译成
  合成器参数（打回的镜不入片）；`compose_film` 新增 `trims` 与 `bgm_volume`。第 7 阶段与 `POST …/timeline/render` 都按时间线渲染，
  后者不重跑阶段、只更新 `assets["7"]` 与成片地址。
- **素材审看**：`review` 操作记录 通过 / 打回 / 待审看 与备注；打回的镜留在时间线上但不入片，配合「重做本镜」重生成后自动回到待审看。
- **配乐库**（`app/core/bgm_library.py`，`runtime/bgm/` + `index.json`）：上传按字节头校验（MP3 / WAV / M4A / AAC / OGG，≤ 20MB），
  第 6 阶段生成的配乐可留库；`GET/POST/DELETE /api/library/bgm`、`GET …/{id}/audio`。时间线按 id 选用，合成器拿到本机路径。
- **剪映草稿**（`app/export/jianying.py`，`GET …/timeline/jianying.zip`）：`draft_content.json`（画布、素材 videos / audios / texts、
  轨道 video / audio / text 的 segment 以微秒计，裁剪写进 `source_timerange`，片头与打回镜按时间线处理，转场挂在段上）与
  `draft_meta_info.json`（名称、时长、素材清单），素材复制到 `materials/` 并用 `##_draftpath_##` 相对引用；不在本机的片段列在
  `skipped` 与响应头里，不伪造。格式按剪映自身文件的字段整理，属尽力兼容。
- 界面：第 7 阶段页「剪辑时间线」面板：逐镜预览、入出点、转场、字幕、静音、候选、通过 / 打回，片头，配乐（无 / 生成 / 库 / 上传 / 音量），
  「按时间线重新合成」与「下载剪映草稿」。

## 13. 嵌入式工具助手与远程 MCP

**语义（ArcReel ADR 0003 / 0028 / 0065 / 0087）**：Agent 用的是产品自己的能力，而不是另一套；站内助手与站外 Agent 共用一份工具；花钱的事先问人。

- **工具目录**（`app/core/agent_tools.py`）：每个工具有名称、说明、JSON Schema 参数与效果等级：`read`（只读）、`write`
  （改项目不花钱）、`paid`（会调模型，必须显式 `confirm=true`，否则只返回 `needs_confirmation` 与将要发生什么）。
  `catalog.call` 以调用者身份运行：项目必须属于该用户（管理员除外），工具内的业务错误作为结果返回而不是崩溃。
  当前 16 个：列项目 / 看状态 / 看剧本与审核 / 看一集 / 看镜头 / 看时间线 / 看队列 / 看费用；确认或重开一集 / 编辑时间线 /
  取消排队项 / 暂停结束 / 标记重做；执行阶段 / 一键成片 / AI 修复一集 / 按时间线重新合成。
- **嵌入式助手**（`app/core/embedded_agent.py`）：聊天里 `/agent …` 进入；模型（快速档）在一个小 JSON 信封里二选一：
  调用工具或回答用户。read / write 工具立即执行并把结果喂回模型（一轮最多 4 次），paid 工具变成提案记在
  `task["agent_pending"]`，`/confirm` 执行、`/cancel` 放弃；非 JSON 的回答当作普通回复，模型不守格式也能说话、只是不能动手。
  转录记在 `task["agent_history"]`，回复同时进聊天记录；其它消息仍走原来的工作流助手。
- **远程 MCP**（`app/api/mcp_api.py`）：`POST /mcp` 为 JSON-RPC 2.0（`initialize` / `ping` / `tools/list` / `tools/call`，
  通知回 202；`GET /mcp` 405，说明不做服务端推流）。`Authorization: Bearer mcp_…` 的令牌代表用户，由用户中心
  `POST/GET/DELETE /api/mcp/tokens` 签发 / 列出（只给尾号）/ 撤销，库里只存哈希。`tools/list` 带 `readOnlyHint`，
  说明前缀 `[read|write|paid]`；`tools/call` 返回文本与 `structuredContent`，付费工具同样等待 `confirm`。
- 界面：聊天快捷命令新增 `/agent`、`/confirm`、`/cancel`；用户中心新增「MCP 令牌」卡片（签发一次性显示、列表、撤销）。

## 14. 创作类型：剧情、旁白解说、广告短片

**语义（ArcReel ADR 0033）**：同一条流水线做三种东西，区别在怎么写、怎么查、多长。

- `app/core/creation_modes.py`：`config.creation_mode ∈ {drama, narration, ad}`，缺省或未知为 drama（老项目不受影响）。
  - **旁白解说**：写作指引要求每个有口播的分镜只用旁白、角色只表演；校验对含角色台词的分镜报
    `mode_dialogue_in_narration`（错误，退回模型重写；多轮仍不改则作为违约草稿隔离，人工编辑时降为警告）。
  - **广告短片**：`config.ad_brief = {product, selling_points, audience, call_to_action}` 写进写作指引（以简报为准、不得编造功效）；
    单集框架换成 至少 3 镜、15–60 秒（`CREATION_AD_MIN_SCENES / _MIN_SECONDS / _MAX_SECONDS` 可改）；最后一镜的画面或口播里
    没有行动号召时给 `ad_missing_call_to_action` 警告。
- 接线：`build_engine` 把类型指引放在用户指令前、用类型的单集框架、把类型与简报交给引擎做额外校验；写作看板按项目类型的框架
  标注不成形的集；自由文本引擎的逐集重拆也用它；第 8 阶段宣发提示词追加类型说明；Agent 的 `get_project` 返回类型。
- 新建 / 更新项目请求新增 `creationMode` 与 `adBrief`；新建弹窗有「创作类型」选择，选广告时出现简报四栏。

## 15. 角色衍生形象与商品资产

**语义（ArcReel ADR 0072 / 0034）**：同一个角色有多种造型（年龄、服装、伤势、变身），由剧情决定用哪一种；商品是一等资产，外观以实物照片为准。

- **衍生形象**（`app/core/character_variants.py`）：衍生形象就是一个演员元素，元数据 `variant = {of, label, triggers, episodes}`
  指向来源角色。`PUT/DELETE /api/elements/{id}/variant` 设置 / 取消（只改这一个键，项目归属与 3D 元数据不动；只有演员可设；
  必须有触发词或集数范围之一）。
  - 场次层（`compile_scene_context`）：衍生形象不算角色，不进出场名单；场次文字含触发词（最长者优先）或场次所在集落在范围内时，
    该角色换上衍生形象的描述与参考图，提示词里的外观也随之改变。
  - 镜头层（`panel_context`）：单个镜头文字点名另一个造型（如闪回里的「少年」）时，只这一镜换上它；参考图标注 `variant`。
  - 视频参考（`merge_video_references`）：换了造型的角色由造型参考图锁定，基础五视图不再并列，避免两种外观互相打架。
  - 元素库加载按场次过滤时，已选角色的衍生形象随之保留，镜头仍可调用。
- **商品**：元素库第六类 `product`。镜头提到商品名（或别名）时绑定其照片（与道具同规则），提示词标「商品」。商品不是每个项目的必需资产；
  广告项目的简报写了商品时，资产就绪检查要求同名商品元素有照片，否则第 4 阶段前置检查给出「商品缺少参考图」。广告项目「从剧本提取」
  会按简报建好商品元素（不生成 AI 图片，等用户上传实物照片）；剧情 / 旁白项目的提取结果与以前完全相同。
- 界面：元素库新增「商品」页；演员卡片有「衍生形象」按钮（来源角色、造型名、触发词、起止集）与「衍生自 … · 触发 … · 第 x–y 集」徽标、「取消衍生」。

## 16. 风格参考图分析

**语义（ArcReel ADR 0023）**：风格不只从模版里挑，也可以拿一张图说“就要这个感觉”。

- `app/core/style_analysis.py`：给可看图模型的提示词只要求描述风格（媒介、光线、色板 hex 与落点、反差 / 色温 / 饱和、机身镜头颗粒、
  质感、构图、年代、情绪、3–5 条中英锁定短语、正负特征、可直接放进提示词的风格锚定句），不描述人物与情节、不写真实人名作品名；
  返回值按字段校验（`StyleProfile`），缺字段时说明缺了哪些。`to_pack` 把它变成一个完整 `StylePack`：id 为 `custom_<任务指纹>`，
  声音策略、情境负面词、反偷懒规则等图里说不出的东西继承同媒介的内置锁（真人 → 写实电影，二维 → 二维赛璐璐，三维 → 三维 CG）。
- `style_packs`：项目配置里存 `custom_style_pack`（完整定义）且 `style_pack` 等于其 id 时，`resolve_pack` 返回它并登记到进程内
  注册表，只拿到 id 的代码（视频网关）也能 `get_pack` 到；项目配置更新时连同存储的定义一起解析，不会被重置成默认锁。
- 网关 `describe_image`：用模型配置中心标为「多模态」的文本模型（优先项目所选模型，否则第一个），图片作为 OpenAI 兼容的
  `image_url` 内容段发送，走凭据轮换与用量台账；没有多模态模型时不发请求并说明。上传图先校验字节头，再缩到长边 1536 像素转 JPEG。
- 路由：`GET/POST /api/drama/{task_id}/style/reference`（上传分析，只展示不生效）、`…/apply`（设为本片风格锁，记下原锁，
  返回哪些阶段已有旧风格画面）、`…/revert`（恢复原锁）。
- 界面：第 1 阶段（总导演策划）页下方「风格参考图」面板：补充说明、上传分析、色板色块、光线 / 镜头 / 质感、锁定短语、设为本片风格 / 恢复原风格。

## 17. 界面三语与剧本内容语言

**语义（ArcReel ADR 0078）**：界面语言与剧本语言是两件事：前者是操作者看的，后者是成片里说的；两者都可选中文 / 英文 / 越南文。

- 界面：`frontend/src/i18n/index.ts` 以中文原文为键，`t(source, vars?)` 查当前语言字典，缺译回落中文（永远不会出现空白）；
  `{0}` / `{name}` 占位符在译文里按名字替换，所以词序可变。语言存浏览器 `localStorage`（`ui.locale`），默认中文，不读浏览器语言；
  切换即刷新（`useSyncExternalStore`），并写 `<html lang>`。`LanguageSwitcher` 挂在登录页与工作台右上角。
  字典 `en.ts` / `vi.ts` 由脚本按键排序生成；`scripts/i18n-coverage.mjs --check`（`npm run i18n:check`，也是一条 vitest 用例）
  把源码里每个 `t('…')` 以及若干动态来源（阶段名、聊天命令、创作类型、运镜 / 风格选项的 label 与 hint）都列成键，
  en / vi 任一缺译即失败。`apiFetch` 带 `Accept-Language`（中文时 `zh-CN,zh;q=0.9`，否则 `<当前>,zh-CN;q=0.5`），后端将来可据此回不同语言的文案。
- 剧本内容：`DramaCreateRequest.content_language`（zh / en / vi，默认 zh）存到 `config.content_language` 并镜像到 `source_language`
  （后者本来就是引擎的字数 / 语速口径：中文按字、英文与越南文按词）。引擎的公开入口（写作 / 补写 / 换规划 / 修复 / 候选重规划 / 提示词预演）
  都包在 `language_scope(self.language)` 里，这是一个 `ContextVar`，线程池工作线程也会继承；所有提示词里原来写死的「使用中文」改为
  `output_language_name()`，小说体正文规则明确「正文用该语言写作，逐字保留的口播除外；示例只示范写法不示范语言」。
  非支持的代码回落中文；作用域结束自动复位，不会串到别的项目。
- 新建项目表单多一个「剧本语言」下拉（`CONTENT_LANGUAGE_OPTIONS`），与「创作类型」并列；请求体字段 `contentLanguage`。
- 未翻译（有意）：后端接口返回的报错与提示（仍中文）、素材馆目录、3D 导演桌面板；聊天命令词（如「进度」）保持中文，因为后端按原词识别。

## 18. 市场：多市场源、零服务端

**语义（ArcReel ADR 0078 / 0079 / 0094）**：分享声明式端点不止于导入导出；浏览与安装靠本地后端加若干「市场源」仓库运转，不依赖任何中心服务与账号。

- `app/core/market.py`：市场源是一个 GitHub 仓库（`https://github.com/owner/repo[/tree/branch]`）或任意 https 目录 / 索引直链，
  解析成 raw 文件基址；索引 `market-index.json`（`schema: short-drama-market/1`，条目有 slug / name / version / kind / path / summary / author / tags）
  是浏览的唯一依据：未知可选字段忽略，主版本更高整份拒读，slug 重复、path 越界（`..`、绝对地址）都拒。安装时才抓那一份定义
  （`{meta, spec}`），meta 的 slug / 名称 / 版本 / 类型必须与索引一致，否则拒装、不以任一方为准。
- 抓取全链路只经 raw 地址：`MARKET_RAW_PROXY_PREFIX` 对 `raw.githubusercontent.com` 做前缀拼接（大陆可达性），其它主机原样。
  抓取是后端代用户发起的请求，按服务端请求伪造的暴露面对待：只 https，每一跳都解析域名并要求公网地址（复用 `settings.is_public_address`），
  最多 3 次重定向，索引 1MB / 定义 256KB 上限（先看 Content-Length，再按流读取截断），15 秒超时。
- 安装记录是独立实体（`market_installs` 设置项），与端点一对一，记来源市场源的规范键（`github:owner/repo@branch` / `url:<索引地址>`）、
  slug、安装版本与定义摘要；用键而非引用，删除市场源不抹掉记录。安装是单事务（`PlatformStore.put_settings` 同时写端点与记录）。
  已安装端点可原地编辑；状态两轴：市场轴 `latest` / `update_available` / `unavailable`（源停用、删除或条目下架），本地轴 `modified`
  （当前定义摘要 ≠ 安装摘要）。可更新只比较版本是否相等，同版本改内容不判可更新。更新保留原 API Key，被本地修改过的端点要先确认丢弃。
  族标识已属另一条目的不做跨条目转移（换族名安装）；本地非市场端点同名要显式确认覆盖；卸载就是删端点（`DELETE …/video-endpoints/{family}` 顺带删记录）。
- 官方市场源：`MARKET_OFFICIAL_SOURCE_URL` 预置，可停用不可删除；本项目没有运营方，所以 ArcReel 的官方服务覆盖层（安装量、评分、代开 PR）不做。
  贡献路径是 `POST /api/market/export/{family}` 导出「条目包」（定义文件 + 索引条目，不含 Key），由人向市场源仓库提 PR。
- 路由 `/api/market`：`sources`（列 / 加 / 停用 / 删 / 刷新）、`entries`（浏览，任何登录用户）、`installed`、`…/entries/{slug}/install`、`export/{family}`；
  改动需管理员。内嵌工具助手与 MCP 不暴露市场（ADR 0078：市场是用户功能）。
- 界面：模型配置中心「视频模型」页的「市场」区：市场源管理、条目浏览与安装 / 更新（带状态徽标）、已安装端点的来源与「导出条目包」。

## 验证

- `backend/tests/test_script_library_sources.py`：引擎 / 文库解析 / 服务层（含第 2 阶段读文库）。
- `backend/tests/test_video_admission_and_usage.py`：定价、台账、准入三种结论、第 5 阶段门禁、口播归属、字幕。
- `backend/tests/test_asset_identity.py`：预览不改动、改名级联、合并与别名、服务层重投影。
- `backend/tests/test_video_jobs.py`：接单登记、按请求指纹复用、重启续查不重投。
- `backend/tests/test_style_reference.py`：答案解析与字段校验、按媒介继承的风格锁、自定义锁的解析与按 id 查找、网关只把图片发给多模态模型、上传 → 分析 → 应用 → 提示词 → 恢复、坏图与无多模态模型的说明。
- `backend/tests/test_variants_and_products.py`：衍生形象校验与选择（触发词优先、最长触发词、集数范围）、场次换装不增角色、镜头级换装与基础五视图让位、商品按提及绑定、广告商品就绪与简报提取、剧情项目不受影响、衍生形象 API 与商品元素类。
- `backend/tests/test_creation_modes.py`：类型解析与回落、广告单集框架与环境覆盖、旁白台词 / 广告行动号召校验、指引与宣发文案、引擎按类型规划（旁白通过 / 台词退回成草稿 / 广告框架与警告）、`build_engine` 接线、建项目保存类型与简报。
- `backend/tests/test_embedded_agent.py`：工具目录（schema / 归属 / 付费确认 / 错误即结果）、助手回合（读后答、提案 → 确认 / 放弃、非 JSON 回复、其它消息仍走工作流助手）、MCP 令牌签发 / 遮蔽 / 撤销、JSON-RPC 初始化 / 列工具 / 调用 / 鉴权。
- `backend/tests/test_edit_timeline.py`：时间线构建 / 编辑 / 刷新保留、渲染计划、剪映草稿布局与打包、配乐库校验与留库、服务层 API（编辑、按时间线渲染、草稿下载）、第 7 阶段按时间线渲染。
- `backend/tests/test_provider_pools.py`：凭据轮换与冷却、网关换 Key、声明式适配器（提交 / 轮询 / 模式拒绝 / 校验）、路由认族、ComfyUI 未就绪不发请求 / 就绪后绑定与取片、配置中心 API 与运行时注册。
- `backend/tests/test_generation_queue.py`：依赖 / 跳过、只取消排队项、分桶上限、快照往返、运行器（限流、失败、撤回、暂停、上下文继承）、sink 记录在进度保存后仍在、重启整理。
- `backend/tests/test_screenwriting_review.py`：状态流转与指纹、重编号、引擎隔离 / 修复 / 不劣化、人工编辑成草稿、API 确认与修复、软门记录、工作流提示。
- `backend/tests/test_market.py`：索引 schema / 重复 slug / 越界 path、源地址解析与 raw 代理前缀、抓取边界（https、每跳公网、重定向上限、大小上限）、加源 / 浏览 / 权限、安装同事务落端点与记录、索引与定义不一致拒装、只比版本与本地修改保护、族标识不跨条目转移与显式覆盖、删源 / 停用保留记录并标不可用、卸载即删端点、官方源只停用、坏索引保留旧索引、导出条目包不含 Key。
- `backend/tests/test_content_language.py`：语言作用域嵌套与复位、按词计数、英文项目每条提示词都要求英文而中文项目不变、建项目的语言到达引擎。
- `frontend/src/i18n/*.test.ts(x)`、`src/App.test.tsx`：查字典 / 回落 / 占位符 / 切换与持久化、覆盖率检查、新建项目带 `contentLanguage`。
- `backend/tests/test_ledger_ops.py`：拆 / 并 / 移边界 / 切未切分段 / 清空 / 建 / 移 / 删 / 改原文、重编号、候选存 - 比 - 采 - 弃；服务层经 API 的确认与写出。
- `frontend/src/features/writer/ScriptLibrary.test.tsx`、`AssetIdentityPanel.test.tsx`、`ShotVisualWorkspace.test.tsx`（准入面板）、`EpisodeLedgerTools.test.tsx`（账本操作、拆分编辑器、候选采纳）、`ScreenwritingPanel.test.tsx`（审核徽标与摘要、确认 / 重开、草稿修复）、`TimelinePanel.test.tsx`（裁剪、审看、选配乐、重新合成、上传配乐）、`UserCenterPage.test.tsx`（MCP 令牌签发与撤销）、`ElementVariants.test.tsx`（衍生形象设置 / 徽标 / 取消、商品页）、`StyleReferencePanel.test.tsx`（上传分析、应用与旧画面提示、恢复、无多模态模型）。
