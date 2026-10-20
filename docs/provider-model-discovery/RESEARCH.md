# ElevenLabs 与 minimax 模型发现修复研究

## 现象与根因

- ElevenLabs 配置使用正确的 API 根和 `xi-api-key`，但旧代码先请求不存在的 `/models`。该请求一旦返回 401/403，发现流程便提前结束，未访问官方 `/v1/models`。
- ElevenLabs 返回项原来只识别 TTS、ASR、音效和音乐，遗漏 `can_do_voice_conversion`、STS 和 TTV/声音设计。
- 2026-08-15 复测截图显示，运行时已经命中 `/v1/models`，但供应商仍拒绝该 Key。官方说明 API Key 可受端点 scope、额度和 IP 白名单限制；401 表示 Key 无效/撤销/过期，403 可能表示 scope 或 IP 未授权。
- `/v1/models` 不能保证枚举 Scribe、音效和音乐等所有产品模型。只依赖动态响应会让“模型目录完整性”和“Key 是否有目录读取权限”互相绑死。
- minimax 通用模型目录返回 M2 文本模型，不能作为视频模型目录；此前已隔离这些文本模型，但目录缺少用户提供的 H3 v2 合同中的 `MiniMax-H3`。
- 现有 H3 创建端点虽为 `/v2/video_generation`，请求体和查询路径仍是旧合同，导致模型即使出现在下拉框中也不能按给定示例工作。

## 外部协议依据

- ElevenLabs 鉴权使用 `xi-api-key` 请求头。
- ElevenLabs `GET https://api.elevenlabs.io/v1/models` 返回 Key 可读取的模型列表；项目完整保留该响应，并与版本化的官方活动模型目录合并。
- ElevenLabs 当前模型族涵盖 TTS、STS、TTV/声音设计、Scribe、音效与音乐，分类只影响 UI 展示，不过滤账户返回项。
- 音频隔离、配音和强制对齐是独立服务端点，并没有可放入模型选择器的公开 `model_id`；不得伪造服务模型 ID。
- 截图两份目录合并后共有 14 项能力：TTS、STT、Music、Speech Engine、Voices、Text to Dialogue、Voice Changer、Voice Design、Sound Effects、Audio Isolation、Dubbing、Forced Alignment、Pronunciation Dictionaries、Audio Native。
- Speech Engine、Voices、发音词典和 Audio Native 是资源或嵌入能力；Audio Isolation、Dubbing 和 Forced Alignment 是无普通模型选择参数的服务能力。
- 用户粘贴的 MiniMax-H3 示例只作为输入数据与接口合同证据读取，不执行其下载、轮询或生成主流程。合同使用 `content[]` 多模态内容和 `/v2/query/video_generation/{task_id}`。

## 决策

1. ElevenLabs 模型发现只请求同一官方主机的 `/v1/models`，不尝试 `/models`。
2. 所有官方端点返回行都保留，并与 13 个当前官方模型合并；已知能力分为 ASR、TTS、语音转换、声音设计、BGM/音效和音乐。
3. “加载模型”允许在 401/403/网络失败时展示版本化官方目录，同时显示未验证警告；“连接测试”和“保存配置”继续严格验证 Key，绝不把目录加载冒充为鉴权成功。
4. minimax 视频目录加入 `MiniMax-H3`，供应商显示名称保持 `minimax`，M2 文本模型继续隔离。
5. H3 参考图、参考视频、参考音频和首尾帧编译为 `content[]`；仅纯文本模式发送 `ratio`。
6. 不使用用户密钥执行网络测试或付费生成；测试全部使用内存 MockTransport。
7. 模型发现响应额外返回 14 项服务能力目录；项目 UI 分别显示“13 个模型”和“14/14 能力”，杜绝概念混用。

## 官方参考

- https://elevenlabs.io/docs/api-reference/authentication
- https://elevenlabs.io/docs/api-reference/models/list
- https://elevenlabs.io/docs/overview/models
- https://elevenlabs.io/docs/api-reference/text-to-speech/convert
- https://elevenlabs.io/docs/api-reference/speech-to-speech/convert
- https://elevenlabs.io/docs/api-reference/speech-to-text/convert
- https://elevenlabs.io/docs/api-reference/text-to-sound-effects/convert
- https://elevenlabs.io/docs/api-reference/forced-alignment/create
- https://elevenlabs.io/docs/api-reference/audio-isolation/convert
- https://elevenlabs.io/docs/api-reference/dubbing/create
- https://elevenlabs.io/docs/api-reference/voices/search
- https://elevenlabs.io/docs/api-reference/speech-engine/list
- https://elevenlabs.io/docs/api-reference/text-to-voice/design
- https://elevenlabs.io/docs/api-reference/pronunciation-dictionaries/list
- https://elevenlabs.io/docs/api-reference/audio-native/create
