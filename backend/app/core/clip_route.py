# -*- coding: utf-8 -*-
"""第 5 阶段每一段视频怎么出：首尾帧、接上一镜、还是多模态参考。规则先于模型判定。

一部戏按场次出片，同一场里一段接一段。哪段用哪种方式，有几条硬规则，按优先级：

1. **一镜式长镜头段内只能首尾帧。** 一个分镜片段太长被切成几段时，后一段的首帧就是前一段的尾帧；
   换别的方式尾帧固定不了，整段接不上。模型没有首尾帧，或这一段只有一张分镜(尾帧没处取)，
   不降级，直接报错，让出品人换模型或把这一镜移出段。
2. **同场连续出片，第 2 段起接上一镜。** 缺省 ``tailframe``：上一段成片的最后一帧当本段首帧，本段不挂定妆照
   和场景图，人物长相靠首帧里的人和文字外貌描述。上一段没出场的新角色进场(或这一镜有主角道具)时改成
   ``tailref``：上一段尾帧当参考图 1，再挂定妆照(多模态参考)。被审核拦下时依次退：
   首帧接力 → 尾帧当参考图 → 延长上一镜视频 → 再试一次延长 → 独立出。
3. **一场戏只有这一段：多模态参考。** 有参考图就直接定，不再问文本模型。
4. **出品人附了参考视频或参考音频：只能多模态参考。** 视频模型收不下就报错，不悄悄丢掉素材。
真人演员在 Seedance 上(``frameless``)：一律多模态参考、不带任何画面帧，长镜头段内做不到首尾帧就报错，
下一段也不接它的尾帧。

5. **主角道具镜头：多模态参考。** 道具母版图只有在多模态参考里才能送到视频模型；这一段又必须首尾帧时首尾帧优先。
6. **只有 1 张分镜时：** 有主体参考就走多模态参考(分镜排第一，写明图 1 是开场画面)；没有就把它当首帧起步。

其余的段不归规则管，照旧交给模型判定与素材规则(``video_mode_judge`` / ``video_references``)。

本模块只做决定，不碰任何供应商；第 5 阶段按 ``ClipRoute`` 组请求。
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable, Sequence
from dataclasses import dataclass

FIRST_LAST = "first_last"       # 首尾帧(长镜头段内)
TAILFRAME = "tailframe"         # 上一段尾帧当本段首帧
TAILREF = "tailref"             # 上一段尾帧当参考图 1 + 定妆照
REFERENCE = "reference"         # 多模态参考：分镜在前，主体参考在后
FIRST_FRAME = "first_frame"     # 唯一一张分镜当首帧起步

EXTEND = "extend"               # 回退步：延长上一段视频
INDEPENDENT = "independent"     # 回退步：不再接上一段，按本段自己的分镜与参考出

KINDS = (FIRST_LAST, TAILFRAME, TAILREF, REFERENCE, FIRST_FRAME)
_REFERENCE_MODES = frozenset({"multi_reference", "multimodal"})


@dataclass(frozen=True)
class ClipFacts:
    """一段视频在路由前就知道的事。``key`` 是第 5 阶段的请求编号(或判定前的分组编号)。"""

    key: Hashable
    scene_id: str
    part: int = 1                       # 分镜片段被切开时：第几段 / 共几段
    parts: int = 1
    characters: tuple[str, ...] = ()
    storyboards: int = 0                # 这一段带的分镜画面张数
    attached_media: bool = False        # 出品人附了参考视频或参考音频
    hero_prop: bool = False             # 绑定了主角道具的母版图
    subject_refs: bool = False          # 有定妆照 / 场景图 / 道具图这类主体参考
    # 真人演员在 Seedance 上：任何画着他真人脸的图(分镜帧、抽出的尾帧、定妆图)都会被拒，只能带真人素材走多模态参考。
    frameless: bool = False


@dataclass(frozen=True)
class ClipRoute:
    kind: str | None                    # None：不归规则管，照旧模型判定
    rule: str = ""
    reason: str = ""
    chain_from: Hashable | None = None  # 接哪一段的尾帧
    error: str = ""                     # 非空：这一段不能出，原因原样给出品人
    fallbacks: tuple[str, ...] = ()     # 被审核拦下时依次尝试的接法
    attached_media: bool = False

    @property
    def decided(self) -> bool:
        return self.kind is not None or bool(self.error)

    def provider_mode(self) -> str | None:
        """交给 ``video_references.plan_video_references`` 的模式。"""
        return provider_mode(self.kind, self.attached_media)

    def as_dict(self) -> dict:
        return {
            "kind": self.kind, "rule": self.rule, "reason": self.reason, "error": self.error,
            "chain_from": self.chain_from, "fallbacks": list(self.fallbacks), "attached_media": self.attached_media,
        }


def provider_mode(kind: str | None, attached_media: bool = False) -> str | None:
    if kind == FIRST_LAST:
        return "first_last_frame"
    if kind in (TAILFRAME, FIRST_FRAME):
        return "first_frame"
    if kind in (TAILREF, REFERENCE):
        return "multimodal" if attached_media else "multi_reference"
    return None


def _scene_runs(clips: Sequence[ClipFacts]) -> list[list[ClipFacts]]:
    """同一场连续出片的几段：相邻且场次相同的归一组。场次为空的段各自成组。"""
    runs: list[list[ClipFacts]] = []
    for clip in clips:
        if runs and clip.scene_id and runs[-1][-1].scene_id == clip.scene_id:
            runs[-1].append(clip)
        else:
            runs.append([clip])
    return runs


def route_clips(
    clips: Sequence[ClipFacts],
    modes: Iterable[str],
    *,
    scene_chain: bool = True,
    can_extend: bool = False,
) -> dict[Hashable, ClipRoute]:
    """按上面六条规则给每段定接法。``modes`` 是所选视频模型能执行的模式；``scene_chain`` 关掉第 2 条。"""
    modes = frozenset(modes)
    references = bool(modes & _REFERENCE_MODES)
    routes: dict[Hashable, ClipRoute] = {}
    for run in _scene_runs(clips):
        for index, clip in enumerate(run):
            previous = run[index - 1] if index else None
            routes[clip.key] = _route(clip, previous, solo=len(run) == 1, modes=modes, references=references,
                                      scene_chain=scene_chain, can_extend=can_extend)
    return routes


def _chain_fallbacks(start: str, *, references: bool, can_extend: bool) -> tuple[str, ...]:
    """被审核拦下时从 ``start`` 之后依次退；模型做不到的步跳过，最后总能独立出。"""
    steps = [TAILFRAME, TAILREF, EXTEND, EXTEND, INDEPENDENT]
    after = steps[steps.index(start) + 1:]
    return tuple(step for step in after if (step != TAILREF or references) and (step != EXTEND or can_extend))


def _route(
    clip: ClipFacts, previous: ClipFacts | None, *, solo: bool, modes: frozenset[str], references: bool,
    scene_chain: bool, can_extend: bool,
) -> ClipRoute:
    # 上一段画着真人脸时它的尾帧送不出去，本段从自己开头起。
    chain = previous.key if previous is not None and scene_chain and not previous.frameless else None

    # 真人演员(Seedance)：不能带任何画面帧，长镜头段做不到首尾帧就报错，其余一律多模态参考、不接尾帧。
    if clip.frameless:
        if clip.parts > 1:
            return ClipRoute(None, "real_person", error=(
                f"长镜头段第 {clip.part}/{clip.parts} 段只能用首尾帧，但真人演员在所选模型上不能带画面帧；"
                "请把这一镜移出长镜头段，或换模型"
            ))
        if not references:
            return ClipRoute(None, "real_person", error="真人演员只能带真人素材走多模态参考，所选视频模型不支持多模态参考")
        return ClipRoute(REFERENCE, "real_person", "真人演员：只带真人素材与场地参考走多模态参考，不接尾帧、不带分镜帧",
                         attached_media=clip.attached_media and "multimodal" in modes)

    # 1. 一镜式长镜头段内：只能首尾帧，做不到就报错。
    if clip.parts > 1:
        where = f"长镜头段第 {clip.part}/{clip.parts} 段"
        if clip.attached_media:
            return ClipRoute(None, "long_take", error=(
                f"{where}只能用首尾帧接住前后段，附的参考视频 / 参考音频送不进去；"
                "请去掉参考素材，或把这一镜移出长镜头段"
            ))
        if "first_last_frame" not in modes:
            return ClipRoute(None, "long_take", error=(
                f"{where}只能用首尾帧，所选视频模型不支持首尾帧；请换支持首尾帧的模型，或把这一镜移出长镜头段"
            ))
        if clip.storyboards < 2:
            return ClipRoute(None, "long_take", error=(
                f"{where}只有一张分镜，尾帧固定不了；请补一张落幅分镜、换单段更长的模型，或把这一镜移出长镜头段"
            ))
        # 段内第 2 段起首帧就是前一段尾帧；第 1 段在同场接着上一镜时也从上一镜尾帧开场。
        return ClipRoute(FIRST_LAST, "long_take", f"{where}：首帧接前一段尾帧、尾帧落在本段最后一张分镜", chain_from=chain)

    # 4. 出品人附的参考视频 / 音频：只能多模态参考，收不下就报错。
    if clip.attached_media:
        if "multimodal" not in modes:
            return ClipRoute(None, "attached_media", error=(
                "出品人附了参考视频或参考音频，只能用多模态参考，所选视频模型收不下；请换支持多模态参考的模型或去掉参考素材"
            ))
        if chain is not None:
            return ClipRoute(TAILREF, "attached_media", "附了参考音视频：上一镜尾帧当参考图 1，连同参考素材走多模态参考",
                             chain_from=chain, attached_media=True,
                             fallbacks=_chain_fallbacks(TAILREF, references=True, can_extend=can_extend))
        return ClipRoute(REFERENCE, "attached_media", "附了参考音视频：只能多模态参考", attached_media=True)

    # 2. 同场连续出片，第 2 段起：接上一镜。
    if chain is not None:
        entering = [name for name in clip.characters if name not in set(previous.characters)] if previous else []
        if (entering or clip.hero_prop) and references:
            why = f"新角色进场（{'、'.join(entering)}）" if entering else "主角道具镜头"
            return ClipRoute(TAILREF, "scene_chain", f"{why}：上一镜尾帧当参考图 1，并挂定妆照", chain_from=chain,
                             fallbacks=_chain_fallbacks(TAILREF, references=True, can_extend=can_extend))
        return ClipRoute(TAILFRAME, "scene_chain", "同场接上一镜：上一镜最后一帧当本镜首帧，不挂定妆照和场景图", chain_from=chain,
                         fallbacks=_chain_fallbacks(TAILFRAME, references=references, can_extend=can_extend))

    # 3. 一场戏只有这一段：有参考图就直接定多模态参考。
    if solo and references and (clip.subject_refs or clip.storyboards >= 2):
        return ClipRoute(REFERENCE, "solo_scene", "一场戏只有这一镜：多模态参考，分镜在前")

    # 5. 主角道具镜头：道具母版图只能经多模态参考送到模型。
    if clip.hero_prop and references:
        return ClipRoute(REFERENCE, "hero_prop", "主角道具镜头：道具母版图经多模态参考送到模型")

    # 6. 只有一张分镜。
    if clip.storyboards == 1:
        if clip.subject_refs and references:
            return ClipRoute(REFERENCE, "single_storyboard", "只有一张分镜：多模态参考，分镜排第一，图 1 是开场画面")
        return ClipRoute(FIRST_FRAME, "single_storyboard", "只有一张分镜、没有主体参考：把它当首帧起步")

    return ClipRoute(None)


def undecided_keys(routes: dict[Hashable, ClipRoute]) -> set[Hashable]:
    """还要交给文本模型判定的段。"""
    return {key for key, route in routes.items() if not route.decided}


__all__ = [
    "EXTEND", "FIRST_FRAME", "FIRST_LAST", "INDEPENDENT", "KINDS", "REFERENCE", "TAILFRAME", "TAILREF",
    "ClipFacts", "ClipRoute", "provider_mode", "route_clips", "undecided_keys",
]
