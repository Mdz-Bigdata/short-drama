# ElevenLabs 多模型配置调研

## 目标

- 按截图中的 14 类 ElevenLabs 能力展示完整入口。
- 有官方模型 ID 的能力支持分类筛选、复选与批量保存。
- 没有模型 ID 的能力继续作为独立服务展示，避免创建不可调用的伪模型。
- 已保存模型不设置业务数量上限，并允许逐项删除。

## 官方依据

- [ElevenLabs Models](https://elevenlabs.io/docs/overview/models)：当前活跃模型目录与模型 ID。
- [ElevenLabs Product overview](https://elevenlabs.io/docs/overview/intro)：语音、转录、音乐、音效、配音等能力范围。
- [Voices](https://elevenlabs.io/docs/overview/capabilities/voices)：声音库是资源能力，不是模型条目。
- [Voice Changer](https://elevenlabs.io/docs/overview/capabilities/voice-changer)：语音到语音转换能力。
- [Forced Alignment](https://elevenlabs.io/docs/overview/capabilities/forced-alignment)：独立对齐服务。
- [Pronunciation Dictionaries](https://elevenlabs.io/docs/eleven-api/guides/how-to/text-to-speech/pronunciation-dictionaries)：发音规则资源及模型兼容性。

## 结论

官方当前目录映射为 13 个活跃模型 ID；截图中的 14 项是能力/产品导航，两者不是一一对应。前端使用能力目录筛选真实模型，并明确显示独立服务。选择集合按 `model_id` 去重并跨分类保留。后端只要求至少选择一个模型，移除 50 项业务上限；供应商异常响应仍保留 1000 条防御性读取上限，它不是用户保存配额。

API Key 只经请求发送给后端并加密存储，文档、前端常量和测试夹具均不包含真实凭据。
