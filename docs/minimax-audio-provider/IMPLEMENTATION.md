# MiniMax 音频供应商实现

## 模型配置

- `model_configuration.py` 将 `minimax` 加入音频供应商。
- MiniMax 通用模型目录只作无费用凭据探测；成功后返回版本锁定的 10 项音频目录，避免将 M 系列语言模型误归类为音频。
- `music-cover` 使用独立 `music_cover` 子分类，前端显示“音乐翻唱”。

## 生成适配器

- `MiniMaxAudioClient` 优先读取已保存并启用的 `minimax/audio` 运行时配置，其次读取服务端环境变量。
- `/v1/t2a_v2` 支持 8 个语音模型、声音、情绪、语速、音量、音调、发音字典与音频规格。
- `/v1/music_generation` 支持 `music-3.0` 和 `music-cover`；翻唱发送 `audio_url`，不伪造歌词或执行本地 ASR。
- HTTP 错误只暴露状态码、请求 ID 或 trace ID，不返回供应商响应正文与密钥。
- 翻唱参考拒绝凭据 URL、localhost 和私网 IP 字面量。

## 项目入口

- `POST /api/production/audio/minimax/tts`
- `POST /api/production/audio/minimax/music`
- `POST /api/production/audio/minimax/music-cover`
