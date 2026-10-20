# ElevenLabs 与 minimax 模型发现修复实现

## 后端

- `model_configuration.py`
  - ElevenLabs 候选模型端点固定为 `/v1/models`。
  - 将动态返回与 13 个当前官方模型合并，补齐 TTS、STS、TTV、Scribe、音效和音乐。
  - 目录加载支持受限/无效 Key 的只读官方目录回退；连接测试和保存仍采用严格鉴权。
  - 401、403 分别给出“无效/撤销/过期”和“scope/IP 限制”诊断。
  - 增加 `voice_conversion` 与 `voice_design` 音频子分类。
  - 识别 ElevenLabs 能力布尔字段和 STS/TTV 模型命名，同时保留未知音频模型。
  - minimax 视频目录登记 `MiniMax-H3` 及多参考、多模态、首尾帧和原生音频能力。
- `elevenlabs_capabilities.py`
  - 登记截图两份菜单合并后的 14 项唯一能力、官方端点、项目入口和模型映射。
  - 确保 13 个当前官方模型全部至少映射到一个真实能力，无模型参数的服务保持空 `model_ids`。
- `elevenlabs.py` / `production_api.py`
  - 新增 Voices、Speech Engine、Voice Changer、Voice Design、Audio Isolation、Forced Alignment、Pronunciation Dictionaries 与 Audio Native 适配器和路由。
  - 上传大小/类型、WSS 公网地址、声音设计文本、发音规则和 Audio Native locator 均先做结构校验。
  - Voice Design 的 base64 预览在服务端解码为受控媒体文件，不把大段 base64 直接返回浏览器。
  - 选中的 Voice Design 候选可通过生成声音 ID 正式保存进声音库，完成官方两阶段流程。
  - TTS 与时间戳 TTS 可绑定最多三个发音词典版本，词典能力不止能管理，也能进入实际生成请求。
- `minimax_h3.py`
  - 生成请求改为 H3 v2 `content[]`。
  - 首帧、尾帧和参考媒体使用明确的 content role。
  - 默认查询端点改为 `/v2/query/video_generation/{task_id}`。
  - 从 `task.content.url` 读取最终视频；旧 v1 file_id 路径保留为显式配置的兼容回退。

## 前端

- 模型配置中心可显示“语音转换”和“声音设计”标签。
- Key 未验证时保留模型下拉框，并以黄色提示明确目录已加载但凭据未通过。
- 模型加载后显示 ElevenLabs 完整能力面板和 `14/14` 覆盖；独立服务不会混入模型下拉框。
- minimax 供应商名称保持小写规范名 `minimax`。

## 测试策略

- ElevenLabs 测试断言只访问 `/v1/models` 且携带 `xi-api-key`。
- 覆盖 API 根与完整 sound-generation Base URL 两种输入。
- 覆盖 TTS、STS、TTV、ASR、音效和音乐分类，断言响应模型不丢失。
- 覆盖 13 模型目录、动态合并、401 目录回退、403 scope 回退和严格连接测试。
- 覆盖 14 项能力 ID、全部项目路由、multipart 请求、严格请求 Schema 和 13 模型到能力映射。
- 覆盖 MiniMax-H3 目录、H3 v2 多模态请求、首尾帧和任务 URL 解析。
- 不使用真实密钥，不执行付费推理。
