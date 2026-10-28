---
name: exchange-unit-master
description: 单元环扣——武是接化发、文是听思答：一个 U 推进一个半单元；武打按流派节奏 × 交互力量档定一个半单元几秒，对话按台词节奏定一轮几秒、几个字；两人以上的对话一格至少一个来回，格尾不空叹，三轮以上走起承转合。当出现打斗节奏、过招太慢、接化发、连招、流派、截拳道、散打、太极、高手、老人、孩子、交互力量、台词话轮、一个来回、空叹、起承转合、台词镜头等需求时使用本技能。
---

# 单元环扣（exchange-unit-master）

出品人 1025：一格分镜里的动作和台词都颗粒过粗——两个武林高手 9 秒只过两招，10 秒的对话只有半个来回、最后几秒只在叹气。
本技能把泽云灵映 1023–1025 新增信息包里的「交互力量」「武术环扣」「台词表达单元」三套表装进本项目，由
`app/core/exchange_units.py` 读表、判档、排节奏，再由第 4 阶段分镜表作者照着写、由分镜表复核照着查。

## 一句话

**一个 U 推进一个半单元。** U1＝起手（开口）＋对方第一次接化发（听思答）；之后每个 U 只写新的那一个人：
接住上一招、化开、发出新的一招（听上一句、想半拍、答出新的一句）。上一 U 的发（答）就是本 U 的来招（话头），同一招、同一句不重播。

## 武：接 → 化 → 发

- 一个半单元多长先看流派（`martial-tempo-tiers.csv`，MS1 截击短打 0.75 秒 … MS6 引化慢接 2.5 秒 … MS10 武侠写意 1.8 秒），
  再乘交互力量档倍率（`unit-code-table.csv`「交互力量档」：IP7 ×0.85　IP6 ×1　IP5 ×1.1　IP4 ×1.35　IP3 ×1.5　IP2 ×2；IP1 病重的人不进武打交锋），
  三人以上 ×1.2，不短于 0.6 秒。剧本没写流派：现代格斗、街头、警匪、擂台按散打（MS3）。
- 判档：健康压过技能，技能压过年龄；对抗双方取平均（MX1），相差三档以上一边倒按强者（MX2）；负伤、力竭、醉酒降一档（醉拳不算醉）。
- 一段连招 3–6 个半单元，段间「停」（对峙、拉开、喘息）1–1.5 秒，停不算单元、不放在格尾当填充；太极连绵不停；倒地后先起身再接站立的招。
- 同一人连续发起不超过两次；多人交锋一个 U 只写一个主交锋（`multi-fighter-modes.csv`）；异兵器各用各的兵器接招；散打要领见 `sanda-essentials.csv`。

## 文：听 → 思 → 答

- 一轮多长看台词节奏（`dialogue-tempo.csv`）：DT1 激烈争吵 4 秒 · DT2 交锋对峙 4.5 · DT3 日常交谈 5 · DT4 情感倾诉 6.5 · DT5 舒缓写意 9 · DT6 喜剧斗嘴 3。
- 一轮字数 ≈（话轮秒 − 思）× 语速 × 0.85；打斗里的一句不超过 8 字，落在化或发上。
- 两人以上的对话一格至少两个话轮（一个来回）；最后一句距格尾不超过颗尾余量（1–1.5 秒，写意 2.5 秒），剩下的只给有内容的收尾动作，不空叹。
- 三轮以上走起承转合（`dialogue-arc.csv`）：有一轮「转」，以「合」落定。独白一人铺满，不造对话者。
- 防串台：每句台词前点名说话人；同一时刻只有一人开口，听的人闭口给反应；换人开口用台词镜头换边（`dialogue-camera.csv`：过肩、反打、听者反应）。

## 本项目怎么用

| 环节 | 做什么 | 代码 |
|---|---|---|
| 第 4 阶段分镜表 | 每场判流派、力量档、台词节奏，给表格作者一段「单元环扣」：本场一个半单元几秒、各时长的格装几个、对话一轮几秒几个字 | `exchange_units.scene_brief` |
| 分镜表复核 | 打斗格的 U 太少、对话格少于一个来回、格尾空叹、一轮台词超字数、同一人连说三轮 | `exchange_units.audit_shot` → `shot_table_rules` |

## 参考文件

- `references/unit-code-table.csv`、`references/unit-spec.md`：三脑共用代码表与规格 V1.3（交互力量档、混档、状态修正、武术节奏、台词节奏、起承转合、台词镜头）
- `references/martial-tempo-tiers.csv`、`references/martial-style-tempo.csv`：武术节奏档（含判定词）与 34 个流派
- `references/dialogue-tempo.csv`、`references/dialogue-camera.csv`、`references/dialogue-arc.csv`：台词节奏、台词镜头、起承转合
- `references/chain-rules.csv`、`references/unit-kinds.csv`、`references/hard-checks.csv`：环扣纪律、单元类型、硬检查 SI-69～76
- `references/sanda-essentials.csv`、`references/multi-fighter-modes.csv`、`references/section-frames.csv`：散打要领、多人交锋、截面取帧
- `references/martial-chain-method.md`、`references/dialogue-unit-method.md`、`references/pack-readme.md`：P11-47～54、P12-01～25 原文与包说明

参考文件逐字照搬自新增信息包；其中提到的 `si_unit_plan.py`、`lfact.py`、O2F「二 U 行」是泽云灵映三脑系统的工具与模板，本项目不调用，
对应的事由上表两处代码完成。节奏秒数、话轮字数都是编排约定，**未经视频试点**。
