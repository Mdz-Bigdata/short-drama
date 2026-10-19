# -*- coding: utf-8 -*-
"""Prompt builders for the screenwriting pipeline.

Principles (kept from the reference design, wording is this project's own):
- Do not repeat what the JSON schema already enforces; explain how to write each
  field well instead, with a positive example and an annotated counter-example.
- Pacing rules come from one shared reference so every stage speaks the same
  rhythm; user instructions are appended as a neutral section whose strength is
  expressed by the instruction text itself.
- Dynamic text (source, asset names) has its angle brackets neutralised so it can
  never break the tagged prompt structure.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from collections.abc import Mapping, Sequence
from typing import Any

from app.core.episode_shape import EpisodeShape
from app.core.fight_design import plan_rules_for, visual_rules_for
from app.core.screenwriting.durations import render_episode_target_rule
from app.core.screenwriting.pacing import render_pacing_section
from app.core.screenwriting.speech_rate import speech_rate_units_per_second
from app.core.screenwriting.text_metrics import reading_unit_noun

USER_INSTRUCTIONS_HEADER = "# 附加指令"

SourceKind = str  # "outline" | "novel" | "screenplay"


# The language the audience-facing text is written in (titles, hooks, lines, narration, prose,
# visual descriptions). The engine sets it for the duration of a call; JSON keys stay English.
OUTPUT_LANGUAGES = {"zh": "中文", "en": "英语（English）", "vi": "越南语（Tiếng Việt）"}
_OUTPUT_LANGUAGE: ContextVar[str] = ContextVar("screenwriting_output_language", default="zh")


def output_language() -> str:
    return _OUTPUT_LANGUAGE.get()


def output_language_name() -> str:
    return OUTPUT_LANGUAGES.get(_OUTPUT_LANGUAGE.get(), OUTPUT_LANGUAGES["zh"])


@contextmanager
def language_scope(code: str | None) -> Iterator[None]:
    """Write everything built inside the block in ``code`` (zh / en / vi; anything else is zh)."""
    token = _OUTPUT_LANGUAGE.set(code if code in OUTPUT_LANGUAGES else "zh")
    try:
        yield
    finally:
        _OUTPUT_LANGUAGE.reset(token)


def append_user_instructions(prompt: str, instructions: str | None) -> str:
    if not instructions or not instructions.strip():
        return prompt
    return f"{prompt.rstrip()}\n\n{USER_INSTRUCTIONS_HEADER}\n{instructions.strip()}"


def neutralize_tags(value: object) -> str:
    return str(value or "").replace("<", "＜").replace(">", "＞")


def _names(mapping: Mapping[str, Any] | None) -> list[str]:
    return [str(name) for name in (mapping or {}).keys() if str(name).strip()]


def _format_name_list(mapping: Mapping[str, Any] | None) -> str:
    names = _names(mapping)
    return "\n".join(f"- {neutralize_tags(name)}" for name in names) if names else "（暂无）"


def _format_assets_with_desc(mapping: Mapping[str, Any] | None) -> str:
    lines: list[str] = []
    for name, entry in (mapping or {}).items():
        description = ""
        if isinstance(entry, Mapping):
            description = str(entry.get("description") or "").strip()
        safe = neutralize_tags(name)
        if description:
            lines.append(f"- {safe}：{neutralize_tags(description).replace(chr(10), chr(10) + '  ')}")
        else:
            lines.append(f"- {safe}")
    return "\n".join(lines) if lines else "（暂无）"


def _overview_block(overview: Mapping[str, Any] | None) -> str:
    overview = overview or {}
    return (
        "<overview>\n"
        f"{neutralize_tags(overview.get('synopsis', ''))}\n\n"
        f"题材：{neutralize_tags(overview.get('genre', ''))}\n"
        f"主题：{neutralize_tags(overview.get('theme', ''))}\n"
        f"世界观：{neutralize_tags(overview.get('world_setting', ''))}\n"
        "</overview>"
    )


OMITTED_MARK = "……（此处省略 {count} 字）……"


def sample_source(text: str, budget: int) -> str:
    """``text`` cut down to about ``budget`` characters for the one-shot analysis stages.

    A whole novel does not fit a prompt; the overview and the asset inventory read
    its opening (where the world and the cast are set up), evenly spaced middle
    excerpts, and its ending, each cut on a paragraph boundary and separated by a
    mark that says how much was skipped. Short texts are returned untouched.
    """
    text = str(text or "")
    budget = max(1000, int(budget))
    if len(text) <= budget:
        return text
    head_len = int(budget * 0.45)
    tail_len = int(budget * 0.2)
    middle_total = budget - head_len - tail_len
    slices = 3
    slice_len = middle_total // slices
    middle_span = len(text) - head_len - tail_len
    cuts: list[tuple[int, int]] = [(0, head_len)]
    for index in range(slices):
        start = head_len + (middle_span * (index + 1)) // (slices + 1) - slice_len // 2
        cuts.append((start, start + slice_len))
    cuts.append((len(text) - tail_len, len(text)))

    def _snap(start: int, end: int) -> tuple[int, int]:
        # Open on a paragraph and close on one, inside the slice, when the slice has them.
        opening = text.rfind("\n", start, end)
        if start > 0 and opening != -1 and opening - start < slice_len // 3:
            start = opening + 1
        closing = text.rfind("\n", start, end)
        if end < len(text) and closing != -1 and end - closing < slice_len // 3:
            end = closing
        return start, end

    parts: list[str] = []
    previous_end = 0
    for start, end in cuts:
        start, end = _snap(max(start, previous_end), min(end, len(text)))
        if start >= end:
            continue
        if start > previous_end:
            parts.append(OMITTED_MARK.format(count=start - previous_end))
        parts.append(text[start:end].strip("\n"))
        previous_end = end
    return "\n\n".join(parts)


def _aspect_desc(aspect_ratio: str) -> str:
    return {"9:16": "竖屏构图", "16:9": "横屏构图"}.get(aspect_ratio, f"{aspect_ratio} 构图")


# --------------------------------------------------------------------------- overview


def build_overview_prompt(source_content: str, *, source_kind: SourceKind, title_hint: str = "") -> str:
    if source_kind == "screenplay":
        task = (
            "请分析以下成品剧本，提炼项目概述（作品名 / 题材 / 一句话主题 / 故事梗概 / 世界观）。"
            "作者若在剧本里写下了创作方案（前言、大纲、设定卡等任意形态），优先照用作者的设定填充字段，"
            "忠于原意、可精炼归并、不另起炉灶；没有创作方案时再从正文归纳。"
        )
        heading, tag = "剧本原文", "screenplay"
    elif source_kind == "novel":
        task = "请分析以下小说内容，提炼项目概述（作品名 / 题材 / 一句话主题 / 故事梗概 / 世界观）。"
        heading, tag = "小说原文", "novel"
    else:
        task = (
            "请根据以下总导演策划方案提炼项目概述（作品名 / 题材 / 一句话主题 / 故事梗概 / 世界观）。"
            "作品名必须是片名本身，不要把「请帮我写一个……」这类创作指令当成片名。"
        )
        heading, tag = "导演策划方案", "director_plan"
    hint = f"\n用户给出的选题提示：{neutralize_tags(title_hint)}\n" if title_hint else ""
    return (
        f"{task}\n{hint}\n**输出语言**：所有字符串值使用{output_language_name()}；JSON 键名保持英文。\n\n"
        f"## {heading}\n\n<{tag}>\n{neutralize_tags(source_content)}\n</{tag}>"
    )


# --------------------------------------------------------------------------- asset inventory


_ASSET_RULES_NOVEL = (
    "- 角色：识别在文本中有实质出场的具名角色；description 只写视觉信息（五官与身材要点、服装款式颜色材质、"
    "标志物、主色调、参考风格），不写性格、关系与剧情；voice_style 记录声音/语气；position 填戏剧位置。\n"
    "- 泛指 / 群演 / 空镜（老人甲、村民若干、一群孩子、无人物空场）不登记为角色。\n"
    "- 场景：提取重复出现或有视觉特征的环境地点；description 只写环境本身（空间结构、氛围、光线、色调），"
    "不写人物和情节。\n"
    "- 道具：提取重复出现或有视觉特征的物品；description 写外观细节、材质、尺寸参考、色彩。\n"
    "- 角色总数控制在 4-6 人以内，角色之间服装颜色要形成对比、发型要有明显区别。\n"
    "- 服装（costumes）：每位登记角色至少一套主造型，剧情里换装（大婚喜服、囚衣、战甲、夜行衣）就另登记一套；"
    "名称写「角色名·造型名」，如「沈知微·素白医官袍」；character 填穿着者；description 写款式、颜色、材质、"
    "配饰（发饰、腰带、鞋履）和在哪段剧情穿，与该角色 description 里的服装一致。\n"
    "- 特效（effects）：提取需要合成或现场效果配合的视觉现象，如暴雨雨幕、大雪、浓雾、火焰烟尘、爆炸破碎、"
    "血迹飞溅、法术光效、符咒剑气、超自然现象、全息屏幕；名称写具体，如「九霄殿金色神光」；description 写视觉形态、"
    "颜色、运动方式和触发时机。普通布光、景别、运镜不算特效；文本里没有就留空。"
)
_ASSET_RULES_SCREENPLAY = (
    "- 这是作者写好的成品剧本，角色由作者定义：只提取作者写下的具名角色（人物表、括注简介、对白前缀里反复出现的固定人名），"
    "不要从情节推断新角色。\n"
    "- description 照用作者写下的视觉描述，不补写、不润色；作者只给了名字没给外形的角色，description 写「需补充外貌与服装细节」。\n"
    "- 泛指 / 群演 / 空镜（老人甲、村民若干、一群孩子、无人物空场）不登记为角色。\n"
    "- 场景与道具同样只提取作者明确写出的地点与物品，description 只写视觉信息。\n"
    "- 服装（costumes）：每位登记角色登记作者写下的造型，换装另登记一套；作者没写服装的角色，按时代与身份登记一套主造型，"
    "description 末尾注明「（按身份推定）」；名称写「角色名·造型名」，character 填穿着者。\n"
    "- 特效（effects）：只提取作者写出的、需要合成或现场效果配合的视觉现象（天气、火焰烟尘、爆炸破碎、血迹、法术光效等）；"
    "名称写具体，description 写视觉形态、颜色、运动方式和触发时机；没有就留空。"
)


_RELATION_RULES = (
    "- 关系（relationships）：为登记的角色两两写出文本里真实成立的关系，from / to 必须与 characters 里的名字逐字一致；"
    "relation 用 2–6 字说清楚两人是什么关系，从常规关系里选最贴切的，如 君臣、父子、母子、父女、母女、夫妻、兄弟、兄妹、姐弟、姐妹、主仆、师徒、亦师亦友、惺惺相惜、宿敌、敌对、背叛、暗恋、青梅竹马、结义兄弟、先祖与后裔、祭司辅佐首领、托孤之臣、辅政大臣、效忠、利用、追杀、救命恩人；"
    "同一对人有多重关系时写最主要的一种。"
    "关系对等（夫妻、兄妹、宿敌、惺惺相惜）bidirectional 为 true；有方向（暗恋、效忠、追杀、利用）为 false，from 指向发起方。"
    "禁止写「同场互动」「共同出场」「有关联」这类空话；主角与每个主要角色都要有关系，最多 40 条。"
)


def build_asset_inventory_prompt(
    source_content: str,
    *,
    source_kind: SourceKind,
    overview: Mapping[str, Any] | None,
    existing: Mapping[str, Sequence[str]] | None = None,
) -> str:
    rules = _ASSET_RULES_SCREENPLAY if source_kind == "screenplay" else _ASSET_RULES_NOVEL
    heading = {"screenplay": "剧本原文", "novel": "小说原文"}.get(source_kind, "导演策划方案")
    existing_block = ""
    if existing:
        parts = []
        for key, label in (("characters", "角色"), ("scenes", "场景"), ("props", "道具"), ("costumes", "服装"), ("effects", "特效")):
            names = list(existing.get(key) or [])
            if names:
                parts.append(f"- 已登记{label}：{'、'.join(neutralize_tags(name) for name in names)}")
        if parts:
            existing_block = "\n\n# 已登记资产（沿用其名称，不要重复登记、不要改名）\n" + "\n".join(parts)
    return (
        "你是一位角色与世界观分析师，负责从文本中提取可用于 AI 视频生成的角色 / 场景 / 道具 / 服装 / 特效五类资产，以及角色之间的关系。\n\n"
        f"{_overview_block(overview)}\n\n"
        f"# 提取规则\n{rules}\n{_RELATION_RULES}{existing_block}\n\n"
        f"## {heading}\n\n<source>\n{neutralize_tags(source_content)}\n</source>"
    )


# --------------------------------------------------------------------------- episode planning


def _target_volume_line(volume) -> str:
    if volume is None:
        return "- 每集目标体量：未设置，请按短视频节奏自行把握（以剧情弧完整优先）"
    if volume.source == "duration":
        return (
            f"- 每集目标体量：约 {volume.units} {volume.unit_noun}（按单集目标时长 {volume.seconds} 秒、"
            f"口播语速约 {volume.units_per_second:g} {volume.unit_noun}/秒粗略折算，允许为剧情完整性上下浮动）"
        )
    if volume.source == "episode_count":
        return f"- 每集目标体量：约 {volume.units} {volume.unit_noun}（按全剧集数平均折算，允许为剧情完整性上下浮动）"
    return f"- 每集目标体量：约 {volume.units} {volume.unit_noun}（允许为剧情完整性上下浮动）"


def _context_lines(context_entries: Sequence[Mapping[str, Any]]) -> list[str]:
    lines: list[str] = []
    if context_entries:
        lines += ["", "# 已规划的前情（已定上下文，不可改动，续着它往下规划）"]
        for entry in context_entries:
            lines.append(
                f"- 第 {entry.get('episode')} 集《{neutralize_tags(entry.get('title') or '（无标题）')}》 "
                f"钩子：{neutralize_tags(entry.get('hook') or '')}"
            )
    return lines


def build_anchored_plan_prompt(
    *,
    window: str,
    window_is_final: bool,
    overview: Mapping[str, Any] | None,
    source_kind: SourceKind,
    context_entries: Sequence[Mapping[str, Any]],
    target_volume,
    max_episodes: int,
    remaining_episodes: int | None,
    instructions: str | None,
) -> str:
    """Split a source window into episodes anchored on verbatim ``end_anchor`` snippets."""
    is_screenplay = source_kind == "screenplay"
    overview = overview or {}
    lines: list[str] = []
    if is_screenplay:
        lines += [
            "你是短剧分集规划师。下面是作者已写好的成品剧本片段，请尊重作者自带的分集、提取而非重切：",
            "- 剧本自带分集（任意形态：分集标记、结构表、标题体系、分隔符）时，照用作者划定的每一集边界，标题、钩子与大纲取自剧本原文。",
            "- 剧本没有任何分集线索时，再按完整剧情弧切分，每一集都是一个完整的故事段落，绝不按字数机械切碎。",
        ]
    else:
        lines += [
            "你是短剧分集规划师。请把下面的原文片段切分为若干集，每一集都必须是一个完整的剧情弧，",
            "并在集尾留下让观众想看下一集的钩子。",
        ]
    lines += ["", "# 项目信息", "- 创作类型：剧情演绎短剧"]
    if overview.get("synopsis"):
        lines.append(f"- 故事概述：{neutralize_tags(overview['synopsis'])}")
    if overview.get("genre"):
        lines.append(f"- 题材：{neutralize_tags(overview['genre'])}")
    lines.append(_target_volume_line(target_volume))
    lines.append(f"- 本批最多规划 {max_episodes} 集")
    if remaining_episodes is not None:
        lines.append(f"- 全剧尚需规划 {remaining_episodes} 集" + ("（本段原文已含全文结尾，请恰好规划完这些集）" if window_is_final else ""))
    lines += _context_lines(context_entries)
    if instructions:
        lines += ["", USER_INSTRUCTIONS_HEADER, instructions]
    lines += [
        "",
        "# 切分规则",
        "- 每一集给出 title（吸引人的短标题）、hook（集尾钩子：这一刀为什么切在这、给观众留了什么悬念）、",
        "  end_anchor（本集结尾处的原文片段，10~30 个字，必须从下方原文逐字摘抄、含标点，且在整段原文中唯一出现；",
        "  本集内容 = 上一集结尾之后到该片段末尾为止的全部原文）。",
        "- 每一集另给出 story_beats（本集故事节点列表，按顺序）与 next_episode_teaser（下集预告语；末集后续未知可为 null）"
        + ("；剧本已写明节点 / 预告时照搬其原文，未写明再自行提炼。" if is_screenplay else "。"),
    ]
    if is_screenplay:
        lines.append("- 优先照用作者的分集：剧本已划定每集边界时，end_anchor 取作者每集结尾处的原文片段。")
    lines.append("- 各集按顺序排列，end_anchor 位置必须严格递增（范围连续、不重叠、不留空洞）。")
    if window_is_final:
        lines.append("- 这段原文已包含全文结尾：请规划到结尾，最后一集的 end_anchor 取全文结尾处的片段，不要留尾巴。")
    else:
        lines.append("- 这段原文只是全文的一个窗口：窗口尾部剧情弧不完整的内容不要硬凑成集，留给下一批规划即可。")
    lines += ["", "# 剧本原文片段" if is_screenplay else "# 原文片段", "---", neutralize_tags(window), "---"]
    return "\n".join(lines)


def build_outline_plan_prompt(
    *,
    title: str,
    director_plan: str,
    overview: Mapping[str, Any] | None,
    first: int,
    last: int,
    total: int,
    context_entries: Sequence[Mapping[str, Any]],
    target_seconds: int | None,
    instructions: str | None,
) -> str:
    """Plan a contiguous run of episodes (title / hook / beats / teaser) from the director plan."""
    overview = overview or {}
    span = f"第 {first} 集" if first == last else f"第 {first} 集到第 {last} 集"
    lines = [
        f"你是短剧分集规划师。请基于总导演策划方案，为短剧《{neutralize_tags(title)}》规划{span}的分集大纲。",
        "全剧按黄金叙事结构推进：前 3 秒强钩子、每集一个完整的小剧情弧（交代冲突→压迫升级→反击/反转/情绪爆点），",
        "集尾留「必须看下一集」的悬念；集与集之间人物、场景、时间线连贯，不重复已规划集的情节。",
        "钩子先定情绪、再选写法：先想清楚观众看完这一下心里该冒出哪句话（「我也想要」「说的就是我」「原来如此」"
        "「答案到底是什么」「再不看就错过了」），再决定用结果前置、身份共鸣、反常识、悬念提问还是代价威胁来递出它；"
        "钩子靠具体细节（时间、数字、一个动作、一件物品）而不是形容词，悬念要让观众能猜、又猜不准。",
        "",
        "# 项目信息",
        f"- 全剧共 {total} 集，本批**恰好**输出 {last - first + 1} 集（对应{span}），episodes 数组长度必须等于 {last - first + 1}",
    ]
    if target_seconds:
        lines.append(f"- 单集成片目标约 {target_seconds} 秒，故事节点数量与密度按此把握（通常 4-7 个节点）")
    if overview.get("synopsis"):
        lines.append(f"- 故事概述：{neutralize_tags(overview['synopsis'])}")
    if overview.get("genre"):
        lines.append(f"- 题材：{neutralize_tags(overview['genre'])}")
    lines += _context_lines(context_entries)
    if instructions:
        lines += ["", USER_INSTRUCTIONS_HEADER, instructions]
    lines += [
        "",
        "# 规划规则",
        "- 每一集给出 title（吸引人的短标题）、hook（集尾钩子：这一集停在什么悬念上、为什么观众必须看下一集）、",
        "  story_beats（本集故事节点列表，按顺序，每条一句话、只写可拍摄的外部事件）、next_episode_teaser（下集预告语；全剧末集可为 null）。",
        f"- 最后一集（第 {total} 集）须完成全剧收束；其余每集结尾都要接得上下一集。",
        "- 不写心理描写，节点只描述镜头拍得到的动作、事件与对话结果。",
        "",
        "# 总导演策划方案",
        "---",
        neutralize_tags(director_plan),
        "---",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- stage A: script plan


_SCENE_RULE_NOVEL = (
    "改编后的视觉化描述：角色动作、神态、环境、光影氛围，适合画面呈现。以本分镜当下的单一时空落笔——"
    "原文的回忆、闪回、心理活动改编为此刻可见的载体（人物神态、手中物件、环境痕迹）；"
    "原文写「他很愤怒」「她害怕极了」这类情绪名词时，改写成摄影机看得见的身体细节（下颌绷紧、指节发白、往后缩半步），"
    "不在画面里写情绪名词。"
    "这段描述是后续单帧分镜画面的内容来源。**台词与旁白不要写进这里**——口播统一落在 utterances。"
)
_SCENE_RULE_SCREENPLAY = (
    "把作者写下的运镜、景别、舞台提示、视觉场面转写为画面视觉描述。**台词与旁白不要写进这里**——逐字落在 utterances；"
    "排版符号（markdown、△、各类标签、表格、emoji）一律剥离，只留干净文本。"
)
_SCENE_RULE_OUTLINE = (
    "你在**创作**画面：按本集故事节点写出角色动作、神态、环境、光影氛围，只写摄影机拍得到的内容；"
    "心理活动用物理动作与神态外化（眉骨微扣、指节发白），杜绝括号暗示。以本分镜当下的单一时空落笔。"
    "**台词与旁白不要写进这里**——口播统一落在 utterances。"
)
_UTTERANCES_NOVEL = (
    "按口播出现顺序产出发声序列，台词（dialogue）的 speaker 必须出现在 characters_in_scene。"
    "叙述、心理独白等不靠画面演出的内容，可按剧情语境判断写为旁白（voiceover）——是否产出由你依语境判断。"
    "原文点明了说话方式的（冷笑道、低声说、哽咽着），写进这句的 delivery（如「冷笑 / 慢 / 尾音下沉」），不进 text。"
    "分镜无口播则留空数组。"
)
_UTTERANCES_SCREENPLAY = (
    "把作者写下的台词与旁白**逐字照搬**为有序发声序列，按它们在分镜中的先后排列：台词（dialogue）的 speaker 填原文说话人"
    "（具名角色应来自 characters_in_scene，路人群演如「老人甲」照填原文称呼即可）；旁白写为 voiceover。"
    "不改写、不润色、不删减、不补写。小说体剧本里被动作隔开的同一句台词（“……，”他放下茶杯，“……”）合并为一句，"
    "引号内的文字逐字保留、引号外的动作不进台词。作者在台词前后括注的语气与情绪（（冷笑）（低声）（哽咽））"
    "照录进这句的 delivery，不进 text。分镜无口播则留空数组。"
)
_UTTERANCES_OUTLINE = (
    "按发声顺序写出台词（dialogue，speaker 必须出现在 characters_in_scene）与必要的旁白（voiceover）。"
    "台词高度口语化，单句不超过 15 个字，一句话只说一件事；每句台词可在 delivery 里给出表演标注"
    "（情绪类型-强度 / 语速 / 停顿与重音 / 生理表现），如「压抑-克制 / 慢 / 尾音下沉，指节发白」。分镜无口播则留空数组。"
)


def spoken_density_rule(spoken_shot_ratio: float, creation_mode: str = "drama") -> str:
    """The ask for talk-heavy episodes: how many shots must carry speech, and what kind."""
    ratio = max(0.0, min(1.0, float(spoken_shot_ratio or 0)))
    if ratio <= 0:
        return ""
    percent = int(round(ratio * 100))
    if creation_mode == "narration":
        return (
            f"**口播密度**：这是旁白解说片，讲述靠旁白推进——至少 {percent}% 的分镜要有旁白（voiceover），"
            "每个分镜 1–3 句，把事件、动机与情绪说出来，只有纯转场 / 空镜可以留空数组。"
        )
    return (
        f"**台词要多**：这是靠对白推进的剧情片——至少 {percent}% 的分镜要有口播，有人物出场的分镜几乎都该有台词；"
        "角色之间要有来有回（一问一答、针锋相对、试探与回避），每个分镜 2–4 句短台词，"
        "信息、冲突与情绪尽量让人物用嘴说出来，不要用画面描述或旁白代替对白；只有空镜 / 转场可以留空数组。"
        "台词多了就按口播时长取更长的秒数档位或拆成多个分镜，不要为了凑时长删台词。"
    )


_SOURCE_TEXT_GUIDE = "逐字摘录本分镜对应的原文片段，尽量与原文一致、宁缺毋造（无把握可留空）。"
_SOURCE_TEXT_OUTLINE = "填写本分镜覆盖的故事节点原文（从本集大纲的 story_beats 里逐字摘录），便于追溯。"

_HOOK_LANDING = (
    "末场（最后一个或几个分镜）的画面与对白须实际呈现集尾钩子的戏剧内容，让悬念定格在画面上；"
    "有下集预告语时，用结尾画面或对白自然引出，不要生硬插入「下集预告」字样的旁白。"
)


def _outline_block(episode_outline: Mapping[str, Any] | None, next_outline: Mapping[str, Any] | None) -> str:
    parts: list[str] = []
    if episode_outline:
        lines = []
        if episode_outline.get("title"):
            lines.append(f"本集标题：{neutralize_tags(episode_outline['title'])}")
        beats = episode_outline.get("story_beats") or []
        if beats:
            lines.append("故事节点：")
            lines.extend(f"- {neutralize_tags(beat)}" for beat in beats)
        if episode_outline.get("hook"):
            lines.append(f"集尾钩子：{neutralize_tags(episode_outline['hook'])}")
        if episode_outline.get("next_episode_teaser"):
            lines.append(f"下集预告语：{neutralize_tags(episode_outline['next_episode_teaser'])}")
        parts.append("<episode_outline>\n本集大纲（分集规划设计，剧本内容应覆盖全部故事节点）：\n" + "\n".join(lines) + "\n</episode_outline>")
        if episode_outline.get("hook") or episode_outline.get("next_episode_teaser"):
            parts.append(_HOOK_LANDING)
    if next_outline:
        lines = []
        if next_outline.get("title"):
            lines.append(f"下集标题：{neutralize_tags(next_outline['title'])}")
        beats = next_outline.get("story_beats") or []
        if beats:
            lines.append("故事节点：")
            lines.extend(f"- {neutralize_tags(beat)}" for beat in beats)
        parts.append("<next_episode_outline>\n下集大纲（仅用于设计本集结尾的衔接，不要把下集情节提前写进本集）：\n" + "\n".join(lines) + "\n</next_episode_outline>")
    return ("\n\n".join(parts) + "\n\n") if parts else ""


def build_script_plan_prompt(
    *,
    source_text: str,
    source_kind: SourceKind,
    episode: int,
    overview: Mapping[str, Any] | None,
    style: str,
    characters: Mapping[str, Any],
    scenes: Mapping[str, Any],
    props: Mapping[str, Any],
    supported_durations: Sequence[int],
    default_duration: int | None,
    episode_target_seconds: int | None,
    episode_outline: Mapping[str, Any] | None,
    next_episode_outline: Mapping[str, Any] | None,
    episode_shape: EpisodeShape | None = None,
    language: str | None = None,
    speech_rate_override: float | None = None,
    spoken_shot_ratio: float = 0.0,
    creation_mode: str = "drama",
) -> str:
    """Stage A prompt: source (or outline) → structured shot content.

    ``spoken_shot_ratio`` (outline mode only) asks for talk-heavy episodes: that share of
    the shots must carry speech. Episodes cut from a source keep the source's own lines.
    """
    durations = sorted({int(value) for value in supported_durations})
    if not durations:
        raise ValueError("supported_durations 不能为空")
    if default_duration is not None and default_duration not in durations:
        raise ValueError(f"default_duration={default_duration} 不在 supported_durations={durations} 内")
    durations_str = ", ".join(str(value) for value in durations)
    max_dur = durations[-1]
    if default_duration is not None:
        base_rule = (
            f"从支持的秒数档位（{durations_str}）中按画面内容选择：默认 {default_duration} 秒，"
            f"打斗 / 大场面 / 情绪铺陈等画面可取更长档至 {max_dur} 秒，不要默认选最短档"
        )
    else:
        base_rule = f"从支持的秒数档位（{durations_str}）中按画面内容复杂度匹配合适时长（最长 {max_dur} 秒），不强制默认值"
    rate = speech_rate_units_per_second(language, speech_rate_override)
    unit = reading_unit_noun(language)
    lower_bound_rule = (
        "再按台词口播长度设下界：先估算该分镜 utterances（台词 + 旁白）念完约需的秒数"
        f"（口播语速约 {rate:g} {unit}/秒），在上述档位里取**不低于**这个秒数的最接近档位；"
        "这是单向下界——画面留白可在此之上取更长档位，但台词永不把时长压到念不完的短档；"
        f"若一段口播已超过最长档 {max_dur} 秒，必须把它拆成多个分镜，不删台词、不强压"
    )
    duration_rule = f"{base_rule}。{lower_bound_rule}"
    target_rule = render_episode_target_rule(episode_target_seconds, episode_shape)
    if target_rule:
        duration_rule = f"{duration_rule}。{target_rule}"

    if source_kind == "screenplay":
        task = (
            "你的任务是从作者已写好的剧本中**提取**结构化的分镜内容：逐字保留台词与旁白（落在 utterances）、"
            "摘录原文锚 source_text、把视觉层转写为分镜视觉描述，用于后续 AI 视频生成。这是成品剧本、不是待加工素材——只做提取、不做再创作。"
        )
        heading, tag = "剧本原文", "screenplay"
        scene_rule, utter_rule, source_rule = _SCENE_RULE_SCREENPLAY, _UTTERANCES_SCREENPLAY, _SOURCE_TEXT_GUIDE
        break_rule = "沿用剧本自带的场次切换——场次变更（地点 / 时间 / 场景切换）标 true，同一场次内标 false；不要重新切碎作者的场次。"
        language_rule = (
            f"自然语言字符串值使用{output_language_name()}；JSON 键名 / 枚举值保持英文。例外（逐字保留、不改写）："
            "资产引用字段（characters_in_scene / scenes / props，须逐字等于候选表登记名）与逐字字段"
            "（utterances[].text / utterances[].speaker / source_text）。"
        )
    elif source_kind == "novel":
        task = "你的任务是将小说原文**改编**为结构化的分镜内容（视觉改编描述、逐字口播 utterances 与原文锚 source_text），用于后续 AI 视频生成。"
        heading, tag = "小说原文", "novel"
        scene_rule, utter_rule, source_rule = _SCENE_RULE_NOVEL, _UTTERANCES_NOVEL, _SOURCE_TEXT_GUIDE
        break_rule = "在真正的场景切换点（地点 / 时间的重大变化）标 true，同一连续场景内标 false。"
        language_rule = (
            f"自然语言字符串值使用{output_language_name()}；JSON 键名 / 枚举值保持英文。例外（逐字保留）：资产引用字段"
            "（characters_in_scene / scenes / props，须逐字等于候选表登记名）、utterances[].speaker 与原文锚 source_text。"
        )
    else:
        task = (
            "你是专业短剧编剧。你的任务是按本集分集大纲**创作**结构化的分镜内容：每个分镜一次定稿分镜边界、出场资产、"
            "逐字口播 utterances（含表演标注）与视觉描述，用于后续 AI 视频生成。只写摄影机拍得到的画面和能听到的声音，"
            "杜绝任何心理描写和括号暗示。"
        )
        heading, tag = "本集写作依据（导演策划节选）", "director_plan"
        density = spoken_density_rule(spoken_shot_ratio, creation_mode)
        scene_rule, utter_rule, source_rule = _SCENE_RULE_OUTLINE, (_UTTERANCES_OUTLINE + (" " + density if density else "")), _SOURCE_TEXT_OUTLINE
        break_rule = "在真正的场景切换点（地点 / 时间的重大变化）标 true，同一连续场景内标 false；一个分镜内不要跨越多个地点或大段时间。"
        language_rule = (
            f"自然语言字符串值使用{output_language_name()}；JSON 键名 / 枚举值保持英文。资产引用字段"
            "（characters_in_scene / scenes / props）须逐字等于候选表登记名，utterances[].speaker 须等于 characters_in_scene 中的角色名。"
        )

    character_names = _names(characters)
    scene_names = _names(scenes)
    prop_names = _names(props)
    # 本集写到打斗才装打戏设计规则，文戏集不占篇幅。
    fight_rules = plan_rules_for(source_text, _outline_block(episode_outline, None))
    fight_block = f"\n{fight_rules}" if fight_rules else ""
    return f"""{task}

**输出语言**：{language_rule}
**结构约束**：字段 / 枚举 / 必填项由 JSON Schema 强制；本提示只解释**如何写好每个字段的内容**。

{render_pacing_section("drama")}

## 项目信息

{_overview_block(overview)}

<style>
{neutralize_tags(style)}
</style>

<characters>
{_format_assets_with_desc(characters)}
</characters>

<scenes>
{_format_name_list(scenes)}
</scenes>

<props>
{_format_name_list(props)}
</props>

## {heading}

<{tag}>
{neutralize_tags(source_text)}
</{tag}>

{_outline_block(episode_outline, next_episode_outline)}# 字段写作指引

把内容拆为有序分镜，逐条产出结构化分镜内容。当前正在生成第 {episode} 集。

## 基础字段

- **scene_id**：`E{episode}S{{两位序号}}` 格式（如 E{episode}S01），按分镜顺序递增，不得用其他集号前缀。
- **duration_seconds**：{duration_rule}。
- **segment_break**：{break_rule}
- **setting**：场景标题行，写成「地点 时间 内景/外景」（如「市井长街 黄昏 外景」），地点优先用候选场景表里的名字。
- **characters_in_scene** / **scenes** / **props**：从下列候选中列出此分镜实际出现的资产。
  - 候选 characters：[{", ".join(character_names) or "（暂无）"}]
  - 候选 scenes：[{", ".join(scene_names) or "（暂无）"}]
  - 候选 props：[{", ".join(prop_names) or "（暂无）"}]
  - 不要发明候选之外的名称；泛指群演（如「老人甲」「村民若干」）不进 characters_in_scene。
- **scene_description**：{scene_rule}

## 逐字内容（内容真相源，定稿后原样保留、不再改写）

- **source_text**：{source_rule}
- **utterances**：{utter_rule}

每个分镜应为一个独立的视觉画面、可在指定时长内完成；避免在一个分镜内安排多个动作或画面切换。
一个分镜的出场角色不超过 3 人；激烈打斗、奔跑、多人肢体接触改用近景暗示或侧面过肩镜头承载。
{fight_block}"""


# --------------------------------------------------------------------------- stage B: visual layer


_SCENE_WRITING_GUIDE = (
    "这段文字将直接生成一张静态图：只描述此刻单帧画面上可见的内容，按主体（姿态 / 表情 / 服装）、环境（陈设 / 物件）、"
    "光线、氛围（雾、雨等可见信号）分层给出具体细节，写成连贯的叙述句而非关键词堆叠。原文若是回忆 / 闪回 / 心理活动，"
    "改编为此刻可见的载体——人物神态、手中物件、环境痕迹，画面里只保留一个时空。画面元素须贴合 <style> 块的风格基调。\n"
    "   正例：「林清坐在窗边木桌前，左手撑着下巴，目光落在桌上一封拆开的信纸上；桌面摊着信封与一只褪色的怀表。"
    "半边脸笼在右侧落地窗逆光的蓝灰色阴影里，雨丝拍在木格窗棂，玻璃凝着细小水珠。」——主体、环境、光线、氛围各有一笔。\n"
    "   反例：「林清陷入了多年前那个绝望的雨夜，画面基调：忧郁。」——「多年前的雨夜」不在此刻画面上；「忧郁」是抽象标签。"
)
_ACTION_WRITING_GUIDE = (
    "首帧画面已定格主体、场景与风格，这段文字驱动它动起来：只描述该时长内发生的运动与变化，不复述静态内容；"
    "镜头运动专由 camera_motion 承载，action 只写主体与环境的运动。按主体动作（肢体 / 手势 / 表情过渡）、物件互动、"
    "环境动态（衣摆、尘埃、雨势、光影移动）分层写成连贯叙述句；动词描述物理可观察动作（伸手 / 转身 / 摩挲），避免内心动词。"
    "优先低缓、连贯的细微动作，动作量与时长匹配：5 秒级完成一个连贯动作加一个细节互动；8 秒级可承载一次动作过渡；"
    "更长的分镜保持单一动作主线、随时长递增动作段数，而非叠加并行动作。\n"
    "   正例：「林清缓缓抬起头，眼角微微收紧，手指无意识地摩挲信纸边缘；窗外雨势渐大，桌面的雨痕影子缓慢移动。」\n"
    "   反例：「林清像蝴蝶般飞舞，思绪在过去与现在之间快速切换。」——「思绪切换」不可拍摄，「像蝴蝶般」是修辞。\n"
    "   避开任务类型触发词：不要用「增加 / 删除 / 去掉 / 修改 / 替换 / 改成 / 延长 / 续写」这类祈使动词，直接描述目标画面本身。"
)
_LIGHTING_GUIDE = (
    "描述具体的光源、方向、色温（如「左侧窗户透入的暖黄色晨光（约 3500K）」），可附加摄影质感术语"
    "（浅景深、逆光剪影、丁达尔光柱、轮廓光勾边、35mm 胶片颗粒感）；避免「光影神秘」「氛围唯美」这类抽象词。"
)
_AMBIANCE_GUIDE = "描述可观察的环境效果（如「薄雾弥漫」「尘埃在光柱里翻飞」），避免抽象情绪词。"
_AMBIANCE_AUDIO_GUIDE = "只描写画内音：环境声、脚步、物体声响。不要写 BGM、配乐、画外音、旁白。"


def render_scene_content_for_visual(content_scenes: Sequence[Mapping[str, Any]]) -> str:
    if not content_scenes:
        return "（无分镜内容）"
    blocks: list[str] = []
    for scene in content_scenes:
        if not isinstance(scene, Mapping):
            continue
        sid = neutralize_tags(scene.get("scene_id") or "?")
        duration = scene.get("duration_seconds")
        lines = [f"### {sid}" + (f"（时长 {duration} 秒）" if duration else "")]
        if scene.get("setting"):
            lines.append(f"场景：{neutralize_tags(scene.get('setting'))}")
        cast = [item for item in (scene.get("characters_in_scene") or []) if isinstance(item, str)]
        scene_refs = [item for item in (scene.get("scenes") or []) if isinstance(item, str)]
        prop_refs = [item for item in (scene.get("props") or []) if isinstance(item, str)]
        lines.append(
            f"出场资产：角色 [{neutralize_tags(', '.join(cast) or '无')}]、场景 [{neutralize_tags(', '.join(scene_refs) or '无')}]、"
            f"道具 [{neutralize_tags(', '.join(prop_refs) or '无')}]"
        )
        lines.append(f"视觉改编：{neutralize_tags(scene.get('scene_description') or '（无）').replace(chr(10), chr(10) + '  ')}")
        utterances = [item for item in (scene.get("utterances") or []) if isinstance(item, Mapping)]
        if utterances:
            lines.append("口播：")
            for utterance in utterances:
                text = neutralize_tags(utterance.get("text") or "")
                if utterance.get("kind") == "dialogue":
                    lines.append(f"  - [台词] {neutralize_tags(utterance.get('speaker') or '')}：{text}")
                else:
                    lines.append(f"  - [旁白] {text}")
        if scene.get("source_text"):
            lines.append(f"原文锚：{neutralize_tags(scene.get('source_text')).replace(chr(10), chr(10) + '  ')}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _fight_visual_block(content_scenes: Sequence[Mapping[str, Any]]) -> str:
    rules = visual_rules_for(render_scene_content_for_visual(content_scenes))
    return f"{rules}\n" if rules else ""


def build_visual_prompt(
    *,
    episode: int,
    overview: Mapping[str, Any] | None,
    style: str,
    style_description: str,
    characters: Mapping[str, Any],
    scenes: Mapping[str, Any],
    props: Mapping[str, Any],
    content_scenes: Sequence[Mapping[str, Any]],
    aspect_ratio: str = "9:16",
) -> str:
    """Stage B prompt: fixed shot content → image_prompt / video_prompt per scene_id."""
    return f"""# 角色与任务

你是一位资深的短剧分镜摄影 / 动作设计师。下方分镜内容（分镜边界、出场资产、逐字口播、原文锚、视觉改编描述）均已定稿，
你的唯一职责是为每个分镜补全视觉生产层：image_prompt（画面）与 video_prompt（动作 / 运镜 / 环境音）。
**不要改写或重述口播、不要新增 / 删除 / 重排分镜、不要改动分镜内容**——只按 scene_id 逐条产出视觉字段。

**输出语言**：所有字符串值使用{output_language_name()}；JSON 键名 / 枚举值保持英文。
**结构约束**：字段 / 枚举 / 必填项由 JSON Schema 强制；本提示只解释**如何写好每个字段的内容**。
**对齐约束**：每个分镜产出一条视觉层，scene_id 必须与下方内容逐字一致、不增不减不改；不要输出口播 / 时长 / 资产等非视觉字段。

{render_pacing_section("drama")}

# 上下文

{_overview_block(overview)}

<style>
风格：{neutralize_tags(style)}
描述：{neutralize_tags(style_description)}
画面比例：{aspect_ratio}（{_aspect_desc(aspect_ratio)}）
</style>

<characters>
{_format_assets_with_desc(characters)}
</characters>

<scenes>
{_format_assets_with_desc(scenes)}
</scenes>

<props>
{_format_assets_with_desc(props)}
</props>

资产外观以上述描述为准：视觉字段写到出场资产的服装 / 材质 / 陈设细节时从中取材，不自行发明。
分镜内容中的「口播」与「原文锚」仅供理解戏剧节奏与语境，不要复制进视觉字段。

<shots>
{render_scene_content_for_visual(content_scenes)}
</shots>

<episode_constraints>
当前正在生成第 {episode} 集。每条视觉层的 scene_id 必须逐字等于上方分镜内容里的 scene_id；若该 ID 含拆分后缀（如 `_1`），也必须原样保留。
</episode_constraints>

# 字段写作指引

## 图片提示词（image_prompt）——切换到「摄影师」视角

- **image_prompt.scene**：{_SCENE_WRITING_GUIDE}
- **image_prompt.composition.shot_type**：从枚举中按画面内容选择；AI 生成手部与多人肢体接触易畸变，物理交互优先用中景以上景别或过肩镜头承载。
- **image_prompt.composition.lighting**：{_LIGHTING_GUIDE}
- **image_prompt.composition.ambiance**：{_AMBIANCE_GUIDE}

## 视频提示词（video_prompt）——切换到「动作设计师」视角

- **video_prompt.action**：{_ACTION_WRITING_GUIDE}
- **video_prompt.camera_motion**：按画面内容自行选择。
- **video_prompt.ambiance_audio**：{_AMBIANCE_AUDIO_GUIDE}

{_fight_visual_block(content_scenes)}# 创作目标

输出可直接驱动 AI 图像 / 视频生成的、视觉一致、节奏紧凑的视觉层。忠于已定稿的分镜内容与戏剧张力。
"""


# --------------------------------------------------------------------------- prose body


_PROSE_EXAMPLE = (
    "正例（一段一行，段与段之间空一行）：\n\n"
    "雨下到后半夜，巷口的灯只剩一盏。\n\n"
    "林清把伞收在门边，水顺着伞骨淌了一地。桌上摊着一封拆开的信，信纸的边已经被她捏得起了毛。\n\n"
    "“你早就知道了。”她没有抬头，“对不对？”\n\n"
    "周叔把茶杯往前推了推，杯底在木桌上磨出一声轻响。“知道又怎样。”\n\n"
    "反例：\n\n"
    "场景1：林家堂屋 夜 内景\n"
    "镜头：中景 固定\n"
    "林清（愤怒）：你早就知道了！\n\n"
    "——标签行、景别运镜、「角色：台词」和括号提示都属于分镜表，不属于正文。"
)


def _prose_length_rule(shot_count: int, language: str | None) -> str:
    unit = reading_unit_noun(language)
    low, high = 80 * max(1, shot_count), 170 * max(1, shot_count)
    return f"篇幅以写足每个分镜的画面与动作为准，本集约 {low}–{high} {unit}；不注水，也不要把几个分镜压成一句话带过。"


def build_prose_prompt(
    *,
    episode: int,
    overview: Mapping[str, Any] | None,
    style: str,
    characters: Mapping[str, Any],
    content_scenes: Sequence[Mapping[str, Any]],
    episode_outline: Mapping[str, Any] | None,
    previous_ending: str = "",
    language: str | None = None,
    previous_is_plan: bool = False,
) -> str:
    """Prose stage prompt: the fixed shot content of one episode → its 小说体正文.

    ``previous_ending`` is the tail of the previous episode: its prose when that is
    already written, else (``previous_is_plan``) its last shots told plainly, so
    episodes can be told side by side and still open where the last one closed.
    """
    previous_label = (
        "上一集结尾的分镜内容（上一集正文正在同时写作；仅用于衔接时空与语气，不要复述）"
        if previous_is_plan else "上一集正文的结尾（仅用于衔接时空与语气，不要复述）"
    )
    previous_block = (
        f"<previous_ending>\n{previous_label}：\n"
        f"{neutralize_tags(previous_ending)}\n</previous_ending>\n\n"
        if previous_ending.strip() else ""
    )
    outline = episode_outline or {}
    outline_lines = [f"本集标题：{neutralize_tags(outline['title'])}"] if outline.get("title") else []
    if outline.get("story_beats"):
        outline_lines.append("故事节点：")
        outline_lines.extend(f"- {neutralize_tags(beat)}" for beat in outline["story_beats"])
    if outline.get("hook"):
        outline_lines.append(f"集尾钩子：{neutralize_tags(outline['hook'])}")
    outline_block = (
        "<episode_outline>\n本集大纲（帮助你把握叙事的轻重与走向，分镜内容已覆盖这些节点）：\n"
        + "\n".join(outline_lines) + "\n</episode_outline>\n\n"
        if outline_lines else ""
    )
    return f"""# 角色与任务

你是一位擅长影视改编的小说家。下方是第 {episode} 集**已定稿**的分镜内容（分镜顺序、出场角色、视觉描述、逐字口播）。
请把它写成本集的**小说体剧本正文**——给人读的连贯故事，而不是给机器读的分镜表。
剧情、人物与台词都已定稿：**不新增或删减事件、不新增角色、不新增或改写台词**，你只负责把定稿内容写成好读的叙事文字。

**输出**：只输出正文本身（纯文本）。不要「第N集」标题、不要前言 / 说明 / 自检 / 结语、不要 markdown 记号、不要 JSON。

# 上下文

{_overview_block(overview)}

<style>
{neutralize_tags(style)}
</style>

<characters>
{_format_assets_with_desc(characters)}
</characters>

{outline_block}{previous_block}<shots>
{render_scene_content_for_visual(content_scenes)}
</shots>

# 写作要求

1. **叙事形态**：第三人称叙述，一段一行，段与段之间空一行；每段只讲一个动作节拍或一轮对话，多用短段。
   按分镜顺序写，覆盖每一个分镜的内容；相邻分镜写成连贯的段落，地点与时间的切换用叙述自然带过
   （如「三日后」「门在他背后落了栓」），不写场景标题。
2. **台词**：<shots> 里的每一句口播都必须**逐字**出现在正文里，台词放进中文引号“”，不改字、不删字、不换说法、不调整先后。
   说话人与其动作、神态写在引号前后；一句台词可以在它原有的标点处被动作隔开
   （“你听好，”她把信纸按在桌上，“这不是我写的。”），引号里的字连起来必须与原句一致。
   旁白类口播同样逐字保留，写成独立的叙述段落。不要写出 <shots> 里没有的台词。
3. **画面**：只写看得见的画面与听得见的声音；人物的心理用动作、神态和手里的物件外化，不用括号做提示。
   取材于分镜的视觉描述与角色外观，可以补足衔接动作与环境细节，但不改变事件的因果与结果。
4. **结尾**：最后一两段落在本集的集尾钩子上，让悬念停在画面或一句台词上；不写「下集预告」「未完待续」之类的字样。
5. **不要出现**：场景 / 镜头 / 画面 / 动作 / 旁白 / 时长等标签行，景别与运镜术语，分镜编号（E{episode}S01），
   「角色名：台词」的剧本体对白，括号舞台提示，列表与表格。
6. **篇幅**：{_prose_length_rule(len(content_scenes), language)}
7. **语言**：正文用{output_language_name()}写作（逐字保留的口播除外）；下面的示例只示范写法，不示范语言。

{_PROSE_EXAMPLE}
"""


__all__ = [
    "USER_INSTRUCTIONS_HEADER",
    "append_user_instructions",
    "build_anchored_plan_prompt",
    "build_asset_inventory_prompt",
    "build_outline_plan_prompt",
    "build_overview_prompt",
    "build_prose_prompt",
    "build_script_plan_prompt",
    "build_visual_prompt",
    "neutralize_tags",
    "render_scene_content_for_visual",
    "sample_source",
    "spoken_density_rule",
]
