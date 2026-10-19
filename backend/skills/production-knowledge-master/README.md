# production-knowledge-master

## 这个技能是什么

八阶段短剧生产线（总导演策划 → 编剧剧本创作 → 角色设计师造型 → 分镜师分镜拆解 →
视觉总监多镜头生成 → 音频总监配音音效 → 合成发布渲染合流 → 宣发Agent引流）的
知识路由与教训进化中枢。SKILL.md 记录了各技能登记的知识章节的完整路由表——哪个
阶段、以什么字符预算、装载哪个章节、拼进提示词的哪个段落——以及负面提示词经
`agent_council.NEGATIVE_MODULE_WORDS` 模块词表生效的六个生成点；代码侧由
`app/core/production_knowledge.py`（装载器）与 `app/core/knowledge_evolution.py`
（进化引擎）落地。learned/ 目录存放流水线从质检报告中自动蒸馏、按命中率晋升
淘汰的历史生产教训，经 `stage_lessons_block(stage)` 注入各阶段提示词。

## 知识放在哪里

每份知识文档都住在它所属的技能里，并由该技能的 `manifest.json` 登记（键、标题、文件、
预算、消费阶段）；运行时只按章节键经 `app/core/knowledge_registry.py` 找到它，代码里
不出现任何知识文件名或路径。本技能自己负责五份：制作规范与关键元素、一致性检查清单、
负面提示词、高光识别、画质风格（都在 references/）。其余在 screenwriting-master、
shot-design-master、character-turnaround-consistency、shot-transitions-master 里。

- **修订内容**：直接改对应技能 references/ 下的文件；agent_council 会对所有登记章节重新
  计算 SHA-256 指纹。
- **改路由（阶段、预算）**：改该技能的 manifest.json，不必改代码；同步更新 SKILL.md 的
  路由表以便人读。
- **新增文档**：放到仓库根部，运行 `backend/scripts/organize_knowledge.py`（先加
  `--dry-run` 看去向）。路由规则在 `backend/skills/knowledge-routing.json`：点名的文档按
  表归位，其余按文件名与首个标题里的关键词归入技能。

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
4. **别动正典**：如果一条教训值得长期沉淀为规范，正确的去处是修订它所属技能里的
   知识文档（走人工评审，指纹随之更新），然后退休这条教训——教训库是缓冲区，不是第二正典。
