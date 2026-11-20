# 捏脸与右侧对话控制：进度

状态：**已完成** = 行为落地并有测试；**部分** = 后端已有、界面未接；**未开始** = 还没有。

## 速查

- 实现与数据模型：`docs/face-sculpt/IMPLEMENTATION.md`
- 舞台侧的助手工具（与 3D 导演台的关系）：`docs/director-desk/AI-DIRECTOR.md`「侧栏助手与 MCP 的舞台控制」
- 后端：`backend/app/core/face_sculpt.py`、`face_sculpt_sync.py`、`stage_locator.py`、`backend/app/api/face_sculpt_api.py`、`backend/app/service/stage_director_ops.py`、`backend/app/core/agent_tools.py`（捏脸与舞台工具）、`drama_service.py` 助手区域
- 数据：`backend/app/data/prompt/face_sculpt.json`、`assistant_intents.json`（`agent_subjects`、`context_line`）、`agent_prompts.json`（`tool_assistant_guides`）
- 后端测试：`tests/test_face_sculpt.py`、`test_face_sculpt_sync.py`、`test_stage_director_ops.py`、`test_embedded_agent.py`、`test_storyboard_agent_control.py`
- 前端：`frontend/src/features/character/CharacterFaceSculpt*.tsx`、`FaceSculptInstruct*.tsx`、`frontend/src/features/workbench/chatCards*.ts`、`ChatCardView*.tsx`

## 分项进度

| 项 | 状态 | 落点 / 缺口 |
|---|---|---|
| 捏脸核心：控件表、合成、预设、表情习惯进第 5 阶段表情描述 | 已完成 | `face_sculpt.py` + `face_sculpt.json`；`shot_expression_lines` 给视频提示词 |
| 接口：控件表、读、预览、保存、重置 | 已完成 | `face_sculpt_api.py`，挂在 `main.py` |
| 一句话捏脸 | 已完成（后端） | `apply_instruction` + `POST …/instruct`；前端 `FaceSculptInstruct.tsx` 已写、未挂载 |
| 撤销历史 | 部分 | 最近 6 步、`revert`、工具 `revert_face_sculpt`；缺：面板里的历史列表与退回按钮 |
| 下游过期：片段标 `stale`、设定集 `sheet_stale` | 已完成 | `mark_character_clips_stale`、`_downstream`；只有脸变了才标 |
| 元素库写回 | 已完成 | `face_sculpt_sync.py`；接口走异步版，工具走同步版（事务外） |
| 设定集提示词预览 | 已完成 | `GET …/sheet-prompt`、工具 `get_sheet_prompt`；风格词表与 `model_gateway` 那份靠测试对账 |
| 助手 / MCP 捏脸工具 | 已完成 | `get_face_sculpt / get_sheet_prompt / preview_face_sculpt / sculpt_face / revert_face_sculpt / reset_face_sculpt` |
| 助手 / MCP 舞台工具 | 已完成 | `edit_stage / repair_stage / adopt_stage_plan / build_stage_model / direct_stage / optimize_stage / optimize_scenes / revert_stage_step / pin_stage_snapshot / get_stage_director / list_stage_scenes / describe_stage / get_stage_checks`，经 `stage_director_ops` 与 `stage_locator` |
| 舞台改动标片段过期 | 已完成（非原子） | `mark_scene_clips_stale`；提交后第二次 `mutate_task`，见 IMPLEMENTATION「已知偏差」 |
| 自然语言路由：对象词 + 项目名字 | 已完成 | `_routes_to_agent / _names_a_subject / _project_names`；关闭开关 `ASSISTANT_AGENT_ROUTING=0` |
| 界面上下文给助手 | 部分 | 后端 `payload.context` → `_interface_line`；`App.tsx` 还没发 |
| 卡片：`ui_action` → 聊天卡片 | 部分 | 后端 `ui_action` 与 `chat_history[].ui_actions / proposal` 持久化；前端 `chatCards.ts`、`ChatCardView.tsx` 已写、未接进 `App.tsx` |
| 捏脸面板 | 已完成 | `CharacterFaceSculpt.tsx`，`CharacterDesignerPage` 的「捏脸 · 捏表情」对话框 |

## 本轮记录（2026-11-10）

三份并行改动，都只改后端与数据文件，前端只新增未挂载的组件：

- **捏脸下游与元素库。** `face_sculpt.save / revert / reset` 返回 `downstream: {clips_marked, sheet_stale}`；新纯函数 `mark_character_clips_stale(task, name, reason)` 按 `assets["4"]` 镜头的 `characters`（角色名 / 第一个别名 / 只指向他的称呼）经 `episode_cycle.clip_for` 标 `assets["5"]` 片段，原因文案在 `face_sculpt.json` 的 `wording.stale_clip_reason`；只有脸真的变了才标，第 4 阶段的图不动。新 `face_sculpt_sync.py`（异步 / 同步两版，从不让库的毛病打断保存）。`PUT / instruct(apply) / revert / DELETE` 带 `library`；新只读 `GET …/sheet-prompt`。
- **舞台与捏脸工具报出过期片段。** `stage_director_ops` 新增 `STALE_CLIP_REASON`、`mark_scene_clips_stale`；`commit_operations / restore_snapshot / optimize_scenes` 返回 `stale_clips`。`agent_tools` 的舞台写工具只在 diff 非空时带 `ui_action`（`stage_changed` 带 `stale_clips`）；`direct_stage / optimize_stage` 在改了舞台时标片段；捏脸写工具带 `downstream`、`library` 并同步元素库；新读工具 `get_sheet_prompt`。`agent_prompts.json` 的 `tool_assistant_guides` 多一句：报出要重跑第 5 阶段的片段数，重跑是付费步骤需确认。
- **路由与卡片持久化。** `_routes_to_agent` 的 `edit / question` 除对象词外也认项目名字（`_project_names`：角色名、第一个别名、场景号、场名及地点半截）；`_agent_turn.record()` 把 `ui_actions` 与 `proposal` 存进助手那条 `chat_history`，`hydrate_task_status` 原样带出（`drama_service.py` 约 2135 行的两行透传是唯一一处在助手区域之外的改动）。`assistant_intents.json` 多一条 `_doc_project_names` 说明。

验证（本机实际运行，日期同上；测试全部用假模型，不花钱）：

| 命令 | 结果 |
|---|---|
| `cd backend && .venv/bin/python -m unittest tests.test_face_sculpt tests.test_face_sculpt_sync tests.test_stage_director_ops` | Ran 75 tests — OK（42 + 9 + 24） |
| `cd backend && .venv/bin/python -m unittest tests.test_embedded_agent tests.test_storyboard_agent_control` | Ran 51 tests — OK（15 + 36） |
| `cd frontend && npx vitest run src/features/character/FaceSculptInstruct.test.tsx src/features/character/CharacterFaceSculpt.test.tsx` | 2 files, 7 tests passed |
| `cd frontend && npx vitest run src/features/workbench/chatCards.test.ts src/features/workbench/ChatCardView.test.tsx` | 2 files, 13 tests passed |
| 三份改动各自的 `ruff check`（`face_sculpt.py`、`face_sculpt_sync.py`、`face_sculpt_api.py`、`stage_director_ops.py`、`agent_tools.py`、`drama_service.py` 及其测试） | All checks passed（各实现报告所载） |

没有在浏览器里走通：卡片与一句话捏脸还没接进 `App.tsx` / `CharacterFaceSculpt.tsx`，只能靠组件测试与后端测试证明链路；真实文本模型翻控件的质量没有调校过。

## 待办

1. 前端接线（`App.tsx`，另一个会话负责）：助手请求带 `context`；回复与 `chatHistory[].ui_actions / proposal` 走 `chatCardsFrom` / `ChatCardView`（刷新后重画需要一个直接吃 `ui_actions` 的入口）；卡片按钮接到打开角色页 / 打开导演台 / 发 `/agent 撤销…`。
2. `CharacterFaceSculpt.tsx`：挂 `FaceSculptInstruct`（`onProposed` 放进未保存改动）；撤销历史列表 + 退回；显示保存回执的 `downstream.clips_marked`、`library`，以及 `sheet-prompt` 预览和「重出定妆照（付费）」入口。
3. 设定集风格词表在 `face_sculpt_api.py` 与 `model_gateway._generate_character_sheet_unmetered` 各一份，靠 `test_face_sculpt` 对账；应由网关侧暴露一个 `sheet_style_word(dir_style, genre)`（或移进数据文件）让接口调用。
4. `get_sheet_prompt` 从 core 反向引用 `app/api/face_sculpt_api._sheet_prompt`，宜把该函数提到 `app/core`。
5. `commit_operations` / 固定快照恢复的片段标记与方案写入不在同一事务；若要原子，`stage_director_service._commit` 需给 `entry_update` 传任务（或加一个写后回调）。
6. `face_sculpt_sync.sync_actor_description` 在事件循环线程里抛 `RuntimeError`（工具层已接住）；其他直接走真实目录调 `sculpt_face` 的测试模块应像 `test_embedded_agent` 那样在 `setUp` 里打桩，免得对着 `settings.database_url()` 空跑。
7. 整个捏脸特性（`face_sculpt.py`、`face_sculpt_api.py`、`face_sculpt_sync.py`、`stage_locator.py`、`stage_director_ops.py`、`face_sculpt.json`、前端四个组件与本目录）在 git 里仍是未跟踪文件，按规则本轮没有提交。
