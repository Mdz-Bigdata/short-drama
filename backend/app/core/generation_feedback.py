# -*- coding: utf-8 -*-
"""What to do when a generated shot comes back wrong.

A person watching a clip says "脸崩了" or "手是六根手指" — not "reduce the clear
character count to two". This turns that sentence into a category, a fix plan the
shot workspace can apply, and a line in the project's ledger.

Two things make it a loop rather than a form:

- **One kind of change per round.** Every fix belongs to one class of variable — the action
  (what the bodies do), the camera (size, setup, axis, cut points) or the reference material
  (first frame, character and weapon images, the gap between first and last frame); sound has
  its own. A retry changes one class only, so the next result says whether that class was the
  problem, and it gives something up in that class in a fixed order. Two rounds in one class
  without improvement mean the failure was put in the wrong class: the next round turns to another.
  A sound failure that no class fixes ends by taking the dialogue out of the video model: the
  clip is rendered without the line and the line is dubbed in post.
- **Memory.** The same failure twice on the same model becomes a weakness on that
  model's profile, and a fix that worked twice becomes a project pattern. Both are
  replayed as preventive notes the next time a shot like that is generated.

The variable classes, the round discipline and the fight symptoms are adapted, in this project's own
words, from the diagnostics reference of the MIT ``fight-prompt-director`` skill vendored in
``backend/skills/fight-prompt-director``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

Result = Literal["success", "partial", "failed"]
# A failure seen this many times on one model is treated as that model's weakness.
PROMOTE_AFTER = 2
LEDGER_KEY = "5_feedback"
MAX_HISTORY_PER_SHOT = 20


Variable = Literal["action", "camera", "reference", "sound"]
VARIABLE_NAMES: dict[str, str] = {"action": "动作", "camera": "镜头", "reference": "参考素材", "sound": "声音"}
# Two rounds in one class with no improvement: the failure was filed under the wrong class.
STALL_ROUNDS = 2
# Where to look next when a class has been tried and did not help.
RECONSIDER_ORDER: dict[str, tuple[str, ...]] = {
    "action": ("camera", "reference"),
    "camera": ("action", "reference"),
    "reference": ("action", "camera"),
    "sound": ("action",),
}


@dataclass(frozen=True)
class Fix:
    """One concrete change, and the class of variable it touches."""

    variable: Variable
    text: str


def _fixes(variable: Variable, *texts: str) -> tuple[Fix, ...]:
    return tuple(Fix(variable, text) for text in texts)


@dataclass(frozen=True)
class Failure:
    """One way a generated shot goes wrong, and what to do about it."""

    id: str
    name: str
    triggers: tuple[str, ...]
    diagnosis: str
    # The class to change first; ``fixes`` may also hold fixes of other classes for later rounds.
    variable: Variable
    fixes: tuple[Fix, ...]
    # Knobs the shot workspace can actually turn.
    negatives: tuple[str, ...] = ()
    prevention: str = ""


FAILURES: tuple[Failure, ...] = (
    Failure(
        "face_collapse", "脸崩 / 换脸",
        ("脸崩", "崩脸", "脸糊", "脸歪", "变脸", "换脸", "五官", "不像", "face"),
        diagnosis="同框人数过多或人脸占比太小，模型分不清谁是谁。",
        variable="action",
        fixes=(
            *_fixes("action", "把第三个人降为虚化、背影或剪影，画面里只留两个清晰人物"),
            *_fixes("camera", "拆成两镜：一镜两人，一镜单人反应"),
            *_fixes("reference", "给这一镜挂上该角色的设定图作参考图，并重述外形锚点"),
        ),
        negatives=("面部畸形", "五官错位", "多张脸", "面部特征互换"),
        prevention="多人同框时每张脸都给足画面占比并挂设定图。",
    ),
    Failure(
        "hand_failure", "手部畸形",
        ("手", "手指", "六指", "多指", "指头", "hand", "finger"),
        diagnosis="手势超出模型稳定范围（结印、比心、捏取小物最容易出错）。",
        variable="action",
        fixes=(
            *_fixes("action", "把手势降级为安全档：握拳、摊掌、单手抬起、手扶道具", "把手移出画面或藏进袖口、口袋、背后"),
            *_fixes("camera", "手部特写改成中景，让手不占主体"),
        ),
        negatives=("多指", "少指", "手指融合", "手部畸形"),
        prevention="避免双手结印与捏取细小物件；手部特写优先改中景。",
    ),
    Failure(
        "occlusion", "特效糊脸",
        ("挡住", "遮住", "糊脸", "盖住脸", "特效挡", "光挡"),
        diagnosis="特效落在脸或关键道具上，被模型焊进了五官。",
        variable="action",
        fixes=(
            *_fixes("action", "把特效移到安全区：脚下地面、身后背景、掌心前方的另一景深层", "在提示词里写明「面部干净、轮廓清楚」"),
            *_fixes("camera", "前景遮挡控制在画面 5%-15% 并虚化 60% 以上"),
        ),
        negatives=("面部被遮挡", "符文覆盖面部"),
        prevention="特效不进人脸安全区；前景遮挡限制在画面边缘。",
    ),
    Failure(
        "action_blur", "动作糊成一团",
        ("糊", "看不清", "拖影", "动作乱", "模糊", "blur"),
        diagnosis="一镜里塞了多个动作，或运镜与动作同时高速。",
        variable="action",
        fixes=(
            *_fixes("action", "一镜只留一个主动作，其余动作挪到下一段"),
            *_fixes("camera", "按起手 → 碰撞 → 结果把这一镜拆成三镜", "一镜只留一个主运镜，放慢运镜速度，让动作读得清"),
        ),
        negatives=("动作拖影", "肢体残影"),
        prevention="多个动作写清先后；运镜与动作不同时冲到最快。",
    ),
    Failure(
        "colour_drift", "颜色漂移",
        ("颜色", "色偏", "变色", "衣服颜色", "色温", "colour", "color"),
        diagnosis="光影锁不完整，或两个角色的主色太接近。",
        variable="reference",
        fixes=(
            *_fixes("reference", "把色卡挂成参考图，并写明「严格按色卡执行，不可偏离色板」", "拉开两个角色的主色（色相至少差 90 度），设定图一并换新"),
            *_fixes("camera", "补全光影锁：时间、天气、主光方向、色温、光比"),
        ),
        negatives=("色彩漂移", "服装变色"),
        prevention="同场景各镜复用同一条光影锁；角色主色互相拉开。",
    ),
    Failure(
        "spatial_break", "站位跳了 / 左右互换 / 穿模",
        ("位置", "站位", "瞬移", "穿模", "穿墙", "穿透", "轴线", "越轴", "左右互换", "换边", "左右颠倒"),
        diagnosis="空间锁没有贯穿，或这一刀两侧的站位对不上。",
        variable="camera",
        fixes=(
            *_fixes("camera", "固定轴线与屏幕方向：切镜前记下谁在画左、谁在画右、各朝哪边", "回到空间调度里核对这一镜的站位与机位，重画本场"),
            *_fixes("action", "补上交接句：上一镜末帧的位置、姿态与道具归属；写明「物理实体、互不穿透」"),
        ),
        negatives=("肢体穿模", "道具穿透", "人物瞬移"),
        prevention="每一镜复述空间锚与状态锁；切点两侧位置首尾相接。",
    ),
    Failure(
        "style_drift", "画风跑了",
        ("画风", "风格", "变成动画", "变成3d", "不写实", "太卡通", "style"),
        diagnosis="风格锁没有进到这一镜，或被参考图的介质带跑了。",
        variable="reference",
        fixes=(
            *_fixes(
                "reference", "给跨介质参考图补反偷懒铁律（设定图、色卡、故事板、白模）", "确认项目风格锁，并把它逐字写进本镜提示词",
                "把风格负面词提到全局区块，不要只写在某一镜",
            ),
        ),
        negatives=("风格突变", "画风不一致"),
        prevention="风格锁逐字重述；参考图一律配反偷懒铁律。",
    ),
    Failure(
        "expression_failure", "表情僵 / 没情绪",
        ("表情", "面瘫", "没情绪", "呆", "僵", "expression"),
        diagnosis="只写了情绪结论，没有写可观察的肌肉动作。",
        variable="action",
        fixes=(
            *_fixes("action", "把情绪词换成五处微表情：眉心、下颌、瞳孔、眨眼节奏、指尖张力", "按情绪弧线校准强度档，别一上来就给满"),
            *_fixes("camera", "表情强度与景别匹配：微表情给近景以上"),
        ),
        negatives=("面部僵硬", "呆滞眼神"),
        prevention="情绪一律写成可观察的身体细节，不写结论词。",
    ),
    Failure(
        "lip_sync", "口型对不上",
        ("口型", "对不上", "嘴没动", "嘴型", "lip", "sync"),
        diagnosis="台词长度超出镜头时长，或旁白被当成了现场对白。",
        variable="sound",
        fixes=_fixes(
            "sound", "按语速换算重排：台词时长不超过镜头时长的七成", "旁白写明「画面人物嘴唇保持闭合」",
            "一镜只留一个人说话，其余人闭口给反应",
        ),
        negatives=("口型不同步", "多人同时说话"),
        prevention="台词按语速预算写；旁白标明闭口。",
    ),
    Failure(
        "audio_muddy", "声音糊在一起",
        ("声音", "听不清", "对白被盖", "音乐盖", "配乐", "环境音", "audio"),
        diagnosis="三层声音没有分开写，或环境音与配乐没有压低。",
        variable="sound",
        fixes=_fixes(
            "sound", "按 center / ambient / music 三层重写，对白层只留人声",
            "环境音加 low volume、配乐加 low frequency 或直接写 none",
            "环境音层补 surround 或 left-right spread，把声场拉开",
        ),
        negatives=("对白被环境音淹没",),
        prevention="声音永远写成三层，对白权重最高。",
    ),
    Failure(
        "wrong_speaker", "说话人错了 / 串台",
        ("说话人错", "说错人", "串台", "别人在说", "嘴在动的不是", "谁在说", "两个人都在说", "wrong speaker"),
        diagnosis="一镜里有不止一个可能开口的人，台词没有先点名说话人，或说话前没有一个能认出他的动作。",
        variable="sound",
        fixes=_fixes(
            "sound", "台词前先写说话人名字，再写「只有他说话，其他人闭口不出声」",
            "说话前先给说话人一个可见动作（抬眼、放下杯子、转身），台词落在动作之后",
            "仍然串台：一镜只留一个说话人，另一句台词拆到下一镜",
        ),
        negatives=("多人同时说话", "非说话人张嘴"),
        prevention="两人对话按听思答轮流开口：台词前点名说话人并先给他一个动作，同一时刻只有一人说话，其余人闭口给反应。",
    ),
    Failure(
        "sfx_timing", "音效早了 / 晚了",
        ("音效早", "音效晚", "音效提前", "音效滞后", "音效对不上", "声音提前", "声音滞后", "声画不同步", "sfx"),
        diagnosis="音效没有绑到画面里看得见的那一下，或一镜里动作太多，模型不知道声音该落在哪个动作上。",
        variable="sound",
        fixes=(
            *_fixes(
                "sound", "每个关键音效绑到一个可见事件：写成「某物碰到某处的瞬间：一声……」",
                "关键音效不超过两个，写明随后的动作不再重复这一声",
            ),
            *_fixes("action", "减少动作：一镜只留一个会出声的主动作，其余动作去掉或拆镜"),
        ),
        negatives=("音画不同步",),
        prevention="关键音效绑定可见事件、一镜不超过两个，会出声的动作越少越准。",
    ),
    # Fight symptoms: each names the class to look at first and the change to make there.
    Failure(
        "action_dwindle", "动作越打越少",
        ("动作变少", "动作减少", "动作自动减少", "越打越少", "只打了一下", "打一下就停", "后面不动了"),
        diagnosis="装饰描述挤占了动作，模型做完第一击就没有可演的了。",
        variable="action",
        fixes=_fixes("action", "删掉装饰性描述，只留关键动作与每一击的结果", "每一段写满一个主动作，结尾写清它把下一击引向哪里"),
        prevention="打戏正文只留关键动作与结果，装饰描述压到最少。",
    ),
    Failure(
        "contact_unclear", "接触点看不清",
        ("接触点", "没打到", "看不出打中", "打没打中", "接触不清", "命中不清"),
        diagnosis="景别或机位把接触藏住了：太远、太近或被身体挡住。",
        variable="camera",
        fixes=(
            *_fixes("camera", "改用侧向中景，让双方身体与接触点同时入画", "接触瞬间接一个短促的接触特写"),
            *_fixes("action", "写出接触点在画面里的位置，如「接触点位于画面正中偏上」"),
        ),
        prevention="接触前用看得见双方身体的景别；接触点给出画面位置。",
    ),
    Failure(
        "fight_disconnected", "双方各打各的",
        ("各打各的", "自己打自己", "对着空气", "没有互动", "打空气"),
        diagnosis="只写了各自的招式，没有写这一招落到对方身上之后发生什么。",
        variable="action",
        fixes=_fixes(
            "action", "每一回合补全：谁发起 → 打向哪里 → 接触 / 格挡 / 落空 → 对方怎么回应 → 双方位移 → 下一拍从哪里接",
            "两人间距写成可数的距离，并在每段重述谁在画左、谁在画右",
        ),
        prevention="每一回合都写成发起、接触、回应、位移与下一拍的完整链。",
    ),
    Failure(
        "jump_cut", "镜头乱切",
        ("跳切", "乱切", "自己切镜", "切来切去", "镜头乱跳", "莫名切换"),
        diagnosis="机位写得太多，或一次生成里塞进了超出时长的镜头数。",
        variable="camera",
        fixes=_fixes(
            "camera", "减少机位数量，每个镜头只承担一个职责（建立空间 / 追随位移 / 看清接触 / 揭示结果）",
            "按时长定镜头数：4–6 秒 1–2 个、7–10 秒 2–3 个、11–15 秒 3–5 个，正文写成连续描述",
        ),
        prevention="一次生成的镜头数按时长定，每镜一个职责。",
    ),
    Failure(
        "body_merge", "身体粘连",
        ("身体融合", "粘在一起", "连在一起", "长在一起", "合体", "融为一体"),
        diagnosis="首帧里两人的轮廓已经叠在一起，模型无从分开。",
        variable="reference",
        fixes=(
            *_fixes("reference", "换一张两人轮廓分离、肢体完整的首帧"),
            *_fixes("action", "双方之间至少留出半个身位，每段重述距离与朝向"),
        ),
        negatives=("肢体粘连",),
        prevention="首帧两人轮廓分开、肢体完整，间距至少半个身位。",
    ),
    Failure(
        "weapon_failure", "兵器复制 / 变形",
        ("武器", "兵器", "刀变", "剑变", "多出一把", "两把刀", "两把剑", "weapon"),
        diagnosis="兵器没有完整可见的参考，模型按常见印象自己补。",
        variable="reference",
        fixes=_fixes(
            "reference", "挂一张兵器完整可见的参考图", "写明兵器数量、长度、材质与握法（哪只手、正握还是反握）",
        ),
        negatives=("兵器变形",),
        prevention="兵器挂完整参考图，并写明数量、长度、材质与握法。",
    ),
    Failure(
        "weightless_hit", "打了没分量",
        ("没有力量", "没力量", "软绵绵", "没有打击感", "没打击感", "轻飘飘", "没重量"),
        diagnosis="只写了出招，没写接触之后身体和环境怎么受力。",
        variable="action",
        fixes=_fixes(
            "action", "写清接触部位、受力方向、被推开的位移和材质反馈（布料凹陷、木屑、尘土）",
            "接触不停：写到继续推进、滑开或擦过，再转入下一动作",
        ),
        prevention="重要命中写清接触部位、受力方向、位移与材质反馈。",
    ),
    Failure(
        "damage_reset", "伤痕自己复原",
        ("伤口消失", "血迹消失", "伤没了", "恢复原样", "复原", "裂痕消失", "损伤消失"),
        diagnosis="损伤只在出现的那一段写过，后面的段落没有再提。",
        variable="action",
        fixes=_fixes("action", "在后面每一段都重述损伤状态：位置、大小、颜色", "场景损伤（裂地、断木）同样逐段照写"),
        prevention="伤痕与场景损伤出现后逐段重述。",
    ),
    Failure(
        "endframe_warp", "首尾帧过渡扭曲",
        ("首尾帧", "过渡扭曲", "扭曲", "过渡变形", "中间融化"),
        diagnosis="首帧与尾帧的姿势、机位差得太远，模型只能硬插值。",
        variable="reference",
        fixes=_fixes("reference", "缩小首帧与尾帧之间的姿势和机位差异", "差异实在大时插一个中间落点帧，分两段生成"),
        prevention="首尾帧的姿势与机位差异控制在一个动作能走完的范围内。",
    ),
    Failure(
        "vfx_unsourced", "特效没有来源",
        ("凭空出现", "特效凭空", "光效乱飞", "特效没来源", "莫名的光"),
        diagnosis="特效没有绑定到兵器、法器或接触点，模型随处撒光。",
        variable="action",
        fixes=_fixes("action", "把特效绑定到兵器、法器或接触点上，写清从哪里发出、打到哪里", "绑不上来源的特效直接删掉"),
        prevention="每道特效都写清来源与落点。",
    ),
)
_BY_ID = {failure.id: failure for failure in FAILURES}

# What a class gives up when a shot keeps failing in it, in this order.
ESCALATION: dict[str, tuple[str, ...]] = {
    "action": (
        "简化动作：安全手势、一镜一个主动作",
        "削减装饰与特效：只留关键动作与结果，特效系统降到一套、光层不超过四层且总覆盖不超过四成",
        "减少人物：三人降两人，多余角色转虚化或背影",
    ),
    "camera": (
        "减少机位：每个镜头只承担一个职责",
        "拆分镜头：把这一镜按起手 / 碰撞 / 结果拆开",
        "更换景别：特写改中景，失败的大场面改远景或剪影",
    ),
    "reference": (
        "更换首帧：轮廓分离、肢体完整、兵器完整可见",
        "缩小首尾帧的姿势与机位差异，必要时加一个中间落点",
        "参考素材各管一件事：角色、场景、动作、镜头分开挂",
    ),
    "sound": (
        "收紧说话人：一镜只留一个说话人，台词前点名，说话前先给一个可见动作",
        "声音拆成三层重写，对白层只留人声；关键音效只绑一到两个可见事件，环境音与配乐降到 low volume 或直接写 none",
        "对白移到后期配音：本镜视频不再生成对白，台词由 TTS 配好后按口型合入",
    ),
}


def _walk(primary: str, rounds: Sequence[tuple[str, bool]]) -> tuple[str | None, int, list[str]]:
    """Which class this round changes, how many rounds that class already had, and which were dropped.

    ``rounds`` are the earlier retries, oldest first: the class each one changed and whether the
    result after it improved. A round in another class (a change made by hand) does not count.
    """
    order = [primary, *RECONSIDER_ORDER.get(primary, ())]
    index, spent, stalled, dropped = 0, 0, 0, []
    for variable, improved in rounds:
        if index >= len(order) or variable != order[index]:
            continue
        spent += 1
        stalled = 0 if improved else stalled + 1
        if stalled >= STALL_ROUNDS:
            dropped.append(order[index])
            index, spent, stalled = index + 1, 0, 0
    return (order[index] if index < len(order) else None), spent, dropped


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
    # The one class of variable this round changes; empty once every class has been tried.
    variable: str = ""
    # Classes already tried for two rounds without improvement, oldest first.
    reconsidered: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "category": self.primary.id, "category_name": self.primary.name,
            "diagnosis": self.primary.diagnosis,
            "secondary": [item.id for item in self.secondary],
            "attempt": self.attempt, "steps": list(self.steps),
            "negatives": list(self.negatives), "escalation": self.escalation,
            "give_up": self.give_up,
            "variable": self.variable, "variable_name": VARIABLE_NAMES.get(self.variable, ""),
            "reconsidered": list(self.reconsidered),
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


def plan_fix(
    text: str = "", *, category: str = "", attempt: int = 1, rounds: Sequence[tuple[str, bool]] | None = None,
) -> FixPlan | None:
    """The fix for this report; ``None`` when nothing in it names a known failure.

    ``rounds`` are the earlier retries on this shot (class changed, improved afterwards); without
    them every earlier retry is taken to have followed the plan and not helped.
    """
    matches = classify(text)
    chosen = get_failure(category) or (matches[0].failure if matches else None)
    if chosen is None:
        return None
    secondary = [match.failure for match in matches if match.failure.id != chosen.id][:2]
    attempt = max(1, int(attempt or 1))
    if rounds is None:
        rounds = []
        for _ in range(attempt - 1):
            variable, _, _ = _walk(chosen.variable, rounds)
            if variable is None:
                break
            rounds.append((variable, False))
    variable, spent, dropped = _walk(chosen.variable, rounds)
    steps: list[str] = []
    escalation = ""
    give_up = variable is None
    if give_up:
        tried = "、".join(VARIABLE_NAMES[item] for item in dropped)
        if chosen.variable == "sound":
            # 声音修不好就不再让视频模型出声：画面照拍，对白与音效全部后期合成。
            steps.append(f"{tried}各改了 {STALL_ROUNDS} 轮都没有改善：对白移到后期配音，本镜视频只出画面与环境声，台词由 TTS 配好后按口型合入")
        else:
            steps.append(f"{tried}各改了 {STALL_ROUNDS} 轮都没有改善，已到模型能力边界：换等价表达（剪影打斗、道具发光代替结印）或换一个视频模型")
    else:
        if dropped:
            steps.append(
                f"连续 {STALL_ROUNDS} 轮只改{VARIABLE_NAMES[dropped[-1]]}都没有改善，可能分错了变量：本轮改查{VARIABLE_NAMES[variable]}"
            )
        steps.extend(fix.text for fix in chosen.fixes if fix.variable == variable)
        # The first round in the failure's own class is the fix itself; every later round, and the
        # first round in a class turned to after a stall, gives something up in that class.
        ladder = ESCALATION[variable]
        rung = spent - 1 if variable == chosen.variable else spent
        if rung >= 0:
            escalation = ladder[min(rung, len(ladder) - 1)]
            steps.append(f"第{attempt}次重试，按退让顺序执行：{escalation}")
        others = "、".join(name for key, name in VARIABLE_NAMES.items() if key != variable and key != "sound")
        steps.append(f"本轮只改{VARIABLE_NAMES[variable]}，{others}保持不变，生成后再判断下一步")
    return FixPlan(
        primary=chosen, secondary=secondary, attempt=attempt, steps=steps,
        negatives=list(dict.fromkeys([*chosen.negatives, *(term for item in secondary for term in item.negatives)])),
        escalation=escalation, give_up=give_up, variable=variable or "", reconsidered=dropped,
    )


_RESULT_RANK = {"failed": 0, "partial": 1, "success": 2}


def _rounds(history: Sequence[Mapping[str, Any]], result: str) -> list[tuple[str, bool]]:
    """Earlier retries on one shot: the class each plan changed, and whether the next report was better."""
    entries = [entry for entry in history if entry.get("result") != "success"]
    rounds: list[tuple[str, bool]] = []
    for index, entry in enumerate(entries):
        variable = str(entry.get("variable") or "")
        if not variable:
            # Ledgers written before the variable classes: the category's own class.
            failure = get_failure(str(entry.get("category") or ""))
            variable = failure.variable if failure else ""
        if not variable:
            continue
        after = entries[index + 1].get("result") if index + 1 < len(entries) else result
        rounds.append((variable, _RESULT_RANK.get(str(after), 0) > _RESULT_RANK.get(str(entry.get("result")), 0)))
    return rounds


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

    plan = (
        plan_fix(text, category=category, attempt=attempt, rounds=_rounds(history, result))
        if result != "success" else None
    )
    entry = {
        "result": result, "text": str(text or "")[:500], "model": str(model or ""),
        "category": plan.primary.id if plan else "", "attempt": attempt,
        "variable": plan.variable if plan else "",
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
            "diagnosis": failure.diagnosis, "variable": failure.variable,
            "fixes": [fix.text for fix in failure.fixes],
            "fix_variables": [fix.variable for fix in failure.fixes],
            "negatives": list(failure.negatives),
        }
        for failure in FAILURES
    ]


__all__ = [
    "ESCALATION", "FAILURES", "LEDGER_KEY", "PROMOTE_AFTER", "RECONSIDER_ORDER", "STALL_ROUNDS", "VARIABLE_NAMES",
    "Failure", "FailureMatch", "Fix", "FixPlan", "classify", "describe", "get_failure", "plan_fix", "preventive_negatives", "preventive_notes",
    "record", "summary", "weaknesses",
]
