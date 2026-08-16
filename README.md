# AI 短剧 8-Agent 工业化成片系统

> **项目定位**：本项目是一个集成了 **React + TypeScript 前端控制台** 与 **Python FastAPI 后端引擎** 的 AI 短剧/漫剧工业化协同成片系统。
> 系统底层由 **8-Agent 多智能体流水线** 驱动，支持从「选题立项、剧本编写、分镜设计、角色锁定、配音合成、画面渲染」到「视频拼接、成片质检」的全流程自动化生成，并提供步骤级断点续传（防孤儿任务）能力。

---

## 目录
1. [项目工程与启动指南](#一项目工程与启动指南)
2. [AI 短剧制作知识库与工作流导航](#二ai-短剧制作知识库与工作流导航)
3. [全局制作基准参数 (跨文档唯一权威源)](#三全局制作基准参数-跨文档唯一权威源)
4. [冲突裁决与维护约定](#四冲突裁决与维护约定)
5. [系统设计思路与原理架构](#五系统设计思路与原理架构)
6. [核心功能模块矩阵](#六核心功能模块矩阵)
7. [深度依赖与生产环境部署](#七深度依赖与生产环境部署)
8. [标准使用说明与操作流](#八标准使用说明与操作流)
9. [系统页面与交互展示](#九系统页面与交互展示)
10. [高级技术底座与架构深度解析](#十高级技术底座与架构深度解析)
11. [SKILL 规约与 Prompt 工程化引擎 (核心)](#十一skill-规约与-prompt-工程化引擎-核心)
    - [1. Prompt as Code (PaaC) 架构理念](#1-prompt-as-code-paac-架构理念)
    - [2. SKILL 动态解析与挂载机制](#2-skill-动态解析与挂载机制)
    - [3. 智能体防御与边界约束策略](#3-智能体防御与边界约束策略)
12. [系统扩展性能力与生态集成](#十二系统扩展性能力与生态集成)
    - [1. 多轨音频混音与闪避引擎 (Audio Ducking)](#1-多轨音频混音与闪避引擎-audio-ducking)
    - [2. 插件式模型适配器 (Plugin-based Adapter)](#2-插件式模型适配器-plugin-based-adapter)
    - [3. 异步高并发与 GPU 资源防超载](#3-异步高并发与-gpu-资源防超载)

---

## 一、项目工程与启动指南

### 1. 系统架构与核心特性

*   **8-Agent 工业化协同**：由 `Executive Director` (总导演)、`Writer` (编剧)、`Character Designer` (角色设计师) 等 8 个智能体分工合作，将非结构化的创意逐步细化并实现音视频物料渲染。
*   **断点续跑与异常重置机制**：
    *   在任务生成时，支持对任意生成步骤（Stage）进行暂停与恢复。
    *   **防孤儿任务机制**：当系统异常重启或崩溃时，启动时会自动将状态残留为 `running` 的任务重置为 `interrupted` 状态，并填充失败信息，避免前端状态卡死，用户可随时点击恢复（`/resume`）从断点续跑。
*   **阿里云短信登录验证**：集成阿里云 SMS 模块，支持手机号与短信验证码的快速注册和登录。
*   **视频一键合成与插帧**：调用火山引擎 `Seedance` 2.0 图生视频及 `Seedream` 4.0 文生图大模型，保证生成画面在动作、构图及人物一致性上达到电影级基准。

### 2. 项目目录结构

```text
short-drama/
├── start.sh                      # 【重要】一键启动脚本 (优雅管理前后端进程)
├── README.md                     # 本说明文档 (全局导航与参数基准)
├── SKILL.md                      # 八 Agent 知识与协作规范（不执行）
├── backend/                      # Python FastAPI 后端
│   ├── app/
│   │   ├── api/                  # 请求解析与响应封装 (drama_api.py, auth_api.py)
│   │   ├── core/                 # 核心模块 (model_gateway.py 驱动模型, media_compositor.py 合成器)
│   │   ├── repository/           # 数据库访问与状态管理 (task_repo.py 等)
│   │   ├── schema/               # Pydantic 请求校验模式
│   │   └── service/              # 业务逻辑层 (drama_service.py 状态机, auth_service.py 鉴权)
│   ├── .env                      # 环境变量配置模板
│   ├── requirements.txt          # 后端 Python 依赖
│   ├── main.py                   # 后端主入口文件
│   └── tasks_db.json             # 任务数据库 (持久化状态)
└── frontend/                     # React + TypeScript 前端
    ├── src/
    │   ├── App.tsx               # 核心交互页面与控制面板
    │   ├── main.tsx              # 渲染入口
    │   └── index.css             # 全局视觉样式
    ├── package.json              # 前端 npm 依赖
    └── vite.config.ts            # Vite 构建配置
```

### 3. 配置说明 (.env)

在启动后端服务前，请在 `backend/` 目录下创建并配置 `.env` 文件。核心参数说明如下：

| 配置项 | 示例值 / 说明 | 作用域 |
| :--- | :--- | :--- |
| **SEEDANCE_API_KEY** | `ark-c620c6ed-xxxx-xxxx-xxxx-xxxx` | 火山引擎 API 密钥（生成底图与视频） |
| **SEEDANCE_BASE_URL** | `https://ark.cn-beijing.volces.com/api/v3` | 火山引擎 API 接入端点 |
| **SEEDANCE_MODEL_NAME** | `doubao-seedance-2-0-260128` | 图生视频大模型（主渲染引擎） |
| **SEEDANCE_IMAGE_MODEL_NAME** | `doubao-seedream-4-0-250828` | 文生图大模型（底片渲染引擎） |
| **SEEDANCE_IMAGE_SIZE** | `1440x2560` | 文生图尺寸（9:16 竖屏高分辨率） |
| **DEEPSEEK_API_KEY** | 通过环境变量注入 | DeepSeek API 密钥（用于驱动 Agent 链逻辑） |
| **DEEPSEEK_BASE_URL** | `https://api.deepseek.com/v1` | DeepSeek API 接入端点 |
| **DEEPSEEK_MODEL_NAME** | `deepseek-v4-pro` | 语言大模型名称 |
| **ALIBABA_CLOUD_ACCESS_KEY_ID** | `LTAIxxxxxxxxxxxxxx` | 阿里云短信 AccessKey ID |
| **ALIBABA_CLOUD_ACCESS_KEY_SECRET**| `xxxxxxxxxxxxxxxxxxxxxxxxxx` | 阿里云短信 AccessKey Secret |
| **ALIBABA_CLOUD_SMS_SIGN_NAME** | `伊胜雪网络科技` | 验证短信签名 |
| **ALIBABA_CLOUD_SMS_TEMPLATE_CODE**| `SMS_501585017` | 验证短信模板 ID |
| **MINIMAX_API_KEY** | 仅服务端环境变量 | minimax 视频、同步语音、Music 3.0 与 Music Cover 密钥 |
| **MINIMAX_BASE_URL** | `https://api.minimaxi.com` | MiniMax 音频 API 根地址；模型配置中心保存的音频配置优先 |
| **MINIMAX_H3_ENDPOINT** | `https://api.minimaxi.com/v2/video_generation` | MiniMax H3 创建任务端点 |
| **MINIMAX_H3_STATUS_URL_TEMPLATE** | 同 API 主机的 `/v2/query/video_generation/{task_id}` | H3 异步任务查询端点，可覆盖 |
| **MINIMAX_FILES_URL** | 同 API 主机的 `/v1/files/retrieve` | 根据 `file_id` 解析最终下载地址，可覆盖 |
| **ELEVENLABS_API_KEY** | 仅服务端环境变量 | 配音、多人对话、音效、音乐、语音识别与配音翻译 |
| **ELEVENLABS_BASE_URL** | `https://api.elevenlabs.io` 或完整 `/v1/sound-generation` 地址 | 服务端会规范化为 API 根，避免重复拼接路径 |
| **ELEVENLABS_VOICE_MAP** | `{"角色名":"voice_id"}` | 固定每个角色的声音身份 |
| **SD25_PE_SKILL_PATH** | `/absolute/path/to/sd25-pe` | 指向完整 `sd25-pe/SKILL.md` 的目录；默认优先 `~/.agents/skills/sd25-pe`，兼容 `~/Desktop/sd25-pe` |
| **AUTH_SIGNING_SECRET** | 至少 32 位随机值 | 会话签名；生产环境必填，禁止复用供应商密钥 |
| **COOKIE_SECURE** | 生产 HTTPS 环境设为 `1` | 只允许浏览器通过 HTTPS 发送登录 Cookie |
| **DATABASE_URL** | `postgresql+asyncpg://postgres:postgres@localhost:5432/short-drama` | 用户、全局能力、元素、会员、订单和账本的 PostgreSQL 数据源 |
| **MODEL_CONFIG_MASTER_KEY** | Fernet 密钥，由部署密钥管理器注入 | 加密管理员在模型配置中心保存的供应商 API Key；生产环境必填 |
| **BOOTSTRAP_ADMIN** | 本地开发 `1`，生产默认 `0` | 仅在配置登录名不存在时初始化管理员 |
| **BOOTSTRAP_ADMIN_LOGIN** | `admin@short-drama` | 本地默认管理员登录名 |
| **BOOTSTRAP_ADMIN_PASSWORD** | 本地开发默认 `admin@123` | 首次登录必须修改；生产环境禁止使用该默认值 |
| **PAYMENT_WEBHOOK_SECRET** | 至少 32 位随机值 | 微信/支付宝回调信封的 HMAC 验签密钥 |

> [!WARNING]
> 敏感密钥只允许来自服务端环境变量或模型配置中心。模型配置中心的 Key 使用服务端主密钥加密后写入 PostgreSQL，浏览器、列表接口、日志和 `localStorage` 都不会收到或保存明文。禁止将带有明文 Key 的代码提交到公共仓库。

任何曾粘贴到聊天、工单或日志中的 Key 都应视为已经暴露：先在供应商后台撤销/轮换，再把新 Key 注入服务端密钥存储。自动测试不会调用付费生成接口。

### 4. 本地快速启动

#### 方式 A：使用一键启动脚本 (推荐)

在项目根目录下，我们提供了一个优雅的 `start.sh` 脚本，它会自动检测当前依赖、清除历史冲突的 Vite/FastAPI 后台进程、并在后台同步启动前后端服务，输出日志。

1. **为脚本赋予执行权限（仅首次）**：
   ```bash
   chmod +x start.sh
   ```
2. **运行启动脚本**：
   ```bash
   ./start.sh
   ```
3. **优雅关闭**：当需要停止开发调试时，在运行终端中按下 **[Enter] 键** 或 **[Ctrl+C]**，脚本将捕获退出信号，自动、干净地杀死全部关联的前后端后台子进程。

#### 方式 B：手动分步启动

##### PostgreSQL 初始化（首次）

PostgreSQL 16 运行后创建数据库，并执行幂等的表结构、能力、会员计划和管理员引导：

```bash
/opt/homebrew/opt/postgresql@16/bin/createdb -h localhost -U postgres short-drama
DATABASE_URL='postgresql+asyncpg://postgres:postgres@localhost:5432/short-drama' \
  backend/.venv/bin/python scripts/bootstrap_admin.py
```

本地开发默认管理员为 `admin@short-drama`，默认密码为 `admin@123`，配置位于服务端 `backend/.env`。密码在 PostgreSQL 中只保存 scrypt 哈希，首次登录自动进入用户中心并要求修改。生产环境检测到这个公开默认密码会拒绝启动，必须关闭自动引导或通过部署密钥管理器注入独立强密码。

##### 后端 (FastAPI) 启动：
1. 进入 backend 目录，创建虚拟环境：
   ```bash
   cd backend
   python3 -m venv .venv
   source .venv/bin/activate
   ```
2. 安装依赖并启动服务：
   ```bash
   pip install -r requirements.txt
   python main.py
   ```

##### 前端 (React) 启动：
1. 进入 frontend 目录，安装 npm 依赖：
   ```bash
   cd frontend
   npm install
   ```
2. 启动 Vite 开发服务：
   ```bash
   npm run dev
   ```

### 5. 常用服务地址与调试

*   **前端控制台 Web 页面**：[http://localhost:5173/](http://localhost:5173/)
*   **后端 API 交互式文档 (Swagger UI)**：[http://localhost:8000/docs](http://localhost:8000/docs)
*   **后端 API 备用文档 (ReDoc)**：[http://localhost:8000/redoc](http://localhost:8000/redoc)
*   **媒体文件静态资源根路径**：[http://localhost:8000/media/](http://localhost:8000/media/)

### 6. 工业化生产 API

所有 `/api/production/*` 路由都要求登录，密钥不会下发给浏览器。

| 路由 | 能力 |
| :--- | :--- |
| `GET /api/production/capabilities` | 查询 13 个来源、已发现 Skill、创作预设和供应商配置状态 |
| `GET /api/production/agent-council/capabilities` | 查询八 Agent、18 份本地规范、能力所有者、可执行策略、校验器与交付物的完整追踪矩阵 |
| `POST /api/production/agent-council/compile` | 按题材、平台、形式和动作强度编译八 Agent 提示契约、交接规则、画面/节奏基准与负面词模块 |
| `POST /api/production/agent-council/release-gate` | 对八阶段交付、五视图、九宫格、契约指纹、视频路由、音频、字幕、授权和 S/A/B/C 问题执行失败关闭验收 |
| `GET /api/production/presets` | 查询 17 个可调用创作/提示词编译模式 |
| `POST /api/production/presets/{id}/compile` | 编译带五视图、九宫格、素材职责、首尾帧、表演和连续性硬约束的方案 |
| `POST /api/production/sd25/compile` | 执行本地 sd25-pe 的生成/编辑/延长、音频单改、编辑后延长有序步骤、素材职责、关键帧、九宫格与白模 Prompt 编译 |
| `POST /api/production/script-prompts/compile` | 把剧本文本完整编译为角色五视图、场景圣经、逐场严格九宫格、同契约分镜/运镜 Prompt、SD25 Prompt、一致性报告和多格式导出 |
| `POST /api/production/script-prompts/compile-file` | 安全接收 TXT/Markdown/DOCX/PDF/FDX，并执行完整剧本到视频提示词流水线 |
| `POST /api/production/storyboard-director/compile` | 编译单镜头基础信息、视觉规范、连续性锁定、色调/动势/运镜/转场、连续时间拍点、逐拍单图、相邻关键帧视频、九宫格分页与自检结果 |
| `GET /api/production/shotcraft/catalog` | 查询锁定的 Video Shotcraft 152 卡 / 209 样式目录与音效统计 |
| `POST /api/production/shotcraft/compile` | 将 Shotcraft 卡片和样式编译为统一镜头计划，不执行上游脚本 |
| `POST /api/production/storyboards/compile` | 校验并编译严格 3×3 九宫格分镜 |
| `POST /api/production/video/minimax-h3` | H3 文本、首帧、尾帧、首尾帧、多图和多模态参考视频 |
| `GET/POST /api/production/audio/*` | ElevenLabs 14/14 能力：TTS、STT、Music、Speech Engine、Voices、Dialogue、Voice Changer、Voice Design、SFX、Audio Isolation、Dubbing、Forced Alignment、Pronunciation Dictionaries 和 Audio Native |
| `POST /api/production/audio/minimax/tts` | MiniMax 同步语音合成；支持 8 个 `speech-*` 接口模型、情绪、语速、音量、音调、发音字典与输出规格 |
| `POST /api/production/audio/minimax/music` | 使用 `music-3.0` 生成歌词歌曲、自动歌词或纯音乐 |
| `POST /api/production/audio/minimax/music-cover` | 使用 `music-cover` 和公网参考音频 URL 一步翻唱，自动 ASR 提取歌词 |
| `POST /api/production/performance/plan` | 生成动机、触发、视线、呼吸、微表情、身体、声音与权力转移的表演节拍 |
| `POST /api/production/audio/mix/plan` | 生成带对白闪避、响度和峰值门禁的可编辑混音计划 |
| `POST /api/production/preproduction/*` | 长篇可复现抽样、断点分集与授权声音参考计划 |
| `POST /api/production/readiness/evaluate` | 在付费提交前校验四类资产、九宫格审批、供应商模式/数量/时长 |
| `POST /api/production/failures/normalize` | 生成脱敏、可定向重试的结构化失败证据 |
| `POST /api/production/analytics/summarize` | 汇总接受率、重试率、延迟、费用与失败类别 |
| `POST /api/production/quality/video/decision` | 对真实多模态/人工评分执行失败关闭的成片质量门禁 |
| `POST /api/drama/{task_id}/quality/video` | 将成片多模态/人工证据写入任务；通过后进入 `awaiting_council_review`，不能直接完成 |
| `POST /api/drama/{task_id}/quality/council` | 在视频门禁通过后持久化八 Agent 全量证据；只有委员会门禁也通过才将任务标为 `completed` |

角色阶段会生成一张有序五视图设定板并物理拆成五个视图；分镜阶段按真实叙事事件生成 N 张独立镜头图，再合成为固定 3×3 九宫格展示页：不足九拍的格位留白，超过九拍自动分页，禁止复制或补造拍点。长视频合成会根据场景、轴线、动作、道具、灯光和声音状态选择动作匹配、硬切、短叠化、声音桥或转黑，未通过连续性门禁的镜头禁止合成。

工作室平台 API 使用 `/api/studio/*`：包含 SQLite 项目、TXT/Markdown/DOCX/PDF/FDX 来源摄取、证据化故事图、版本谱系、下游过期、追加式人工审核、主线/Freezone 双轨画布、Director World 空间调度、原子任务租约与取消、分币种成本账本、带 SHA-256 的项目归档往返、资产就绪、SRT/ASS/Jianying-compatible 导出以及作用域外部 Agent Key。外部自动化使用 `/api/agent/*`，凭据只允许访问绑定项目和显式授权的 scope。

产品平台 API 使用 PostgreSQL：`/api/platform/*` 提供 13 个来源、81 项能力的全局开关、审计提交/许可证处理和 `/command` 白名单调用；`/api/elements/*` 提供演员、道具、场景、特效独立元素库及安全图片上传/重新生成请求；`/api/users/*` 与 `/api/admin/users/*` 提供个人资料、改密和角色/状态管理；`/api/billing/*` 提供会员计划、积分账本、订单、沙箱支付和签名幂等回调。微信/支付宝真实结算在商户证书未配置时失败关闭，不会把浏览器跳转当作付款成功。

全局模型配置中心使用 `/api/model-configurations/*`。管理员可在文本、图像、视频、音频四类中选择供应商，填写官方 Base URL 和 API Key；服务端优先通过供应商模型枚举接口实时获取模型，自动将文本模型区分为纯文本/多模态。ElevenLabs 固定使用官方 `GET /v1/models` 与 `xi-api-key` 鉴权，将动态响应与 13 个当前官方模型合并，并归为 ASR、TTS、语音转换、声音设计、BGM/音效和音乐。界面另以 14/14 可点击能力分类展示截图要求的所有 ElevenLabs 功能；每个模型分类均可复选，选择会跨分类保留并可一次批量保存，已保存模型没有业务数量上限。无 `model_id` 的隔离、Dubbing、强制对齐等服务会显示为“独立服务”，不会伪装成模型。Key 因 401/403 或网络问题不能读取目录时，“加载模型”仍提供官方目录并明确标注未验证；401 无效/撤销 Key 不能保存，403 仅缺少模型目录 scope 的 Key 可以保存目录配置，但运行能力仍取决于相应 scope 与 IP 白名单，“连接测试”始终严格验证。MiniMax 的通用模型目录只用于无费用鉴权：视频分类返回 `MiniMax-H3` 与锁定的 Hailuo 视频模型；音频分类返回 8 个同步语音模型（含接口仍接受的 `speech-01` 兼容模型）、`music-3.0` 和 `music-cover`，分别标注为 TTS、音乐和音乐翻唱，禁止把 M 系列文本模型误标为音视频。H3 生成采用多模态 `content[]` 请求，并以 `/v2/query/video_generation/{task_id}` 查询成片；MiniMax 音频生成采用 Bearer 鉴权，TTS 使用 `/v1/t2a_v2`，音乐生成和一步翻唱使用 `/v1/music_generation`。保存后启用项立即进入全局运行时路由；文本、图像、视频任务未显式指定模型时会自动采用该分类首个全局启用模型。系统支持逐模型禁用、任务当前模型选择和叉号删除；删除供应商下最后一个模型时会同步删除空配置和对应加密凭据。连接测试不提交付费生成任务。

动态配置 API：

| 路由 | 作用 |
| :--- | :--- |
| `GET /api/model-configurations/providers` | 获取四分类与供应商协议元数据（不含模型 ID） |
| `GET /api/model-configurations` | 获取已保存配置、启用项和分类统计（不返回 Key） |
| `POST /api/model-configurations/discover` | 使用当前 Base URL/Key 动态发现并归类模型 |
| `POST /api/model-configurations/test` | 重新发现并验证选择，不执行付费推理 |
| `POST /api/model-configurations` | 加密保存已验证的模型配置并全局生效 |
| `PATCH /api/model-configurations/{id}` | 启用或禁用整组供应商配置 |
| `PATCH /api/model-configurations/{id}/models/{entry_id}` | 启用或禁用单个动态模型 |
| `DELETE /api/model-configurations/{id}/models/{entry_id}` | 删除单个已保存模型；最后一项会清理空配置 |

已保存模型面板使用独立滚动列表呈现全部条目，不以 5 项截断；面板会分别显示保存总数和当前启用数。

首页“模型”徽标以服务端 `global_status` 为准：任意分类存在至少一个全局启用模型时显示“已配置”，全部停用或删除后显示“未配置”。保存、启用、停用和删除都会立即刷新；前端同时自动采用各分类的全局默认启用模型，不再依赖当前任务是否手动选择视频模型来判断配置状态。

实现依据的当前官方接口：[MiniMax API 概览](https://platform.minimaxi.com/docs/api-reference/api-overview)、[MiniMax 同步语音合成](https://platform.minimaxi.com/docs/api-reference/speech-t2a-http)、[MiniMax 音乐生成与翻唱指南](https://platform.minimaxi.com/docs/guides/music-generation)、[ElevenLabs 模型](https://elevenlabs.io/docs/overview/models)、[ElevenLabs 鉴权](https://elevenlabs.io/docs/api-reference/authentication)、[Voices](https://elevenlabs.io/docs/api-reference/voices/search)、[Speech Engine](https://elevenlabs.io/docs/api-reference/speech-engine/list)、[Voice Changer](https://elevenlabs.io/docs/api-reference/speech-to-speech/convert)、[Voice Design](https://elevenlabs.io/docs/api-reference/text-to-voice/design)、[Audio Isolation](https://elevenlabs.io/docs/api-reference/audio-isolation/convert)、[Forced Alignment](https://elevenlabs.io/docs/api-reference/forced-alignment/create)、[Pronunciation Dictionaries](https://elevenlabs.io/docs/api-reference/pronunciation-dictionaries/list)、[Audio Native](https://elevenlabs.io/docs/api-reference/audio-native/create)、[FastAPI 多文件路由](https://fastapi.tiangolo.com/tutorial/bigger-applications/)、[Pydantic 校验器](https://pydantic.dev/docs/validation/latest/concepts/validators/) 与 [Python sqlite3](https://docs.python.org/3/library/sqlite3.html)。

---

## 二、AI 短剧制作知识库与工作流导航

本项目不仅包含工程代码，还是 AI 短剧「从选题到发布」的完整全流程知识库。18 份规范由八 Agent 能力注册表逐项映射到代码、交付物和验收器；Markdown 只作为知识与行为规范读取，不会作为代码执行。

### 1. 知识库文档地图

| # | 文档名称 | 负责内容与唯一权威源 | 适用创作节点 |
| :--- | :--- | :--- | :--- |
| 1 | [AI 生成短剧一致性检查清单.md](AI%20生成短剧一致性检查清单.md) | 全链路一致性、S/A/B/C 分级、自动/人工质检和发布评分 | 八阶段质检与终审 |
| 2 | [AI影视剧台词语速情绪提示词总结.md](AI影视剧台词语速情绪提示词总结.md) | 语速、情绪、停顿、重音、呼吸、角色声卡和口型时长 | 编剧、音频总监 |
| 3 | [AI影视剧负面提示词.md](AI影视剧负面提示词.md) | 人脸、手部、多人、服化、场景、材质、时序与题材负面词模块 | 视觉总监 |
| 4 | [AI漫剧短剧剧本黄金叙事结构.md](AI漫剧短剧剧本黄金叙事结构.md) | 前3秒钩子、冲突/反转密度、多集弧与尾钩 | 总导演、编剧 |
| 5 | [AI短剧与漫剧导演级拍摄分镜完全指南.md](AI短剧与漫剧导演级拍摄分镜完全指南.md) | 景别、机位、构图、站位、光影、36/88 运镜系统 | 分镜师、视觉总监 |
| 6 | [AI短剧五视图解决人物一致性提示词模板.md](AI短剧五视图解决人物一致性提示词模板.md) | 严格五视图、角色状态、九宫格与分镜/运镜同源契约 | 角色设计师、分镜师、视觉总监 |
| 7 | [AI短剧注意事项与关键元素.md](AI短剧注意事项与关键元素.md) | 剧本、视觉、声音、后期、平台、商业、团队和版权总览 | 全流程 |
| 8 | [AI短剧电影级武打镜头设计指南.md](AI短剧电影级武打镜头设计指南.md) | 力学拆解、出招/受击、冲击帧、防越轴、Foley 卡点 | 分镜师、视觉/音频总监 |
| 9 | [AI短剧表演细节与提示词指南.md](AI短剧表演细节与提示词指南.md) | 身体、微表情、口型、关键帧、手部、声音与竖屏适配 | 角色、分镜、视觉、音频 |
| 10 | [AI短剧连续性设计指南.md](AI短剧连续性设计指南.md) | 视觉/角色/空间/时间/运动连续性、首尾帧和后期修复 | 分镜、视觉、合成 |
| 11 | [SKILL.md](SKILL.md) | 八 Agent 角色职责与工业化协作规范（知识规范，不执行） | 八 Agent 总览 |
| 12 | [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) | 上游能力来源、许可证观察和 clean-room 处理边界 | 总导演、合成、宣发 |
| 13 | [场景设计提示词.md](场景设计提示词.md) | 功能化场景圣经、空间布局、光色、道具叙事和负面词 | 分镜师、视觉总监 |
| 14 | [影视剧高光时刻识别方案.md](影视剧高光时刻识别方案.md) | 情节/情绪/叙事/视听/观众行为高光标签与强度 | 总导演、宣发 |
| 15 | [画质风格类型总结.md](画质风格类型总结.md) | 载体画风、调色、光影、画幅、色彩空间与技术基准 | 总导演、视觉、合成 |
| 16 | [短剧情绪与面部表情提示词库.md](短剧情绪与面部表情提示词库.md) | 可观察微表情、情绪递进、镜头搭配和负面约束 | 角色、分镜、视觉 |
| 17 | [短剧情节与镜头连贯性提示词.md](短剧情节与镜头连贯性提示词.md) | 六锚点、连续性圣经、逐镜单动作和承接模板 | 分镜师、视觉总监 |
| 18 | [短剧题材类型总结.md](短剧题材类型总结.md) | 完整题材库、商业价值、出海与互动形式 | 总导演、编剧、宣发 |

### 2. 知识层 vs 工程层 (SKILL.md)

本仓库将创作经验与工程代码以分层模式紧密耦合：

*   **知识层（18份规范）**：提供给创作者查阅的标准、案例与验收依据；内容不会被执行。
*   **工程层（Agent Council）**：`agent_council.py` 将知识能力映射为类型化角色、交付、校验器、交接和发布门禁，并由 `drama_service.py` 的真实八阶段流程复用。

### 3. 后端 8-Agent 与创作流程映射

后端多智能体执行链路与 12 步主流程及上层知识层标准紧密咬合：

```
                    ┌────────────────────────┐
                    │      总导演 Agent      │  ──▶ 对应：步骤 ① (选题/立项)
                    └────────────────────────┘
                                 │
                    ┌────────────────────────┐
                    │       编剧 Agent       │  ──▶ 对应：步骤 ③ (剧本编写)
                    └────────────────────────┘
                                 │
                    ┌────────────────────────┐
                    │     角色设计师 Agent    │  ──▶ 对应：步骤 ④ (角色锁定)
                    └────────────────────────┘
                                 │
                    ┌────────────────────────┐
                    │       分镜师 Agent      │  ──▶ 对应：步骤 ⑥ (镜头运镜)
                    └────────────────────────┘
                                 │
                    ┌────────────────────────┐
                    │      视觉总监 Agent    │  ──▶ 对应：步骤 ⑦-⑨ (视觉生成与连续性)
                    └────────────────────────┘
                                 │
                    ┌────────────────────────┐
                    │      音频总监 Agent    │  ──▶ 对应：步骤 ⑤/⑩ (音频设计与TTS)
                    └────────────────────────┘
                                 │
                    ┌────────────────────────┐
                    │      合成发布 Agent    │  ──▶ 对应：步骤 ⑩-⑫ (视频后期与合成)
                    └────────────────────────┘
                                 │
                    ┌────────────────────────┐
                    │    一致性质检 Hooks    │  ──▶ 对应：步骤 ⑪ (一致性检查清单质检)
                    └────────────────────────┘
```

### 4. 全局制作工作流 (12步流程)

```text
【选题策划】          【视觉基调】         【前期锁定】                【生成渲染】                  【合成与质检】
    │                  │                   │                          │                            │
 [1]题材 ───▶ [2]画质风格 ───▶ ┌── [4]角色五视图锁定 ─┐ ───▶ [6]表演细节/动作/口型/手部控制 ───▶ [5]连续性(首尾帧过渡)
                               ├── [6]声音音色设计 ──┤       [7]运镜镜头语言设计              │   后期插帧/调色/导出
                               └── [3]剧本分镜脚本 ──┘                                        ▼
                                                                                   [8]一致性检查清单全程过滤
```

每一阶段包含如下 12 个核心操作步骤：
1.  **选题立项**：匹配题材、受众、商业价值、黄金结构与高光模型。
2.  **视觉基调设定**：确定载体画风、色板、光线、画幅、帧率和技术参数。
3.  **剧本与脚本**：建立系列圣经、因果/信息/伏笔台账、分集剧本和台词表。
4.  **角色一致性锁定**：渲染严格有序五视图，建立角色状态、服化、标志物和声音身份卡。
5.  **声音设计**：逐句编译语速、情绪、停顿、重音、呼吸，生成配音、环境、SFX、Foley 与 BGM 计划。
6.  **设计镜头语言**：建立场景圣经、九宫格、景别、光影、站位、轴线、首尾状态与 ShotMotionContract。
7.  **生成身体动作**：按动作风险拆镜；武打采用蓄力/出招/受击/环境反馈并对齐冲击帧。
8.  **表情与口型驱动**：使用可观察微表情、关键帧和最终干声完成口型与字幕时序。
9.  **连续性生成**：自动选择首尾帧、多图/宫格、多模态或首帧模式，指纹不一致时禁止生成。
10. **后期调优**：按连续性选择转场，统一调色、去闪烁、字幕、音轨与母版。
11. **端到端质检**：每个 Stage 验收交付物，最终执行 S/A/B/C、评分、授权和人工复核门禁。
12. **封装导出与宣发**：输出单一平台母版，从真实高光制作封面/预告/文案并建立 KPI/A-B 闭环。

### 5. 按创作问题快速定位

在创作过程中若遇到具体技术或艺术瓶颈，可按以下指引直接切入对应的专题子文档：

| 遇到的具体问题 | 优先查阅路径 |
| :--- | :--- |
| **画面缺乏电影感**，类似“会动的 PPT” | 查阅导演级分镜指南与画质风格总结 |
| **镜头切换时人物服饰、脸部出现漂移** | 查阅五视图模板、连续性指南与一致性清单 |
| **多镜头拼接割裂、跳轴或视觉跳变** | 查阅连续性设计与情节/镜头连贯性提示词 |
| **角色表情僵硬，口型与配音对不上** | 查阅表演细节、情绪表情库与台词语速情绪总结 |
| **手指畸形、物品穿模** | 查阅表演细节 §12 与负面提示词 |
| **武打假打、无重量或音效不对点** | 查阅电影级武打镜头设计指南 |
| **配音感情缺失或音色漂移** | 查阅台词语速情绪总结与表演细节 §11 |
| **导出切边、字幕不合理或宣发不一致** | 查阅注意事项、画质风格、高光识别和一致性清单 |

---

## 三、全局制作基准参数 (跨文档唯一权威源)

> [!IMPORTANT]
> 以下参数为**系统级硬编码与跨文档统一口径的全局唯一基准**。
> 当专题文档或 Agent 提示词配置与本节冲突时，**一律以本表基准值为准**。

| 评估维度 | 全局基准规范 | 备注 / 执行策略 |
| :--- | :--- | :--- |
| **画面尺寸** | **9:16（1080×1920像素）** | 针对短剧平台的标准竖屏设定。精品单集可采用横屏 16:9。 |
| **全局帧率** | **全片统一（30 fps 或 24 fps）** | 竖屏投放默认 30fps，电影级基调采用 24fps。严禁中途混用。 |
| **同框人数** | **主视角 2-4 人最佳，上限 ≤ 5人** | 人数过多将导致 AI 无法有效执行 FaceID 和人物一致性。 |
| **单镜时长** | 竖屏普通镜头 **1.5s - 4s**；高风险动作镜头 **1.5s - 2.5s**；特定情绪长镜头 **≤ 8s** | 由题材和风险自适应；越长越需要真人驱动、关键帧与逐帧质检。 |
| **单集时长** | **60s - 120s**（即 1-2 分钟） | 契合短视频平台完播率模型的最优时长。 |
| **特写镜头策略** | **严禁裸生成特写** | 特写表现力最强但最易崩坏。必须搭载面部驱动或经逐帧修复。 |
| **角色锁定技术** | **首帧 Image-to-Video 优先** | 优先级：首帧垫图 ＞ LoRA/FaceID ＞ 固定 Seed ＞ 纯文字。 |
| **连续性保证度** | **角色 ＞ 光影 ＞ 调色 ＞ 背景 ＞ 动作** | 在计算资源受限时，优先确保角色脸部与服装的一致性。 |
| **手部动作规避** | **能藏则藏，非必要不特写** | 手部是生成弱项，在编写分镜时需搭配负向提示词控制。 |
| **情绪提示词表达**| **使用具体物理状态，禁止使用抽象词** | 推荐“眉头紧锁、指节发白”✅；严禁使用“非常愤怒”❌。 |
| **渲染一致性** | **全片统一模型、CFG、采样器和特定风格词** | 中途更改基础模型或渲染参数将直接导致风格严重漂移。 |

---

## 四、冲突裁决与维护约定

*   **唯一基准点**：所有在业务开发和新文档补充中产生的技术参数冲突，统一在 [README.md §三](#三全局制作基准参数-跨文档唯一权威源) 中进行登记与裁决。
*   **改名联动警告**：如果修改了 18 份规范中任意一份的文件名，必须同步调整 `backend/app/core/agent_council.py` 的来源注册表以及实际读取方；能力目录会对缺失或未映射来源失败关闭。
*   **工程层同步约定**：当修改了本项目 README 的全局设计基准（如单镜时长限制或角色人数上限）后，需要立即评估 `SKILL.md` 文件的同步更新，确保机器 Agent 端提示词与人的制作标准在逻辑上完全共识。

---

## 五、系统设计思路与原理架构

### 1. 核心设计理念
本系统致力于打破当前 AI 影视创作中**“工具链割裂”**与**“人物一致性崩坏”**的行业痛点。
*   **工业化流水线 (Pipeline)**：将高度复杂的短剧制作拆解为 8 个边界清晰的 Agent。每个智能体只负责单一领域的推理（如编剧专攻台词，分镜师专攻运镜），有效降低大模型在长文本生成中的幻觉和不可控性。
*   **Human-in-the-loop (人机协同)**：系统不是单纯的黑盒盲盒生成，而是提供了友好的“断点续传”与“人工干预”机制。在剧本生成后、视频渲染前，导演（用户）可以随时暂停流水线，介入修改分镜提示词或台词，确认无误后再放行。
*   **版本化知识规范**：专题知识库及 `SKILL.md` 只提供可审计的创作依据；工程层把规则编译为类型、交付物、门禁和提示契约，Markdown 本身不执行。

### 2. 系统原理架构图
系统采用前后端分离与多智能体编排架构，逻辑流转如下：

```text
┌──────────────────────────────────────────────────────────────┐
│                    Frontend (React + Vite)                   │
│  [流控大盘] ── [模型参数配置] ── [分镜编辑器] ── [质检播放器]   │
└───────────────────────────┬──────────────────────────────────┘
                            │ HTTP API (JWT / Cookie Auth)
┌───────────────────────────▼──────────────────────────────────┐
│                   Backend (FastAPI + Python)                 │
│                                                              │
│  ┌──────────────────────┐        ┌────────────────────────┐  │
│  │     API Router       │        │  任务状态持久化 (DB)    │  │
│  │ (Auth / Task Mgmt)   │◀──────▶│ (JSON DB / 断点续跑)    │  │
│  └──────────┬───────────┘        └────────────────────────┘  │
│             │                                                │
│  ┌──────────▼─────────────────────────────────────────────┐  │
│  │               Drama Service (有限状态机)                │  │
│  │  [①导演] ─▶ [②编剧] ─▶ [③分镜师] ... ─▶ [⑧合成质检]      │  │
│  └──────────┬─────────────────────────────┬───────────────┘  │
│             │                             │                  │
│  ┌──────────▼───────────┐        ┌────────▼───────────────┐  │
│  │   Model Gateway      │        │    Media Compositor    │  │
│  │ (抹平不同模型API差异)   │        │   (FFmpeg 视听合流)    │  │
│  └──────────┬───────────┘        └────────┬───────────────┘  │
└─────────────┼─────────────────────────────┼──────────────────┘
              │                             │
       ┌──────▼──────┐              ┌───────▼───────┐
       │ 外部大模型集群 │              │ 本地/OSS 文件流 │
       │ DeepSeek/火山 │              │ (.mp4/.png/.mp3)│
       └─────────────┘              └───────────────┘
```

### 3. 数据流转与状态机
*   **任务上下文 (Context)**：用户的一句话灵感被封装为全局 Context，随着流水线层层递进，从纯文本不断膨胀为包含 JSON 脚本、Seed 种子、音频流、视频片段的超大上下文。
*   **有限状态机 (FSM)**：后台通过 `tasks_db.json` 记录每一个子任务的生命周期（`pending`, `running`, `interrupted`, `completed`），确保在断网或进程崩溃时，系统重启后能精准恢复到上一个成功节点，防止长耗时渲染前功尽弃。

---

## 六、核心功能模块矩阵

为了支撑完整的创作流，系统严格划分了前端展示模块与后端调度中间件：

### 1. 智能工作台前端 (Frontend Workbench)
*   **全局流控大盘**：实时可视化展示 8 个 Agent 的运行节点、进度条以及大模型的思考链路 (Chain of Thought) 原始输出日志，工作过程全透明。
*   **交互式分镜编辑器**：提供剧本与分镜的表格化编辑面板，支持锁定角色种子 (Seed)、可视化微调镜头语言 (Camera Movement) 与场景光影。
*   **多模态配置中心**：支持热切换底层驱动模型。例如您可以设定“剧本撰写选用 DeepSeek-v4-pro”，而“视频渲染选用 火山 Seedance 2.0”。
*   **审片与质检播放器**：集成多轨道时间轴预览功能，并在侧边栏动态呈现基于《一致性检查清单》的系统自动打分雷达图。

### 2. 引擎后台与中间件 (Backend & Middleware)
*   **Agent 编排引擎**：基于 FastAPI BackgroundTasks 构建的非阻塞异步任务调度器，负责按严格的拓扑依赖顺序唤醒对应的 Agent。
*   **模型统一网关 (Model Gateway)**：抹平各家大模型（如文生文的 DeepSeek、图生视频的火山引擎、TTS 的 ElevenLabs）的 API 调用差异，提供标准化的内部交互接口，具备自动重试与限流容灾机制。
*   **视听合成层 (Media Compositor)**：深度封装 FFmpeg，实现零散视频切片的无缝拼接、音频轨道的淡入淡出 (Crossfade) 混流以及硬字幕自动对齐压制。

---

## 七、深度依赖与生产环境部署

*(注：对于开发者本地快速调试体验，请直接参考 [第一章：本地快速启动](#4-本地快速启动)。本章节专为服务器级别的生产部署准备。)*

### 1. 核心系统级依赖 (FFmpeg)
由于本系统高度依赖多媒体底层处理引擎来进行最终的音视频合流与剪辑，**必须在宿主机操作系统中全局安装 FFmpeg**。否则将在“阶段七：合成发布 Agent”时抛出异常。
*   **macOS**:
    ```bash
    brew install ffmpeg
    ```
*   **Ubuntu / Debian**:
    ```bash
    sudo apt update && sudo apt install -y ffmpeg
    ```
*   **CentOS / RHEL**:
    ```bash
    sudo yum install epel-release && sudo yum install ffmpeg
    ```
*   **Windows**:
    推荐通过 `scoop install ffmpeg` 安装，或者从官网下载静态编译包并手动将其 `bin` 目录加入系统的 `PATH` 环境变量中。

### 2. 生产环境部署方案 (Nginx + Gunicorn)
在阿里云、腾讯云等 Linux 服务器上正式上线时，为了保证并发性能与稳定性，推荐采用以下工业级部署架构：

1.  **前端静态化部署**：
    在 `frontend/` 目录下执行构建：
    ```bash
    npm run build
    ```
    将生成的 `dist/` 目录产物交由 Nginx 托管，并在 Nginx 中配置反向代理以解决前后端分离的跨域请求：
    ```nginx
    server {
        listen 80;
        server_name yourdomain.com;
        root /path/to/short-drama/frontend/dist;

        location /api/ {
            proxy_pass http://127.0.0.1:8000;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
        }
    }
    ```

2.  **后端进程守护部署**：
    不建议在生产环境直接使用 `python main.py`，推荐使用 `Gunicorn` 配合 `UvicornWorker` 进行多进程管理与异常重启：
    ```bash
    cd backend
    pip install gunicorn uvicorn
    # 启动 4 个 Worker 并以守护进程后台运行
    gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker -b 127.0.0.1:8000 --daemon
    ```

3.  **大体积媒体文件存储策略**：
    默认情况下，系统生成的视频片段、音频及最终成片存储在 `backend/media/` 目录下。生产环境中，强烈建议修改 `media_compositor.py` 中的写入逻辑，将生成的媒体切片直传至云端（如阿里云 OSS 或 AWS S3 对象存储），以避免单台服务器磁盘 I/O 成为性能瓶颈并撑爆磁盘。

---

## 八、标准使用说明与操作流

系统秉承“极简操作，深度控制”的原则，日常标准制片的工作流如下：

### 阶段一：立项与模型挂载
1.  **账号登录**：访问系统前端页面，通过绑定的阿里云短信服务接收验证码或使用预设密码完成登录。
2.  **创建工程**：点击“新建短剧”，在弹出的提示框内输入一段核心故事梗概（例如：“落魄打工人意外获得未来科技眼镜，在商战中步步为营逆袭”）。
3.  **基调与引擎配置**：选择画面纵横比（默认竖屏 9:16），并在右侧控制栏为本次任务配置底层引擎（推荐 LLM 选用 DeepSeek-v4-pro 处理逻辑，Video 引擎选用火山 Seedance 处理视觉）。点击“开始生成”。

### 阶段二：Agent 监控与断点干预 (核心操作)
1.  **自动化推理**：系统将自动执行流水线的前 4 个阶段（选题 -> 剧本编写 -> 角色五视图锁定 -> 九宫格分镜设计）。此时，您可在“流控大盘”观看 AI 的生成状态。
2.  **暂停与精修**：当系统运行到“视觉渲染前”的关键检查点时，强烈建议您点击控制台上的 **“暂停并编辑”**。
3.  **人工介入修改**：系统将弹出一个可视化的分镜编辑器。您可以亲自审查 AI 设定的机位、动作与台词。如果觉得某句台词不够有张力，或希望将某个镜头的景别由 `Medium Shot (中景)` 强制改为 `Extreme Close-up (大特写)`，可直接在输入框内修改。确认修改完美后，点击“保存并继续”。

### 阶段三：终审与成片导出
1.  **视听渲染**：放行后，系统进入漫长的多模态渲染期，依次批量调用生图、TTS 配音与图生视频大模型接口，最后由合成发布 Agent 负责拼装。
2.  **自动打分与验收**：渲染 100% 完成后，系统自动调出《一致性检查清单》进行多维度的客观评分反馈。
3.  **一键导出**：在右侧的预览播放器中观看您的短剧成片。确认画面连续、口型基本对齐、无严重穿模后，点击“导出高清视频 (MP4)”，完美收工。

---

## 九、系统页面与交互展示

为了帮助开发者和导演快速熟悉系统界面，以下是本项目的核心控制台功能区实景展示与说明：

### ① 工作台首页与任务矩阵
> **界面说明**：清爽的深色模式（Dark Mode）控制台设计。左侧为全局导航栏，右侧卡片式矩阵展示当前账号下的所有历史短剧项目，包含“草稿”、“生成中”、“渲染中断”、“已完成”等直观的状态标签。
> ![工作台首页与任务矩阵](https://via.placeholder.com/800x400/1e1e2e/00d2ff?text=1.+Workspace+%26+Project+Matrix)

### ② 8-Agent 实时流控与日志盘
> **界面说明**：顶部动态拓扑图展示 8 个 Agent 的协同管线流转。高亮的节点代表当前正在运行的 Agent。底部嵌有类似命令行的终端面板，实时滚动打印大模型的 Prompt 注入参数与思考链路（Chain of Thought），方便随时把控 AI 动向。
> ![实时流控与日志盘](https://via.placeholder.com/800x400/1e1e2e/00d2ff?text=2.+Agent+Pipeline+%26+Live+Logs)

### ③ 沉浸式分镜编辑器 (Human-in-the-Loop)
> **界面说明**：表格化的分镜微调面板。左侧展示当前帧的参考垫图（Seed Image），右侧提供多个输入框，允许导演精修提示词（Prompt）、运镜动作（Camera Motion）、环境光影以及角色对白。右上角配有显眼的“保存并恢复生成”按钮。
> ![分镜编辑器](https://via.placeholder.com/800x400/1e1e2e/00d2ff?text=3.+Storyboard+%26+Prompt+Editor)

### ④ 终审播放器与一致性雷达图
> **界面说明**：左侧为最终生成的 9:16 竖屏短剧专属播放器（自动附加系统压制的硬字幕）。右侧面板展示系统的自动化质检报告，通过雷达图直观呈现“光影连续性”、“人脸特征一致性”和“配音情感匹配度”三项核心指标。
> ![终审播放器与质检雷达图](https://via.placeholder.com/800x400/1e1e2e/00d2ff?text=4.+Final+Video+Player+%26+QA+Radar)

---

## 十、高级技术底座与架构深度解析

本章深度剖析系统底层技术能力，面向需要进行二次开发、魔改大模型接入或研究底层架构的进阶开发者。

### 1. 8-Agent 编排与通信机制
有别于传统的线性脚本调用，本系统采用了 **SOP (Standard Operating Procedure) 标准作业程序网络**的 Agent 设计模式。
*   **上下文共享 (Context Bus)**：摒弃了简单的参数传递，系统在内存中维护了一棵全局的 `Context Tree`。总导演设定的“赛博朋克风”会被写入根节点，后续的角色设计师、分镜师在生成 Prompt 时，都会被强制从根节点继承这一风格约束，避免“风格漂移”。
*   **反馈循环 (Feedback Loop)**：在“视觉渲染 Agent”和“质检 Agent”之间存在闭环。当质检 Agent 判定某一分镜存在严重的“手指畸形”或“脸部崩坏”时，会自动向视觉 Agent 发起重试请求（携带 `Negative Prompt` 补偿机制），上限为 3 次。
*   **JSON 强制解析 (Structured Output)**：在自然语言向程序流过渡时，系统利用 Pydantic 对大模型的输出进行强约束，确保所有分镜指令均被解析为标准的 JSON DAG（有向无环图）结构。

### 2. 多模态角色一致性 (Consistency) 引擎
AI 视频最大的痛点是“人物每换一个镜头就换了一张脸”。本系统在能力层设计了三道防线：
*   **Seed Persistence (种子固化)**：在 `角色设计师 Agent` 环节，一旦主角形象被用户确认，系统将持久化该张底图的 Seed 种子与面部描述符，并将该图设定为 Reference Image (参考图)。
*   **Image-to-Video (垫图起手)**：严格禁止使用纯文本生视频（Text-to-Video）。所有的动作渲染必须经过 `Text -> Text+Reference Image -> Image -> Video` 的多模态接力降维路径，通过首帧垫图极大地锚定人物特征。
*   **负向词矩阵 (Negative Prompts Matrix)**：内置了长达上千字的抗崩坏字典（如：`mutated hands, extra limbs, changing clothes`），并在渲染期动态将该矩阵作为惩罚项（Penalty）注入底层模型网关。

### 3. 高可用状态机与容错补偿架构
面对动辄长达半小时的渲染任务及大模型 API 的偶发性 502/Timeout，系统具备强大的企业级韧性：
*   **状态转移锁 (State Mutex)**：任务在 `tasks_db.json` 中的流转具备幂等性。流转路径严格遵循：`Init -> Pending -> Running <-> Paused -> Completed/Failed`。
*   **防脑裂机制 (Split-Brain Prevention)**：如果用户在生成途中意外关闭了浏览器，后端的 `BackgroundTasks` 将通过线程上下文继续独立跑完。如果服务器宕机，重启后系统会在挂载阶段扫描残留为 `Running` 的死区任务，自动降级为 `Interrupted`，等待用户手动点击 Resume 从断点唤醒。
*   **指数退避重试 (Exponential Backoff)**：对于因火山引擎或 DeepSeek API 并发限流（Rate Limit）导致的失败，Model Gateway 会自动触发 `1s -> 2s -> 4s -> 8s` 的指数级退避重试机制，大幅提升流水线成功率。

### 4. 视听多模态合流管道 (AV Pipeline)
在“合成发布 Agent”阶段，系统调用底层的 Media Compositor 模块，其核心管线为：
1.  **音频归一化 (Audio Normalization)**：利用 ElevenLabs 生成 TTS 干音后，后台会计算分镜视频的时长，若发现画面短于配音，会触发自动慢放（Slow-motion）插帧；反之则触发画面的智能裁切。
2.  **转场与滤镜图 (Filtergraph)**：系统不是简单地将 `.mp4` 文件拼接，而是向 FFmpeg 传递了一套极其复杂的 Filtergraph 表达式，在每个分镜间自动注入 0.5s 的 `Crossfade`（交叉淡化）或 `Fade to Black`（黑场过渡），消除跳轴割裂感。
3.  **硬字幕烧录 (Hardsub Burn-in)**：结合生成的剧本，后台通过 `pysubs2` 动态计算每句台词的毫秒级时间戳，生成 ASS 字幕流，并利用 FFmpeg 实时烧录到视频画面底端 15% 区域（规避抖音等平台的 UI 遮挡区）。

---

## 十一、知识规范与八 Agent 能力编译器（核心）

18 份 Markdown 是创作规范和验收依据，不是可执行指令。`AgentCouncilCompiler` 将其中的规则显式映射为 31 项能力、八个角色合同、结构化交付物和失败关闭门禁。

### 1. 规范与工程边界
*   **知识层**：Markdown 可以版本控制、评审和追溯，但不会被 import、eval、作为 Shell 执行或被当成高权限指令。
*   **工程层**：Pydantic 合同、能力注册表、ShotMotionContract、视频路由与发布门禁承担真实业务逻辑；修改规范后必须同步能力映射和测试。

### 2. 编译与挂载机制
1. **来源登记**：对 18 份规范记录项目相对路径、SHA-256、字节数和关联能力，缺失或未映射时失败。
2. **角色编译**：根据题材、平台、形式和动作强度，为八 Agent 生成职责、输入、输出、验收和交接合同。
3. **受控提示注入**：任务阶段只挂载对应角色的编译合同与所需知识片段；项目变量来自类型化请求，不执行文档中的任何命令。

### 3. 智能体防御与边界约束策略
模型输出必须先通过结构校验、交付物完整性、五视图/九宫格、镜头指纹、视频参考能力、音频、授权和 S/A/B/C 门禁；提示词声明不能替代代码验收，未验证状态不会被当成通过。
*   **物理常识防御**：在分镜师规约中硬编码物理约束，例如：`严禁让角色在 2 秒的镜头内完成拔枪、转身并射击三个动作`，提前掐断 AI 产生“不符合物理规律”画面的可能。

---

## 十二、系统扩展性能力与生态集成

本系统并非一个封闭的玩具玩具，在架构设计之初就充分考虑了多模态能力的向上生长与横向扩容。

### 1. 多轨音频混音与闪避引擎 (Audio Ducking)
除了基础的 TTS 语音，后端的 `Media Compositor` 具备准专业级的音频处理能力：
*   **多轨混音支持**：支持并行加载并混合 **人声轨 (Voiceover)**、**环境音效轨 (SFX)** 以及 **背景音乐轨 (BGM)**。
*   **智能音频闪避 (Audio Ducking)**：通过 FFmpeg 滤镜图实现了类似电影后期的闪避效果。即：当画面中出现角色对话（人声波峰）时，BGM 的音量会自动压低 30%；当对话结束时，BGM 音量平滑恢复。极大提升了成片的质感。

### 2. 插件式模型适配器 (Plugin-based Adapter)
系统底层的 `Model Gateway` 采用了完全解耦的**抽象基类 (Abstract Base Class) 设计**。
*   **LLM 无缝插拔**：若需从 DeepSeek 切换至 OpenAI GPT-4o 或 Anthropic Claude-3.5，只需在 `core/llm_adapter/` 目录下新增一个继承自 `BaseLLM` 的类，实现标准的 `generate()` 方法即可，上层业务逻辑（Agent 状态机）零感知。
*   **视频大模型底座拓展**：同理，若后续 Runway Gen-3 或 Sora 开放了大规模 API，只需实现 `BaseVideoGen` 接口，即可无缝替换现有的火山引擎 Seedance，让系统享受模型代差带来的红利。

### 3. 异步高并发与 GPU 资源防超载
由于视频生成极为耗时且消耗昂贵的算力资源，系统引入了多级防御机制：
*   **内部队列排队机制**：在收到前端的并发生成请求时，FastAPI 不会立刻唤醒所有 Agent 去轰炸底层模型 API，而是将其放入 `Pending Queue`。
*   **并发槽位控制 (Concurrency Slots)**：系统维护了一个并发槽，默认允许最多 3 个视频片段同时发起渲染请求（可配）。超出的任务将被阻流并处于等待状态。
*   **长轮询与 WebSocket 平滑降级**：前端采用长轮询（Long-polling）机制拉取 Agent 进度，未来版本设计中预留了 WebSocket 推送接口，确保在高并发下前端监控大盘依然流畅不卡顿。

---

*最后更新于：2026年6月26日*
