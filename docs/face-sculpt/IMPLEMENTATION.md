# 捏脸与右侧对话控制：实现

捏脸把一个角色的长相和表情习惯用一组固定控件捏出来，只改第 3 阶段角色记录里的那段描述
（`assets["3_characters"][i]["desc"]`）。设定集、分镜、视频提示词读的都是这一段，再由 `face_card` 拆成
「身份锚点 / 骨相 / 五官 / 皮肤 / 毛发 / 体态」六层，所以宫殿、街道、第一集到第三十集，每一镜拿到的都是同一张脸，
没有任何一个提示词构建器需要认识「捏脸」。

右侧对话（侧栏助手）和 MCP 客户端用同一份工具目录（`backend/app/core/agent_tools.py`）捏脸、改舞台。每次改动给界面
一张卡片（`ui_action`），并把因此过期的第 5 阶段片段数报出来；付费的步骤（重出定妆照、重跑片段、批量优化多场）
只提议，`/confirm` 才执行。

## 决定

| 决定 | 选择 |
|---|---|
| 存哪里 | 角色记录自己的 `face_sculpt` 键；描述 `desc` 改写，`assets["3_dna"]` 各造型状态的分层字段同步改写；不另起一套资产 |
| 怎么合成 | 每次保存都从第一次捏脸前的描述 `desc_before` 重新合成：称呼段原样留在最前（`cast_aliases` 靠它认人），捏出的各层带层名紧跟其后，原描述里与某个已选控件说同一件事的片段（同一层、含该控件 `replaces` 里的词）删掉，其余一字不动。捏多少次都不会层层加码；重置就是把 `desc_before` 放回去 |
| 控件 | 全在 `backend/app/data/prompt/face_sculpt.json`：6 层、31 个控件（`choice` 选项带写进提示词的短语；`scale` 五档 -2..2，中间档不写词）、6 个预设、5 个表情控件、19 种情绪（情绪词与 `emotion_table` 同一套）。`face_sculpt.py` 只有结构和逻辑 |
| 一句话捏脸 | 文本模型把要求翻成控件取值，服务端逐项核对（认不得的控件 / 选项 / 层 / 表情进 `unknown`，不整句失败），合到当前捏脸上；默认只预览（`apply=false`） |
| 撤销 | `history` 保留最近 6 步（`limits.history_limit`），每步一整份捏脸；撤销就是把那一步再保存一次（照样从原文合成）；重置才清历史 |
| 什么算改了脸 | 合成后的描述与现在的 `desc` 不同才算。只改表情、原样重存都不算：`revision` 不加、设定集不变成「待重出」、片段不标过期 |
| 过期 | 脸变了：记下当时的设定集地址 `sheet_at_save`，把这个人出镜的第 5 阶段片段标 `stale`；第 4 阶段的图不动。设定集是否过期不写标记，而是比对地址 |
| 元素库 | 保存后把新描述写回元素库里本项目的同名数字演员（`actor` 元素），下一个项目复用这张脸时读到的也是捏过的那版；库出错只进回执，不影响保存 |
| 费用 | 读、预览、保存、撤销、重置都不调用模型；一句话捏脸 1 次文本调用（记入用量账本，用途 `face_sculpt`）；重出定妆照 = 第 3 阶段、重跑片段 = 第 5 阶段，都是付费阶段 |

## 数据模型

```text
assets["3_characters"][i]
  desc                         合成后的描述；设定集、分镜、视频都读它
  face_sculpt                  face_sculpt.RECORD_KEY
    face: {控件键: 取值}        choice 填选项 value，scale 填 -2..2 的整数
    notes: {层键: 一句}         每层一句，≤ note_chars(60) 字
    expressions: {情绪键: {choices: {表情控件: value}, tell: ≤40 字, habit: ≤40 字}}
    preset: str                 先铺的预设名（界面改过任一控件后清空）
    revision: int               只数脸变了几次
    updated_at: float           脸最近一次变的时间
    label: str                  这一步怎么来的：手动调整 / 对话：{message} / 撤销到「{label}」
    history: [{id: 8 hex, at, label, revision, sculpt}]   保存前的那份入栈，最近 6 步；第一次入栈的是「捏脸前」的空白
    desc_before: str            第一次捏脸前的描述
    states_before: {state_id: {分层字段}}                   3_dna 各造型状态的原字段
    sheet_at_save: str          脸变时当时的设定集地址（record.sheet 或 assets["3_sheets"][name]）
assets["3_dna"].characters[].states[]   bone / features / skin / hair / body 随捏脸改写，重置放回
assets["3_character_dashboard"]         每次写后重算（接口与工具同一条写路）
assets["5"][clip].stale / stale_reason  下游标记（见「过期语义」）
```

`sheet_is_stale(record, task)`：`revision > 0` 且当前设定集地址等于 `sheet_at_save` → 设定集还是旧脸；重出设定集后地址变了，就不再过期。

`preview()` 的形状（接口、工具、卡片都用它）：`{description, face_text(近景实际进提示词的脸), layers{层: 短语}, issues[资产卡警告], expressions{情绪: 这个人怎么笑}, sheet_stale, stale_note}`。
`current()`：`{name, sculpt, revision, updated_at, label, history[{id, label, at, revision}], preview}`。
`save / revert / reset` 返回 `current()` 加 `downstream: {clips_marked, sheet_stale}`。

## 接口（`backend/app/api/face_sculpt_api.py`）

全部在 `require_owned_drama_task` 之下；写接口通过 `Depends(get_platform_store)` 拿元素库（与 `element_api` 同一个依赖）。

| 方法与路径 | 做什么 | 花费 |
|---|---|---|
| `GET /api/face-sculpt/catalog` | 控件表（按层）、预设、表情控件与情绪清单 | 无 |
| `GET /api/drama/{task}/characters/{name}/face-sculpt` | `current()` | 无 |
| `POST …/face-sculpt/preview` | 不保存，只看合成后的描述、近景里的脸、资产卡警告和表情写法 | 无 |
| `GET …/characters/{name}/sheet-prompt` | `{name, prompt, sheet_stale, revision}`：第 3 阶段重出这个人的设定集时会交给图像模型的画面描述，按 `regenerate_character` 的入参拼（描述、`director_style` 默认「真人电影写实」、题材、年代服装句、风格词表） | 无 |
| `PUT …/face-sculpt` `{face, notes, expressions, preset, label}` | 校验（422 说清哪个控件哪个值）→ 保存 → 重算角色总览 → 写回元素库；返回 `current + downstream + library` | 无 |
| `POST …/face-sculpt/instruct` `{message, model?, apply}` | 一句话捏脸：`{reply, patch, unknown, sculpt, preview, saved, current, library}`；没配文本模型 422「没有可用的文本模型」，离线模板的回答按没有算；模型一个可用改动都没给 422；`apply=true` 才保存（历史标签「对话：{message}」） | 1 次文本调用 |
| `POST …/face-sculpt/revert` `{snapshot_id}` | 退回历史里的某一步；不在了 404「这一步已经撤销不了了：只保留最近几步」 | 无 |
| `DELETE …/face-sculpt` | 重置：放回捏脸前的描述与各状态字段，清掉捏脸、表情习惯和历史 | 无 |

`library` 是元素库写回的结果 `{updated, element_id[, error]}`；`instruct` 不保存时为 `null`。

## 元素库写回（`backend/app/core/face_sculpt_sync.py`）

- `sync_actor_description_async(store, task, name, description)`：按 `task.owner_user_id` 分页 `store.list_elements(owner, "actor", page, 100)`，只认绑定到本项目（`element_in_task(metadata, task_id)`）且名字对得上（`normalized_asset_name`：角色名或第一个别名 ↔ 元素名或元素 `metadata.aliases`）的演员，`store.update_element(id, owner, name=None, description=...)`。找不到 `{"updated": false}`；库抛错记一条日志，原因放进 `error`，从不抛。
- `sync_actor_description(task, name, description)`：同步版，给工作线程（Agent 工具、第 5 阶段工人）用。与 `load_storyboard_elements` 同一条规矩：新开一个 `PlatformStore(settings.database_url())` 在自己的事件循环里跑完就关；已在事件循环里时抛 `RuntimeError`（`agent_tools._face_sync` 把它接成 `library.error`）。

## 工具（`backend/app/core/agent_tools.py`，侧栏助手与 `POST /mcp` 同一份目录）

效果分三种：`read` 只读；`write` 改项目、不走确认；`paid` 先返回 `needs_confirmation` 提议，`confirm=true`（聊天里 `/confirm`）才执行，提议里带 `quote` 说明这次花在什么范围上。

### 捏脸

角色名不分大小写与空格，也认第一个别名；找不到时把项目里的角色列出来。

| 工具 | 效果 | 做什么 | 回执 |
|---|---|---|---|
| `get_face_sculpt {name}` | read | 控件表（压成「键 → 名字：可选值」）、当前取值、合成后的描述、`sheet_stale`、可撤销的历史 | 控件表放最前，截断时不先丢它 |
| `get_sheet_prompt {name}` | read | 与 `GET sheet-prompt` 同一段文字（直接调 `face_sculpt_api._sheet_prompt`） | `{name, prompt, sheet_stale, revision}` |
| `preview_face_sculpt {name, face?, notes?, expressions?, preset?}` | read | 在当前捏脸上叠加改动看效果，不写 | `{patch, sculpt, description, face_text, layers, issues, expressions, sheet_stale}` |
| `sculpt_face {name, face?, notes?, expressions?, preset?, merge=true, label?}` | write | 叠加（或 `merge=false` 整份替换）并保存；对不上控件表的改动整条拒绝并列出原因 | 见下 |
| `revert_face_sculpt {name, snapshot_id?}` | write | 退回某一步；省略则最近一步 | 见下 |
| `reset_face_sculpt {name}` | write | 恢复捏脸前的样子 | 见下 |

三个写工具的回执：`{name, revision, label, description, face_text, sheet_stale, stale_note, issues, changed, sculpt, history, downstream: {stale_clips, sheet_stale}, library: {library_updated, element_id[, error]}, ui_action}`；
`ui_action = {type: "face_sculpt_changed", name, before, after, revision, sheet_stale, snapshot_id, downstream, library}`。
写路与接口相同（`_face_edit` 改完重算角色总览），元素库写回在事务外。

### 舞台

每个带 `scene_id` 的工具都接受场景号、「第 3 场」（可带「第一集」）、唯一的场名片段，或只在一场里出现的人物名（`stage_locator.resolve_scene_id`）；有歧义时报错并列出候选。镜号认「第 2 镜」「#2」「2」和「X 说话的那镜」（`resolve_shot_id`）。

| 工具 | 效果 | 做什么 | 花费 |
|---|---|---|---|
| `list_stage_scenes` | read | 每一场的场景号、集、场名、人物和镜头 | 无 |
| `describe_stage {scene_id}` | read | 站位 / 朝向 / 姿态、道具、每台机位、每镜用哪台机、评分、快照，以及全部操作说明 | 无 |
| `get_stage_checks {scene_id}` | read | 空间检查结果与每条未通过项的修正操作 | 无 |
| `get_stage_director {scene_id}` | read | 评分、快照（含固定的）、最近几条导演台对话 | 无 |
| `edit_stage {scene_id, operations[], base_revision?, label?}` | write | 按序执行导演台同一套语义操作，作为一步可撤销的改动提交 | 无 |
| `repair_stage {scene_id, codes?}` | write | 一次修正未通过的检查；修不了的放在 `manual` 里 | 无 |
| `adopt_stage_plan {scene_id, candidate_id}` | write | 采用 `auto_plan_stage` 给出的一版 | 无 |
| `revert_stage_step {scene_id, snapshot_id?}` | write | 退回某个快照（省略则最近一步）；撤销本身也留快照 | 无 |
| `pin_stage_snapshot {scene_id, snapshot_id, name?, pinned=true}` | write | 固定 / 取消固定一个快照，最多 12 个 | 无 |
| `direct_stage {scene_id, message, names?, shot_id?}` | write | 像导演台「AI 导演」页签那样把含糊目标交给文本模型 | **每条 1–3 次文本调用，不走确认** |
| `optimize_stage {scene_id, goal?, names?, shot_id?}` | write | 规则先修、模型再优化，评分变低的不留 | **1–3 次文本调用，不走确认** |
| `auto_plan_stage {scene_id, count=3, goal?, from_current?}` | paid | 出 1–3 版完整调度（`from_current` 以当前舞台为底稿），舞台不变 | 每版 1–2 次 |
| `build_stage_model {scene_id, description, position, yaw_deg?, name?}` | paid | 模型库有的直接用，没有的让模型用体块搭 | 0 或 1 次 |
| `optimize_scenes {scene_ids? \| episode, goal?}` | paid | 依次优化多场；必须给 `scene_ids` 或 `episode`（不默认全剧），≤ 12 场；提议里列出要优化的场 | 每场 1–3 次 |

写工具的回执：`{revision, failing_checks, snapshot_id, changed, stale_clips[, ui_action]}`；`ui_action = {type: "stage_changed", scene_id, revision, snapshot_id, summary, failing_checks, changed, stale_clips}` **只在舞台真的变了时出现**（没动就没有刷新动作）。`direct_stage / optimize_stage` 另带 `reply, measured, errors`。

费用上要留意：`direct_stage` 与 `optimize_stage` 的效果是 `write`，与导演台里的「对话调整」「自动优化」一样不问就花 1–3 次文本调用；工具说明和 `agent_prompts.json` 的 `tool_assistant_guides` 都告诉助手「明确的站位 / 机位改动用 `edit_stage`（不花钱）」。真正走确认的是 `optimize_scenes`（多场）、`auto_plan_stage`、`build_stage_model` 和 `run_stage`。

### `stage_director_ops.py`（侧栏助手对舞台的操作层）

建立在 `stage_director_service` 之上（读 `_load`、写 `_commit`、对话行、模型都用它的），所以快照、聊天记录和修订号的规则只有一处：

- `commit_operations`：一组操作当作助手的一步——留快照、记一条对话（`changed` 清单 + 评分对比）、返回 `stale_clips`；内容没变就什么都不写（`changed: False, stale_clips: 0`）。
- `pin_snapshot / list_snapshots / restore_snapshot`：固定的快照放在同一条目下单独的 `pinned_snapshots`（≤ 12），服务层只裁剪自己的 `snapshots`，固定的不会被挤掉；恢复服务层快照前先把现在的舞台留成一条「撤销前」，恢复本身也能撤销。
- `plan_from_current`：与 `plan_scene` 同形，底稿是现在的舞台。
- `optimize_scenes / batch_scope / ensure_idle`：顺序优化多场（`MAX_BATCH = 12`），任务正在跑阶段时开始前就拒绝、中途碰到立即停下，不再为剩下的场花调用。
- `mark_scene_clips_stale(task, scene_id, reason=STALE_CLIP_REASON)`：见下。

已知偏差：`director._commit` 的 `entry_update` 只拿到导演台条目、拿不到任务，而 `stage_director_service` 不在这次改动范围内，所以 `commit_operations` 与固定快照的恢复路径里，标片段过期是紧跟在 `_commit` 之后的第二次 `repo.mutate_task`，不与方案写入同一事务（标记幂等，交错无害，但不原子）。

## 侧栏助手的路由（`drama_service.assistant_message`）

一条消息按这个顺序决定去向：

1. `/记住 …`、`/忘记 …` → 项目记忆，不问模型。
2. `/agent …`、`/助手 …` → 工具助手（`embedded_agent.run_turn`）；`/confirm`、`/确认`、`/cancel`、`/取消` → 结算上一条提议。
3. 其余先过 `assistant_intent`（`workflow_guide.py`，宁可不做也不误启动）：斜杠命令；问句（`？`、怎么、为什么、能不能…）→ `question`；「不用确认 / 别停」→ `run_all`；带否定词 → `read`；验收 / 发布 / 暂停 / 结束 / 恢复 / 合成视频 / 继续 / 一键成片；「重跑第 N 阶段」→ `rerun`；以「修改 / 调整 / 改成 / 把…改 / 将…改」开头 → `edit`；「进度 / 状态 / 流程」→ `status`；其余 `read`。
4. `_routes_to_agent(task, msg, intent)`：
   - 关着（环境变量 `ASSISTANT_AGENT_ROUTING` 为 0 / false / off / no）或项目没配文本模型 → 不路由；
   - `read` → 交给助手（「打开 E1S01 的 3D 导演台」「把陆昭往前挪两步」）；
   - `edit` → 句子里点了名才交给助手；
   - `question` 且不含「流程」→ 点了名才交给助手；
   - 其余意图（continue / run_all / rerun / compose / pause / stop / resume / review / release / help / status）一律走原来的确定性路径，**永远不进助手**。
5. 「点了名」= `_names_a_subject`：对象词表（`assistant_intents.json` 的 `agent_subjects`，四组：工作区词如 `E1S02 / 第3镜 / 分镜 / 导演台 / 站位 / 机位`，动作词如 `打开 / 看看 / 角色 / 道具 / 场景`，捏脸词如 `捏脸 / 鼻 / 眼 / 嘴 / 眉 / 脸型 / 发型 / 肤色 / 表情 / 身材`，舞台词如 `舞台 / 布景 / 姿势 / 走位 / 群演 / 过肩 / 轴线 / 景别 / 撤销 / 评分 / 优化 / 镜头 / 灯光`），或项目自己的名字（`_project_names`：角色名与第一个别名、场景号、场名及「地点 / 时间」里地点那半截；短于 2 字的不算，长名先匹配；坏数据只退回对象词）。
6. 路由成功就以 `"/agent " + msg` 走一轮；助手出错退回原来的提示，且 `edit` 失败时改按 `read` 回答——交给助手的修改失败了也不会悄悄重跑阶段（那是要花钱的）。

| 这句话 | 去向 |
|---|---|
| 把林夏的鼻子改高一点 | `edit` + 捏脸词 → 助手（`sculpt_face`） |
| 把林夏改瘦一点 | `edit` + 角色名 → 助手 |
| 把办公室那场改暗一点 | `edit` + 场名 → 助手（`direct_stage`，1–3 次文本调用） |
| 把第 3 场的机位改到右侧 | `edit` + 对象词 → 助手（`edit_stage`） |
| 修改一下整体节奏，再紧凑些 | `edit`、没点名 → 以这句为指导重跑当前阶段（原路径） |
| E1S08 为什么失败 | `question` + 场景号 → 助手 |
| 完整流程是什么 | `question` 含「流程」→ 固定回答 |
| 继续 / 重跑第 5 阶段 / 一键成片 / 暂停 | 流程指令，不进助手 |
| 撤销上一步 | `read` → 助手（`revert_stage_step` / `revert_face_sculpt`） |

**界面上下文**：`POST /api/drama/{task}/assistant` 的 `payload.context`（`scene_id / shot_id / character / view / stage`）由 `_interface_line` 拼成一行放在项目记忆之前：「[界面] 当前打开：场景 E1S03（第 2 镜）· 角色 林夏 · 视图 desk · 第 4 阶段」，句式在 `assistant_intents.json` 的 `context_line`，只拼有值的部分。

**卡片持久化**：`_agent_turn.record()` 把这轮成功工具结果里的 `ui_action` 收进助手那条 `chat_history` 的 `ui_actions`，待确认的提议收进 `proposal: {tool, message}`（都只在有值时出现）；`hydrate_task_status` 原样带出，`GET status` 的 `chatHistory[]` 就能在刷新后重画卡片。助手的调用计入该项目用量（用途 `agent`）。

## 过期语义

| 触发 | 标哪些 | `stale_reason` | 计数 |
|---|---|---|---|
| 捏脸保存 / 撤销 / 重置，且脸变了 | 这个人出镜的镜头所在的第 5 阶段片段：`assets["4"]` 里 `characters` 含角色名、第一个别名或 `cast_aliases` 中只指向他的称呼的镜，经 `episode_cycle.clip_for` 对到片段（一段分镜片段视频覆盖多个瞬间，标一次算一段） | `「{name}」的脸已改，需重跑第 5 阶段后生效`（`face_sculpt.json` `wording.stale_clip_reason`） | `downstream.clips_marked` → 工具里 `downstream.stale_clips` |
| 舞台改动落地（`edit_stage / repair_stage / adopt_stage_plan / build_stage_model / direct_stage / optimize_stage / revert_stage_step / optimize_scenes`） | 这一场的片段：`scene_id` 相同、`shot_uids` 覆盖本场镜头，或没有场号的旧片段按 `shot_id` 对到本场分镜（与 `clip_for` 同一条规则） | `所属场景的站位或机位已由助手修改，需重跑第 5 阶段后生效`（`stage_director_ops.STALE_CLIP_REASON`） | `stale_clips`，`optimize_scenes` 逐场加总 |
| 定妆照 / 设定集 | 不写标记：`sheet_is_stale` 比对 `sheet_at_save` 与当前地址 | 预览里的 `stale_note`：「脸已经改过，现有设定集和定妆图还是旧脸；重出设定集后新脸才会进图。」 | `sheet_stale` |

不标的情况：只改表情、原样重存、舞台内容没变的提交（`changed: False`，什么都不写）、第 4 阶段的分镜图。
计数的含义是「因这次改动而处于过期的片段数」：已经过期的片段会被重新标上这次的原因并计入，不是「新增过期数」。
过期的效果：第 5 阶段复用旧片段时要求 `not earlier.get("stale")`，所以下次只重做这些；`get_shots` 与镜头工作区显示 `stale / stale_reason`。重跑是付费步骤，助手被要求报出片段数并等用户确认 `run_stage(stage=5)`。

## 前端

已有：

- `features/character/CharacterFaceSculpt.tsx`（含测试）：按层的控件、预设、服务端预览（新描述、近景里的脸、资产卡警告、表情写法）、保存、重置；由 `CharacterDesignerPage` 的「捏脸 · 捏表情」对话框挂载。
- `features/character/FaceSculptInstruct.tsx`（含测试）：一句话捏脸输入框，调 `instruct`（`apply=false`），把翻好的整份 `sculpt` 通过 `onProposed` 交给外层当作未保存的改动；没认出来的半句原样列出。
- `features/workbench/chatCards.ts`：`chatCardsFrom(tool_calls, proposal)` 把一轮回复里的 `ui_action` 做成卡片（`face_sculpt_changed / stage_changed / proposal / tool_calls`），格式不对就当没有。
- `features/workbench/ChatCardView.tsx`（含测试）：卡片渲染，按钮都交回外层（`onOpenCharacter / onOpenStage / onUndoStage / onUndoFace / onSend('/confirm' | '/cancel')`）。

还等前端接线（这些文件不在本轮范围内）：

1. `App.tsx`：助手请求只发 `{message}`，还没带 `context`；回复里的 `tool_calls` 只给 `storyboardActionFrom` 用，没有调用 `chatCardsFrom` / `ChatCardView`；`chatHistory[].ui_actions / proposal` 没有读取（刷新后卡片需要从 `ui_actions` 直接重画，`chatCards.ts` 的 `cardFromUiAction` 目前未导出）。
2. `CharacterFaceSculpt.tsx` 还没挂 `FaceSculptInstruct`，也没有撤销历史 / 退回某一步的界面（接口 `revert` 与 `current().history` 已有）；保存回执里的 `downstream.clips_marked`、`library` 和 `GET sheet-prompt` 还没有显示的位置。
3. 卡片上的「撤销这一步」「到导演台看这场」「打开角色页」要由工作台决定怎么发、打开哪个看板。
