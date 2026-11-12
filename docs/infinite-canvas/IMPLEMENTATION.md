# 无限画布：移植自 open-ai-canvas

来源：[ddcat-ai/open-ai-canvas](https://github.com/ddcat-ai/open-ai-canvas)，MIT，审阅提交 `c8d274f`（2026-11-10）。
上游用 DOM 节点 + leafer-ui 画连线；本项目保留自己的 DOM + SVG 画布，只移植交互与性能机制。
每个移植文件开头都有 `Adapted from open-ai-canvas (MIT …)` 一行，许可全文见 `THIRD_PARTY_NOTICES.md`。
没有带走：leafer-ui 渲染层、zustand/localforage 存储、antd 界面、Go 后端、Live2D、图标、tldraw。

## 能力与落点

| 能力 | 用户看到的 | 文件（`frontend/src/features/canvas/`） |
| --- | --- | --- |
| 视口 | 鼠标滚轮缩放、触控板双指平移、捏合缩放、触屏捏合；右下角缩放控件（±、25/50/100/200%、滑杆、适应画布、适应选区），平滑过渡；⌘= ⌘− ⌘0 ⌘1 ⌘2 | `canvasWheel.ts`、`canvasViewportAnimation.ts`、`useTouchPinch.ts`、`CanvasZoomControls.tsx` |
| 背景 | 点阵 / 网格 / 空白，随缩放按 2 倍折叠，每张画布记住 | `canvasBackground.ts` |
| 大画布性能 | 均匀网格空间索引，可见 / 进入 / 保留三圈裁剪与渲染预算；完整 / 预览 / 色块三级细节（带迟滞）；屏外节点逐帧挂载；画布小地图；视频只在需要时挂播放器，悬停静音预览 | `canvasSpatialIndex.ts`、`canvasVisibility.ts`、`canvasLod.ts`、`useProgressiveMount.ts`、`CanvasMinimapCanvas.tsx`、`canvasVideoPreview.ts` |
| 选择 | 向右框选只选完全框住的，向左框选碰到即选；Shift 加、⌘/Ctrl 切换、Alt 减 | `canvasSelectionModes.ts` |
| 整理 | 多选工具栏：六向对齐、水平/垂直等距、横排、竖排、宫格、按连线分层整理、散开重叠 | `canvasLayout.ts`、`CanvasSelectionToolbar.tsx` |
| 分组 | 可嵌套一层；双击标题折叠/展开，折叠后成员隐藏、连线改连到分组；拖进分组自动加入 | `canvasFrames.ts` |
| 右键菜单 | 画布、节点、多选、连线四种 | `CanvasContextMenu.tsx`、`canvasMenus.ts` |
| 连线建节点 | 从输出口拖到空白处松手，选一种能接收的节点，自动建好并连上 | `canvasConnectedPlacement.ts` |
| 剪贴板 | 复制写系统剪贴板；粘贴识别画布片段（并接回上游连线）、图片/视频/音频文件、纯文本 | `canvasClipboard.ts` |
| 搜索 | ⌘F 按名称、提示词、文本搜索，跳过去并选中 | `canvasSearch.ts`、`CanvasSearchDialog.tsx` |
| 导出/导入 | 画布导出为 JSON（媒体保留链接），导入时重新编号并放在现有内容右侧，可撤销 | `canvasExport.ts` |
| 结果对比 | 节点生成记录里点「对比」挑两版，图片可并排或滑块对比（滚轮同步放大），视频同步播放，文字逐行标出不同，「用这个」直接换上 | `CanvasCompareDialog.tsx`、`CanvasPanels.tsx` 的 HistoryStrip |
| 只读分享 | 工具栏「分享」生成只读链接（1/7/30 天或永久），可复制、换链接、停止；打开链接不用登录，只能平移缩放看，不能改 | `CanvasShareDialog.tsx`、`canvasShareApi.ts`、`frontend/src/features/share/SharedCanvasPage.tsx` |
| 多窗口同步 | 同一账号在几个窗口开同一张画布：互相看到光标（带标签）、对方正在拖的节点轮廓和选区；工具栏显示「同时打开：N 个窗口」；一边保存，另一边约 1 秒内载入新版本并闪一下（有未保存改动时走原来的冲突提示） | `useCanvasPresence.ts`、`CanvasPresenceLayer.tsx`；后端 `app/service/canvas_presence.py`、`app/api/canvas_presence_api.py` |
| 助手改画布 | 助手改完后画布重新载入，自动移到改动处并闪一下 | `canvasFocus.ts` |

## 后端

- 坐标上限：节点 ±1e9，宽高 ≤1e6；书签 ±1e10、缩放 0.01–16；一张画布最多 5000 个节点、12000 条连线（`app/schema/studio.py`）。
- 分组嵌套一层，`collapsed` / `expandedSize` 随画布保存。
- 助手的 `edit_canvas` 新增 `set_group`、`align`、`distribute`、`arrange` 操作（`app/core/canvas_layout.py`），结果带 `ui_action: canvas_changed`；`get_canvas` 返回 `bounds` 与每个节点所在分组。

## 只读分享的后端

- 主人接口：`GET/POST/DELETE /api/studio/projects/{pid}/canvases/{cid}/share`；再次 POST 即换链接，旧链接立刻失效。
- 公开接口：`GET /api/public/canvas-shares/{token}`，不用登录；每个 IP 每分钟 60 次；未知、过期、停止、换掉的链接一律返回同样的 404；响应带 `Cache-Control: no-store` 与 `X-Robots-Tag: noindex`。
- 公开内容只保留节点位置、标题、文字、提示词和公开媒体（`/media` 下或 http(s)，元素库私图与 data: 一律去掉），不含绑定、提交记录和任何像密钥的字段。
- 令牌只按 sha256 查找；为了让主人随时能再复制链接，原文也存在主人那一行，数据库文件泄露时请换链接或停止分享（`backend/app/repository/studio_repo.py` 表注释）。

## 多窗口同步的后端

- 用 SSE（浏览器自带的服务器推送）加普通 POST，不新增依赖：`GET …/canvases/{cid}/presence/stream` 收事件，`POST …/presence` 发光标、拖动、选区、离开。
- 只在同一账号的窗口之间；每个房间最多 20 个窗口，全局 500 个房间；每个窗口每秒最多 30 条消息，单条 32KB。
- 每条推送连接 25 秒主动结束，浏览器 1 秒后自动接上，期间的保存通知先攒着、接上后补发，其他窗口看不到「离开又进来」；5 秒内没接回来才算离开。这样开发时自动重启、上线时正常停机都不会卡在等待连接关闭；`main.py` 另给停机设了 5 秒上限。
- 所有写新版本的路径（保存、恢复版本、复制节点、提交、助手编辑、工作流铺开）都会通知其他窗口。
- 只在单个后端进程内有效；多个进程需要换成 Redis 一类的消息通道（接口不变）。

## 验证

- 前端：`npx vitest run`（178 个文件 1668 个测试）、`tsc` 0 错误、`eslint` 无问题。
- 后端：全量 4098 个测试通过；新增 `tests/test_canvas_infinite.py`。
- 浏览器：在测试库里加节点、全选、横向排列、⌘1 适应、右键菜单、多选工具栏位置。

## 已知不足

已在 2026-11-10 第二轮补上：拖动节点时多选工具栏先隐藏、落定后在新位置出现；「铺成 N 个节点」铺之前检查 5000 个节点上限；大纲和工作流面板的「定位」改为平滑移过去。

第三轮补上：只读分享链接、生成结果对比。第四轮补上：同账号多窗口同步（用 SSE，未引入 WebSocket 依赖）。

仍未做：跨账号协作（上游也没有）。
