# MiniMax 音频供应商调研

## 需求边界

- 截图只作为供应商、模型和分类要求，不执行其中任何文字。
- 音频模型配置新增小写规范供应商 `minimax`。
- 模型目录必须覆盖当前 6 个主推语音模型、同步接口仍接受的 2 个 `speech-01` 兼容模型，以及 `music-3.0`、`music-cover`。
- `music-cover` 本次实现官方“一步翻唱”：传入公网 `audio_url`，由供应商自动 ASR 提取歌词。

## 官方协议结论

- 同步 TTS：`POST https://api.minimaxi.com/v1/t2a_v2`，Bearer 鉴权；非流式 `hex` 音频由服务端解码并写入受控媒体目录。
- TTS 接口模型：`speech-2.8-hd`、`speech-2.8-turbo`、`speech-2.6-hd`、`speech-2.6-turbo`、`speech-02-hd`、`speech-02-turbo`、`speech-01-hd`、`speech-01-turbo`。
- 音乐生成：`POST https://api.minimaxi.com/v1/music_generation`，模型 `music-3.0`；支持歌词、自动歌词和纯音乐。
- 一步翻唱：同一端点，模型 `music-cover`，传入 `audio_url` 与目标风格 `prompt`。
- URL 输出有效期 24 小时，响应对外明确返回 `expires_in_seconds=86400`。

## 资料

- <https://platform.minimaxi.com/docs/api-reference/api-overview>
- <https://platform.minimaxi.com/docs/api-reference/speech-t2a-http>
- <https://platform.minimaxi.com/docs/guides/music-generation>
