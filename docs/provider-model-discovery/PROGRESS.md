# ElevenLabs 与 minimax 模型发现修复进度

## 状态：实现与验证完成

- [x] 定位 ElevenLabs 错误端点优先级问题。
- [x] 对齐 ElevenLabs 官方鉴权头和模型列表端点。
- [x] 补齐语音转换、声音设计及完整音频分类。
- [x] 把 MiniMax-H3 加入 minimax 视频模型目录。
- [x] 对齐 H3 v2 `content[]` 和任务查询合同。
- [x] 增加后端与前端回归测试。
- [x] 后端 166 项、前端 9 项全量测试通过。
- [x] Python 编译、Ruff、TypeScript/Vite 构建和 ESLint 通过。
- [x] 强制 TLS 的前端依赖审计为 0 漏洞；本次差异未出现 API Key 模式。
- [x] 完成最终代码自审：端点、鉴权头、分类保留、H3 请求、查询结果和秘密处理均有回归断言。
- [x] 2026-08-15 补充 ElevenLabs 13 模型完整目录与动态合并。
- [x] 将只读目录加载和严格 Key 验证分离，补充 401/403 权限诊断与前端警告。
- [x] 完成截图要求的 ElevenLabs 14/14 能力目录和 13 个官方模型映射。
- [x] 补齐 Voices、Speech Engine、Voice Changer、Voice Design、Audio Isolation、Forced Alignment、Pronunciation Dictionaries 与 Audio Native 可调用 API。
