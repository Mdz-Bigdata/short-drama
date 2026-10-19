# -*- coding: utf-8 -*-
"""Designing a fight before it is shot: why it happens, how each side fights, where it moves.

Stage 4 already turns a fight scene into shots (``DramaService._detect_scene_kind`` loads the
choreography chapters of the shot-design skill). What reaches it is only as good as the scene
the writer planned, so the writer's episode plan and visual layer get their own fight rules:

* **Cause before moves.** Who fights whom and why, how it escalates, the turn, and a win that
  comes from a weakness shown earlier, never a power that appears from nowhere.
* **A style per fighter.** Opening stance, best distance, footwork, main attack, how they
  break a guard, how they take a hit, how they finish.
* **One exchange per shot, as a chain.** Intent, wind-up and path, the other side's answer,
  hit / miss / block, the force landing, the resulting position. That end is the next shot's start.
* **A route through the space,** using what the set offers, with a stable left/right relation.
* **Many against one never queues;** an ability needs its precondition set up before it fires.

The method is adapted, in this project's own words, from the Apache-2.0 ``SKILL.md`` of
qualsenWeb/fight-video-create-skill (commit 8a5afd2, reviewed 2026-10-18). Its move, ability,
scene and script libraries are CC BY-NC-ND 4.0 and shipped encrypted; none of them is used, and
its router script, which decrypts and executes a bundled payload, was not run.

A xianxia fight (flying swords, sword qi, lightning, formations) also gets the scene-level parts of
this project's own ``xianxia-combat-vfx`` reference: the three-round skeleton and the four ending
protocols in the plan, the energy states, scale kit and close exchanges in the visual layer. They are
read from that file, so it stays the single source, and the Seedance 2.5 director layer keeps reading
the same file per shot.

The fight vocabulary lives here so the writer and the storyboard stage judge a fight the same way.
"""

from __future__ import annotations

import re

from app.core import knowledge_registry

# Only fights use these words.
STRONG_SIGNALS: tuple[str, ...] = (
    "打斗", "打戏", "武打", "动作戏", "对打", "过招", "交手", "缠斗", "混战", "厮杀",
    "格斗", "搏斗", "械斗", "单挑", "群殴", "出招", "招式", "拳脚", "挥拳", "出拳",
    "飞踢", "踢腿", "肘击", "膝撞", "擒拿", "反手夺刀", "拔剑", "拔刀", "刀光", "剑光",
    "刀剑相接", "短兵相接", "拳拳到肉", "受击", "被击退", "重拳", "扫腿", "腾空跃起",
    # A xianxia fight is often written in energy attacks alone: 「劈出一道紫电刀气横斩」.
    "剑气", "刀气", "斩向", "劈向", "刺向", "击飞", "震飞", "反杀", "连招", "大招",
)
# Conflict words a dialogue scene uses too: they only add weight to a strong signal.
WEAK_SIGNALS: tuple[str, ...] = (
    "冲突", "对峙", "扭打", "推搡", "撕扯", "追逐", "围攻", "反击", "格挡", "闪身",
    "倒地", "翻滚", "血迹", "兵器", "长剑", "匕首", "刀刃",
)
# A genre alone is no evidence (a wuxia drama has long dialogue scenes); it adds one point.
FIGHT_GENRES = frozenset({"wuxia", "xianxia", "military", "sports", "action"})
FIGHT_THRESHOLD = 3
# Words that make a fight a xianxia one (with the Seedance 2.5 director layer, which reads the same list).
XIANXIA_MARKERS: tuple[str, ...] = (
    "剑气", "刀气", "拳气", "灵力", "真气", "法阵", "飞剑", "法术", "神通", "法相", "修仙", "仙", "妖", "魔",
    "雷劫", "雷柱", "天雷", "紫电", "御剑", "符文", "结界", "灵光", "光刃", "大招",
)
XIANXIA_REFERENCE = "xianxia-combat-vfx"
# Heading keywords of that reference: what the plan decides, and what each shot has to show.
XIANXIA_PLAN_SECTIONS = ("三轮攻守", "收束协议")
XIANXIA_VISUAL_SECTIONS = ("能量四态", "尺度四件套", "近景对招")


def fight_score(text: str, genre: str = "") -> int:
    """Two points per strong signal (at most three), one per weak signal (at most two), one for the genre.

    Without a strong signal the score is 0: a standoff full of conflict words is not a fight.
    """
    content = text or ""
    strong = sum(1 for word in STRONG_SIGNALS if word in content)
    if not strong:
        return 0
    weak = sum(1 for word in WEAK_SIGNALS if word in content)
    score = 2 * min(strong, 3) + min(weak, 2)
    if str(genre or "").strip().lower() in FIGHT_GENRES:
        score += 1
    return score


def looks_like_fight(text: str, genre: str = "") -> bool:
    """Three points: one strong signal plus a weak one or the genre, or two strong signals."""
    return fight_score(text, genre) >= FIGHT_THRESHOLD


def is_xianxia_fight(text: str, genre: str = "") -> bool:
    """A fight whose attacks or setting are xianxia: energy, formations, immortals, demons."""
    return looks_like_fight(text, genre) and any(marker in (text or "") for marker in XIANXIA_MARKERS)


def xianxia_sections(keywords: tuple[str, ...]) -> str:
    """The ``## `` sections of the xianxia reference whose heading names one of ``keywords``.

    Lines meant for a video model's syntax (「Seedance 2.5 写法…」) stay out of the writer's prompt.
    Empty when the reference is not installed.
    """
    item = knowledge_registry.section(XIANXIA_REFERENCE)
    if item is None:
        return ""
    try:
        text = item.path.read_text(encoding="utf-8")
    except OSError:
        return ""
    picked: list[str] = []
    for block in re.split(r"(?m)^(?=## )", text):
        heading = block.splitlines()[0] if block.strip() else ""
        if heading.startswith("## ") and any(keyword in heading for keyword in keywords):
            lines = [line for line in block.splitlines() if not line.startswith("Seedance")]
            picked.append("#" + "\n".join(lines).strip())
    return "\n\n".join(picked)


PLAN_RULES = """# 打戏设计（本集含打斗时适用）

原文或大纲已经写定的人物、阵营、武器、能力、出招顺序、胜负与结尾一律照办；下面只管把这场打戏写得成立、好拍。
1. **先定因果再写招**：交代谁为什么动手、各自想要什么；冲突逐级升级，中段至少一次攻守易位；胜负必须来自前文已经露出的破绽、伤势、地形或条件，不能临场爆发、凭空翻盘。
2. **每人一套打法**：给每个参战角色定好起手架势、擅长距离、移动方式、主攻手段、破招办法、受击反应与收招方式；两人的打法一眼就能分开。
3. **一个分镜写一个回合的因果**：出手意图 → 起势与轨迹 → 对手怎么应对 → 命中 / 落空 / 被格挡 → 受力反馈（身体、兵器、衣物、环境）→ 位移与状态结果。这个结果就是下一个分镜的起点，不要回合制地各自复位重来。
4. **空间要有路线**：交代起点、转折处与终点，至少用上一次场景里的可交互物（柱子、桌案、台阶、水面、栏杆）；双方的左右关系保持稳定，要换边就让人物在画面里走过去。
5. **一打多不排队**：围攻方同时施压、互相掩护，主角靠走位和地形把局面拆成一对一，而不是敌人轮流上前挨打。
6. **特殊能力四段成立**：法术、异能、法器写成 前置条件 → 发动 → 作用 → 结束；它需要的法器、血契、介质或代价必须在本集或前文出现过，不得临场补设。
7. **快进快出**：第一个打斗分镜就进入有效动作，不拖长对峙；打戏最后一个分镜里仍有人物、镜头或环境余波在动（尘土落下、衣摆回摆、刀尖滴血），不要定格摆拍。
8. **台词嵌在攻防间隙**：打斗中的台词短而有力、一两句，放在拉开距离或僵持的瞬间，用来亮明立场、挑衅或揭示破绽，不要边打边长篇对白。
"""

VISUAL_RULES = """# 打斗分镜的视觉写法（打斗分镜适用，优先于上文「低缓细微动作」的一般要求）

- **video_prompt.action** 一条只写一个回合，按「攻方动作 → 守方反应 → 接触结果 → 受力反馈 → 落点姿态」的顺序写成连贯句子，不叠加第二套动作。
- 写身体路径而不是招式名：发力部位、轨迹方向（画面左 / 右 / 纵深）、接触点与对手被推开的方向；不要只写「使出一招××」。
- 承接上一分镜的落点姿态、伤势与兵器状态（断刃、脱手、沾血），不要无故复位、换手或换兵器。
- 双方肢体与兵器保持分离可辨，禁止身体或兵器互相融合；刀光、法术光效不遮挡关键接触点。
- 保持双方左右关系与观察轴，不随机越轴。
- **image_prompt.scene** 定格在这一回合出手前的一瞬（蓄力、起手、对视），给动作留出画面空间。
"""


def _with_xianxia(rules: str, text: str, genre: str, keywords: tuple[str, ...], title: str, note: str = "") -> str:
    if not is_xianxia_fight(text, genre):
        return rules
    extra = xianxia_sections(keywords)
    lead = f"{note}\n\n" if note else ""
    return f"{rules}\n# {title}\n\n{lead}{extra}\n" if extra else rules


def plan_rules_for(*texts: str, genre: str = "") -> str:
    """The plan's fight block when this episode's text describes a fight, otherwise empty.

    A xianxia fight also gets the three-round skeleton and the four ending protocols.
    """
    text = "\n".join(str(item or "") for item in texts)
    if not looks_like_fight(text, genre):
        return ""
    return _with_xianxia(
        PLAN_RULES, text, genre, XIANXIA_PLAN_SECTIONS, "玄幻打戏补充（本集为玄幻打戏时适用）",
        note="原文或大纲已写定的胜负、出招顺序与结尾优先；下面的三轮骨架与收束协议只用来补全原文没写定的部分。",
    )


def visual_rules_for(*texts: str, genre: str = "") -> str:
    """The visual layer's fight block when these shots describe a fight, otherwise empty.

    A xianxia fight also gets the energy states, the scale kit and the close-exchange rules.
    """
    text = "\n".join(str(item or "") for item in texts)
    if not looks_like_fight(text, genre):
        return ""
    return _with_xianxia(VISUAL_RULES, text, genre, XIANXIA_VISUAL_SECTIONS, "玄幻打斗分镜补充（玄幻打斗分镜适用）")


__all__ = [
    "FIGHT_GENRES", "FIGHT_THRESHOLD", "PLAN_RULES", "STRONG_SIGNALS", "VISUAL_RULES", "WEAK_SIGNALS",
    "XIANXIA_MARKERS", "XIANXIA_PLAN_SECTIONS", "XIANXIA_REFERENCE", "XIANXIA_VISUAL_SECTIONS",
    "fight_score", "is_xianxia_fight", "looks_like_fight", "plan_rules_for", "visual_rules_for", "xianxia_sections",
]
