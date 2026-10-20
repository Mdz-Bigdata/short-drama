# -*- coding: utf-8 -*-
"""What to do when a generated shot comes back wrong.

A person watching a clip says "脸崩了" or "手是六根手指" — not "reduce the clear
character count to two". This turns that sentence into a category, a fix plan the
shot workspace can apply, and a line in the project's ledger.

Two things make it a loop rather than a form:

- **Escalation.** A shot that keeps failing is cut back in a fixed order — simplify the
  action, fewer people, fewer effects, split the shot, widen the framing — so the
  fourth attempt is not the first attempt with a different seed.
- **Memory.** The same failure twice on the same model becomes a weakness on that
  model's profile, and a fix that worked twice becomes a project pattern. Both are
  replayed as preventive notes the next time a shot like that is generated.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

Result = Literal["success", "partial", "failed"]
# A failure seen this many times on one model is treated as that model's weakness.
PROMOTE_AFTER = 2
LEDGER_KEY = "5_feedback"
MAX_HISTORY_PER_SHOT = 20


@dataclass(frozen=True)
class Failure:
    """One way a generated shot goes wrong, and what to do about it."""

    id: str
    name: str
    triggers: tuple[str, ...]
    diagnosis: str
    fixes: tuple[str, ...]
    # Knobs the shot workspace can actually turn.
    negatives: tuple[str, ...] = ()
    prevention: str = ""


FAILURES: tuple[Failure, ...] = (
    Failure(
        "face_collapse", "脸崩 / 换脸",
        ("脸崩", "崩脸", "脸糊", "脸歪", "变脸", "换脸", "五官", "不像", "face"),
        diagnosis="同框人数过多或人脸占比太小，模型分不清谁是谁。",
        fixes=(
            "把第三个人降为虚化、背影或剪影，画面里只留两个清晰人物",
            "拆成两镜：一镜两人，一镜单人反应",
            "给这一镜挂上该角色的设定图作参考图，并重述外形锚点",
        ),
        negatives=("面部畸形", "五官错位", "多张脸", "面部特征互换"),
        prevention="同框清晰人物不超过两人；人脸镜给足画面占比并挂设定图。",
    ),
    Failure(
        "hand_failure", "手部畸形",
        ("手", "手指", "六指", "多指", "指头", "hand", "finger"),
        diagnosis="手势超出模型稳定范围（结印、比心、捏取小物最容易出错）。",
        fixes=(
            "把手势降级为安全档：握拳、摊掌、单手抬起、手扶道具",
            "把手移出画面或藏进袖口、口袋、背后",
            "手部特写改成中景，让手不占主体",
        ),
        negatives=("多指", "少指", "手指融合", "手部畸形"),
        prevention="避免双手结印与捏取细小物件；手部特写优先改中景。",
    ),
    Failure(
        "occlusion", "特效糊脸",
        ("挡住", "遮住", "糊脸", "盖住脸", "特效挡", "光挡"),
        diagnosis="特效落在脸或关键道具上，被模型焊进了五官。",
        fixes=(
            "把特效移到安全区：脚下地面、身后背景、掌心前方的另一景深层",
            "在提示词里写明「面部干净、无符文阴影、不被遮挡」",
            "前景遮挡控制在画面 5%-15% 并虚化 60% 以上",
        ),
        negatives=("面部被遮挡", "符文覆盖面部"),
        prevention="特效不进人脸安全区；前景遮挡限制在画面边缘。",
    ),
    Failure(
        "action_blur", "动作糊成一团",
        ("糊", "看不清", "拖影", "动作乱", "模糊", "blur"),
        diagnosis="一镜里塞了多个动作，或运镜与动作同时高速。",
        fixes=(
            "按起手 → 碰撞 → 结果把这一镜拆成三镜",
            "一镜只留一个主运镜 + 一个主动作",
            "放慢运镜速度，让动作读得清",
        ),
        negatives=("动作拖影", "肢体残影"),
        prevention="一镜一个主动作；运镜与动作不同时冲到最快。",
    ),
    Failure(
        "colour_drift", "颜色漂移",
        ("颜色", "色偏", "变色", "衣服颜色", "色温", "colour", "color"),
        diagnosis="光影锁不完整，或两个角色的主色太接近。",
        fixes=(
            "补全光影锁：时间、天气、主光方向、色温、光比",
            "拉开两个角色的主色（色相至少差 90 度）",
            "把色卡挂成参考图，并写明「严格按色卡执行，不可偏离色板」",
        ),
        negatives=("色彩漂移", "服装变色"),
        prevention="同场景各镜复用同一条光影锁；角色主色互相拉开。",
    ),
    Failure(
        "spatial_break", "站位跳了 / 穿模",
        ("位置", "站位", "瞬移", "穿模", "穿墙", "穿透", "轴线", "越轴"),
        diagnosis="空间锁没有贯穿，或这一刀两侧的站位对不上。",
        fixes=(
            "回到空间调度里核对这一镜的站位与机位，重画本场",
            "补上交接句：上一镜末帧的位置、姿态与道具归属",
            "写明「物理实体、互不穿透」，并检查六层锁是否完整",
        ),
        negatives=("肢体穿模", "道具穿透", "人物瞬移"),
        prevention="每一镜复述空间锚与状态锁；切点两侧位置首尾相接。",
    ),
    Failure(
        "style_drift", "画风跑了",
        ("画风", "风格", "变成动画", "变成3d", "不写实", "太卡通", "style"),
        diagnosis="风格锁没有进到这一镜，或被参考图的介质带跑了。",
        fixes=(
            "确认项目风格锁，并把它逐字写进本镜提示词",
            "给跨介质参考图补反偷懒铁律（设定图、色卡、故事板、白模）",
            "把风格负面词提到全局区块，不要只写在某一镜",
        ),
        negatives=("风格突变", "画风不一致"),
        prevention="风格锁逐字重述；参考图一律配反偷懒铁律。",
    ),
    Failure(
        "expression_failure", "表情僵 / 没情绪",
        ("表情", "面瘫", "没情绪", "呆", "僵", "expression"),
        diagnosis="只写了情绪结论，没有写可观察的肌肉动作。",
        fixes=(
            "把情绪词换成五处微表情：眉心、下颌、瞳孔、眨眼节奏、指尖张力",
            "按情绪弧线校准强度档，别一上来就给满",
            "表情强度与景别匹配：微表情给近景以上",
        ),
        negatives=("面部僵硬", "呆滞眼神"),
        prevention="情绪一律写成可观察的身体细节，不写结论词。",
    ),
    Failure(
        "lip_sync", "口型对不上",
        ("口型", "对不上", "嘴没动", "嘴型", "lip", "sync"),
        diagnosis="台词长度超出镜头时长，或旁白被当成了现场对白。",
        fixes=(
            "按语速换算重排：台词时长不超过镜头时长的七成",
            "旁白写明「画面人物嘴唇保持闭合」",
            "一镜只留一个人说话，其余人闭口给反应",
        ),
        negatives=("口型不同步", "多人同时说话"),
        prevention="台词按语速预算写；旁白标明闭口。",
    ),
    Failure(
        "audio_muddy", "声音糊在一起",
        ("声音", "听不清", "对白被盖", "音乐盖", "配乐", "环境音", "audio"),
        diagnosis="三层声音没有分开写，或环境音与配乐没有压低。",
        fixes=(
            "按 center / ambient / music 三层重写，对白层只留人声",
            "环境音加 low volume、配乐加 low frequency 或直接写 none",
            "环境音层补 surround 或 left-right spread，把声场拉开",
        ),
        negatives=("对白被环境音淹没",),
        prevention="声音永远写成三层，对白权重最高。",
    ),
)
_BY_ID = {failure.id: failure for failure in FAILURES}

# When a shot keeps failing, this is the order things are given up.
ESCALATION: tuple[str, ...] = (
    "简化动作：安全手势、一镜一个主动作",
    "减少人物：三人降两人，多余角色转虚化或背影",
    "削减特效：特效系统降到一套、光层不超过四层且总覆盖不超过四成",
    "拆分镜头：把这一镜按起手 / 碰撞 / 结果拆开",
    "更换景别：特写改中景，失败的大场面改远景或剪影",
)


@dataclass
class FailureMatch:
    failure: Failure
    matched: str


@dataclass
class FixPlan:
    """What to do with this shot next."""

    primary: Failure
    secondary: list[Failure] = field(default_factory=list)
    attempt: int = 1
    steps: list[str] = field(default_factory=list)
    negatives: list[str] = field(default_factory=list)
    escalation: str = ""
    give_up: bool = False

    def as_dict(self) -> dict:
        return {
            "category": self.primary.id, "category_name": self.primary.name,
            "diagnosis": self.primary.diagnosis,
            "secondary": [item.id for item in self.secondary],
            "attempt": self.attempt, "steps": list(self.steps),
            "negatives": list(self.negatives), "escalation": self.escalation,
            "give_up": self.give_up,
        }


def get_failure(failure_id: str) -> Failure | None:
    return _BY_ID.get(str(failure_id or "").strip().lower())


def classify(text: str) -> list[FailureMatch]:
    """Every failure the report names, in the order the words appear."""
    haystack = str(text or "").lower()
    hits: list[tuple[int, FailureMatch]] = []
    for failure in FAILURES:
        found = [(haystack.find(word.lower()), word) for word in failure.triggers if word.lower() in haystack]
        if found:
            position, word = min(found)
            hits.append((position, FailureMatch(failure=failure, matched=word)))
    return [match for _, match in sorted(hits, key=lambda item: item[0])]


def plan_fix(text: str = "", *, category: str = "", attempt: int = 1) -> FixPlan | None:
    """The fix for this report; ``None`` when nothing in it names a known failure."""
    matches = classify(text)
    chosen = get_failure(category) or (matches[0].failure if matches else None)
    if chosen is None:
        return None
    secondary = [match.failure for match in matches if match.failure.id != chosen.id][:2]
    attempt = max(1, int(attempt or 1))
    steps = list(chosen.fixes)
    escalation = ""
    if attempt >= 2:
        # Every retry past the first gives something up, in the same order every time.
        cuts = ESCALATION[: min(attempt - 1, len(ESCALATION))]
        escalation = cuts[-1]
        steps.append(f"第{attempt}次重试，按退让顺序执行：{escalation}")
    give_up = attempt > len(ESCALATION)
    if give_up:
        steps.append("已到模型能力边界：换等价表达（剪影打斗、道具发光代替结印）或换一个视频模型")
    return FixPlan(
        primary=chosen, secondary=secondary, attempt=attempt, steps=steps,
        negatives=list(dict.fromkeys([*chosen.negatives, *(term for item in secondary for term in item.negatives)])),
        escalation=escalation, give_up=give_up,
    )


# ---------------------------------------------------------------------------------------------
# The ledger


def _ledger(task: Mapping[str, Any]) -> dict:
    assets = task.get("assets") if isinstance(task.get("assets"), dict) else {}
    stored = assets.get(LEDGER_KEY)
    ledger = stored if isinstance(stored, dict) else {}
    ledger.setdefault("shots", {})
    ledger.setdefault("model_profiles", {})
    ledger.setdefault("patterns", [])
    ledger.setdefault("stats", {"reports": 0, "success": 0, "partial": 0, "failed": 0})
    return ledger


def record(
    task: dict[str, Any], *, shot_id: Any, result: Result, text: str = "", category: str = "", model: str = "",
    applied_fix: str = "",
) -> dict:
    """Write one report into the project's ledger and return what to do next.

    A failure seen twice on the same model becomes that model's weakness; a fix that
    worked twice becomes a project pattern. Both are replayed later as prevention.
    """
    assets = task.setdefault("assets", {})
    ledger = _ledger(task)
    key = str(shot_id)
    history = ledger["shots"].setdefault(key, [])
    attempt = sum(1 for entry in history if entry.get("result") != "success") + 1

    plan = plan_fix(text, category=category, attempt=attempt) if result != "success" else None
    entry = {
        "result": result, "text": str(text or "")[:500], "model": str(model or ""),
        "category": plan.primary.id if plan else "", "attempt": attempt,
        "applied_fix": str(applied_fix or "")[:300],
    }
    history.append(entry)
    del history[:-MAX_HISTORY_PER_SHOT]

    stats = ledger["stats"]
    stats["reports"] = int(stats.get("reports", 0)) + 1
    stats[result] = int(stats.get(result, 0)) + 1

    if plan is not None and model:
        profile = ledger["model_profiles"].setdefault(model, {"counts": {}, "weaknesses": []})
        counts = profile["counts"]
        counts[plan.primary.id] = int(counts.get(plan.primary.id, 0)) + 1
        if counts[plan.primary.id] >= PROMOTE_AFTER and plan.primary.id not in profile["weaknesses"]:
            profile["weaknesses"].append(plan.primary.id)
    if result == "success" and applied_fix:
        worked = [item for item in ledger["patterns"] if item.get("fix") == applied_fix]
        if worked:
            worked[0]["hits"] = int(worked[0].get("hits", 1)) + 1
        else:
            ledger["patterns"].append({"fix": applied_fix, "hits": 1})

    assets[LEDGER_KEY] = ledger
    return {"ledger": ledger, "plan": plan.as_dict() if plan else None, "attempt": attempt}


def weaknesses(task: Mapping[str, Any], model: str) -> list[Failure]:
    """What this model has already proved it is bad at on this project."""
    profile = _ledger(task)["model_profiles"].get(str(model or ""), {})
    return [failure for failure in (get_failure(item) for item in profile.get("weaknesses", [])) if failure]


def preventive_notes(task: Mapping[str, Any], model: str) -> list[str]:
    """Lines to put in the next prompt, so a known weakness is designed around."""
    notes = [f"{failure.name}：{failure.prevention}" for failure in weaknesses(task, model) if failure.prevention]
    patterns = [
        item["fix"] for item in _ledger(task)["patterns"]
        if isinstance(item, Mapping) and int(item.get("hits", 0)) >= PROMOTE_AFTER and item.get("fix")
    ]
    notes.extend(f"本项目已验证有效：{fix}" for fix in patterns[:3])
    return notes


def preventive_negatives(task: Mapping[str, Any], model: str) -> list[str]:
    """Negative terms a known weakness earns, added on top of the usual ones."""
    return list(dict.fromkeys(term for failure in weaknesses(task, model) for term in failure.negatives))


def summary(task: Mapping[str, Any]) -> dict:
    """The ledger as the workspace shows it."""
    ledger = _ledger(task)
    by_category: dict[str, int] = {}
    for entries in ledger["shots"].values():
        for entry in entries:
            if entry.get("category"):
                by_category[entry["category"]] = by_category.get(entry["category"], 0) + 1
    return {
        "stats": dict(ledger["stats"]),
        "top_failures": [
            {"category": key, "name": _BY_ID[key].name if key in _BY_ID else key, "count": count}
            for key, count in sorted(by_category.items(), key=lambda item: -item[1])[:5]
        ],
        "model_profiles": {
            model: {
                "weaknesses": [
                    {"category": item, "name": _BY_ID[item].name if item in _BY_ID else item}
                    for item in profile.get("weaknesses", [])
                ],
            }
            for model, profile in ledger["model_profiles"].items()
        },
        "patterns": [item for item in ledger["patterns"] if int(item.get("hits", 0)) >= PROMOTE_AFTER],
        "shots": {
            shot: {"attempts": len(entries), "last": entries[-1] if entries else None}
            for shot, entries in ledger["shots"].items()
        },
    }


def describe() -> list[dict]:
    """The catalogue the reporting UI shows."""
    return [
        {
            "id": failure.id, "name": failure.name, "triggers": list(failure.triggers),
            "diagnosis": failure.diagnosis, "fixes": list(failure.fixes), "negatives": list(failure.negatives),
        }
        for failure in FAILURES
    ]


__all__ = [
    "ESCALATION", "FAILURES", "LEDGER_KEY", "PROMOTE_AFTER", "Failure", "FailureMatch", "FixPlan",
    "classify", "describe", "get_failure", "plan_fix", "preventive_negatives", "preventive_notes",
    "record", "summary", "weaknesses",
]
