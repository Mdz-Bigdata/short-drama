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

## 2026-10-14 — 火山引擎 Ark 全目录按名称归类

- 现象：视频标签选 Seedance 点「加载模型」，列表里全是 `doubao-pro-32k-*` 文本模型。原因：Ark 的 `/api/v3/models` 返回整个方舟目录（文本、图像、视频、音频都在一起），而 `_classify` 对 `seedance` 有一条「分类专属目录」兜底——认不出的 id 一律按发起标签的分类贴标。全局目录不该走这条兜底。
- 修复（`backend/app/core/model_configuration.py`）：去掉 `seedance` 的兜底（Kling、ElevenLabs 的专属目录保留）；图像 / 视频名称模式补上方舟的命名：`seedream`、`seededit`、`dreamina`、`t2i`、`i2i` 归图像，`seaweed`、`t2v`、`i2v`、`wan`、`veo`、`sora`、`vidu`、`pixverse` 归视频（`seedance` 原本就有）。同一目录在文本 / 图像标签下是「火山引擎」供应商，走同一套归类。
- 反馈：`normalize_models` 统计被归到其他分类的模型数，`discover` 以 warnings 返回一句「已按名称自动归类：另有 N 个文本模型、M 个图像模型未列在视频分类下，请到对应标签加载」，模型配置中心把 warnings 显示为提示。单一分类的目录不带这句。
- 测试：`test_ark_global_catalog_is_filed_by_name_into_text_image_and_video`（同一份 12 条方舟目录在三个标签下各得其所，并互相报数；`vision` 文本模型标为多模态）、`test_a_catalog_of_one_category_carries_no_filing_note`。
