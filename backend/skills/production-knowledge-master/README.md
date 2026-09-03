# production-knowledge-master

## 这个技能是什么

八阶段短剧生产线（总导演策划 → 编剧剧本创作 → 角色设计师造型 → 分镜师分镜拆解 →
视觉总监多镜头生成 → 音频总监配音音效 → 合成发布渲染合流 → 宣发Agent引流）的
知识路由与教训进化中枢。SKILL.md 记录了 16 份根部知识源文档的完整路由表——哪个
阶段、以什么字符预算、装载哪份文档、拼进提示词的哪个段落——以及负面提示词经
`agent_council.NEGATIVE_MODULE_WORDS` 模块词表生效的六个生成点；代码侧由
`app/core/production_knowledge.py`（装载器）与 `app/core/knowledge_evolution.py`
（进化引擎）落地。learned/ 目录存放流水线从质检报告中自动蒸馏、按命中率晋升
淘汰的历史生产教训，经 `stage_lessons_block(stage)` 注入各阶段提示词。

## 唯一事实源原则

16 份知识源 md **只存在于仓库根部**（如 `AI短剧连续性设计指南.md`），受
`agent_council.KNOWLEDGE_SOURCE_FILES` 的 SHA-256 指纹做 fail-closed 校验，是唯一
正典——本技能包**绝不复制**它们的任何内容：复制必然随时间漂移，且会绕过指纹校验，
让两份"事实"各说各话。技能包只放路由（SKILL.md）、进化数据（learned/）和本说明。
装载器按「章节键 → 根部文件名」映射去根部读取，根解析与 `read_md_file` 完全同源
（`DRAMA_PROMPT_ROOT` 环境变量优先，否则仓库根）。修订知识本身请直接改根部文档
并走指纹更新流程；改路由（阶段消费矩阵、预算）请同步修改 `production_knowledge.py`
与 SKILL.md 路由表，二者必须始终一致。

## 怎么人工审阅教训

教训库是机器产物，需要定期人工把关：

1. **看现状**：`learned/lessons.jsonl` 每行一条 LessonRecord，重点看
   `status`（candidate/active/retired）、`rule`（进提示词的正文）、`hits` 与
   `score`；`learned/evolution_log.jsonl` 是每次晋升/退休的流水账。代码侧可调
   `knowledge_evolution.evolution_report()` 拿各阶段计数与 top 规则。
2. **审 active 条目**：active 教训会实打实进入该阶段提示词（每阶段上限 12 条、
   注入预算 900 字符），发现错误或过时的规则，把该行 `status` 改为 `retired`
   （保留行本身，审计需要，不要删行）。
3. **人工补充**：确有把握的经验可手工追加一行 `trigger: "manual"` 的记录（candidate
   起步，命中两次后自动晋升；直接写 active 也允许，但要自负其责）。
4. **别动正典**：如果一条教训值得长期沉淀为规范，正确的去处是修订根部知识源文档
   （走人工评审 + 指纹更新），然后退休这条教训——教训库是缓冲区，不是第二正典。
