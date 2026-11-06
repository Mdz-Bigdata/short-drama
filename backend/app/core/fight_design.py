# -*- coding: utf-8 -*-
"""Designing a fight before it is shot: why it happens, how each side fights, where it moves.

Stage 4 already turns a fight scene into shots (``DramaService._detect_scene_kind`` loads the
choreography chapters of the shot-design skill). What reaches it is only as good as the scene
the writer planned, so the writer's episode plan and visual layer get their own fight rules:

* **Cause before moves.** Who fights whom and why, how it escalates, the turn, and a win that
  comes from a weakness shown earlier, never a power that appears from nowhere.
* **A style per fighter.** Opening stance, best distance, footwork, main attack, how they
  break a guard, how they take a hit, how they finish.
* **One exchange, one chain.** Intent, wind-up and path, the other side's answer,
  hit / miss / block, the force landing, the resulting position. That end is the next exchange's start.
* **A shot is one generation, cut by its length:** 1–2 segments for 4–6 s up to 3–5 for 11–15 s,
  none shorter than 2.5 s; contact is a point on a path, and flash, shake and slow motion are rationed.
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
3. **一个回合一条因果链**：出手意图 → 起势与轨迹 → 对手怎么应对 → 命中 / 落空 / 被格挡 → 受力反馈（身体、兵器、衣物、环境）→ 位移与状态结果。这个结果就是下一回合的起点，回合之间一路接下去，不各自复位重来（武是接化发：上一招的发就是下一招的来招）。交锋多密按流派与人物的交互力量档定：截拳道约 0.75 秒一个半单元、散打约 1.5 秒、太极约 2.5 秒，高手比常人快、老人慢、病重的人不进交锋——两个高手 9 秒至少过四招；写清参战人物的身份、武功与伤病，分镜阶段据此排单元。
4. **空间要有路线**：交代起点、转折处与终点，至少用上一次场景里的可交互物（柱子、桌案、台阶、水面、栏杆）；双方的左右关系保持稳定，要换边就让人物在画面里走过去。
5. **一打多不排队**：围攻方同时施压、互相掩护，主角靠走位和地形把局面拆成一对一，而不是敌人轮流上前挨打。
6. **特殊能力四段成立**：法术、异能、法器写成 前置条件 → 发动 → 作用 → 结束；它需要的法器、血契、介质或代价必须在本集或前文出现过，不得临场补设。
7. **快进快出**：第一个打斗分镜的第一拍就是有效动作，第一次接触落在开场 1.5 秒前后，不拖长对峙；打戏最后一个分镜里仍有人物、镜头或环境余波在动（尘土落下、衣摆回摆、刀尖滴血），不要定格摆拍。
8. **台词嵌在攻防间隙**：打斗中的台词短而有力、一两句，放在拉开距离或僵持的瞬间，用来亮明立场、挑衅或揭示破绽，不要边打边长篇对白。
"""

VISUAL_RULES = """# 打斗分镜的视觉写法（打斗分镜适用，优先于上文「低缓细微动作」的一般要求）

- **按时长分段**：一条分镜就是一次生成。4–6 秒分 1–2 段，7–10 秒分 2–3 段，11–15 秒分 3–5 段；每段 2.5–4 秒，最短的一段也要 2.5 秒。成片上更碎的快切是剪辑台从这些段里裁出来的，生成时不写。
- **密度**：第一拍就是有效动作，第一次接触落在 1.5 秒前后；交锋次数按流派节奏 × 交互力量档（宗师 ×0.85、高手 ×1、习武 ×1.1、孩童 ×1.35、常人 ×1.5、老人 ×2），每段装若干个环扣的半单元（接→化→发），中段至少一次攻守易位。
- **video_prompt.action** 每段一个主动作，按「攻方动作 → 守方反应 → 接触结果 → 受力反馈 → 落点姿态」写成连贯句子，不叠加第二套动作。
- **接触是路径上的一个点**：写满「起势 → 加速 → 接触 → 受力形变 → 继续推进 → 滑开 / 擦过 → 转入下一动作」，句子不停在接触那一下；同一瞬间的细节一起写齐：接触点的火花或碎屑、双方身体各自的反应、衣摆与发丝、脚下地面、旁边被带动的物件。
- 写身体路径而不是招式名：发力部位、轨迹方向（画面左 / 右 / 纵深）、接触点与对手被推开的方向；不要只写「使出一招××」。
- **每段重述站位**：谁在画左、谁在画右、各自朝向、相隔多远（至少半个身位）；接触点给出画面位置，如「接触点位于画面正中偏上」。双方左右关系与观察轴全程不变。
- 双方肢体与兵器轮廓分明、彼此之间留出空隙；刀光、法术光效让开关键接触点。
- 承接上一分镜的落点姿态、伤势与兵器状态（断刃、脱手、沾血），已有的损伤在后面每一段都照写；手里的兵器与持握的手保持原样。
- **打击感只给关键处**：2–3 帧黑白或白闪冲击帧只给关键击与终结击；镜头震动放在接触之后，只震一次；动态模糊落在环境与运动边缘，接触点保持清晰；慢动作只放在最后 1–2 秒。
- **特效跟着招式的形状走**：横斩扫出一道宽扇形，上撩是向上扬起的月牙，下劈是沉重的楔形；大特效只给大幅度的挥砍，轻击只溅火花；每个角色固定一种特效颜色，全场不换。特效从兵器或接触点发出，找不到来源就不加。
- **video_prompt.camera_motion** 选跟随动作的运镜（跟拍、横移、环绕、推拉），速度贴着攻击方向，运动强度可以高；固定机位只留给开打前的对峙。
- **image_prompt.scene** 就是这条分镜的首帧：定格在出手前的起势姿态（重心下沉、兵器扬起、双方对视），两人轮廓分开，给动作留出画面空间。
- **负面要求少写、正着写**：写画面里有什么（「两人之间隔着半个身位」），不写「不要 X」，也不把要避开的那个名词再写一遍；容易被误读的名词改写成形状与空间关系。
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
