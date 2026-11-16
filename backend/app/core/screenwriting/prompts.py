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

The wording of every builder lives in ``app/data/prompt/screenwriting_prompts.json``
(one section per builder); this module only decides which sentences apply and fills them in.
"""

from __future__ import annotations

import re

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from collections.abc import Mapping, Sequence
from typing import Any

from app.core import light_setups
from app.core import acting, breakdown_kinds, character_block, emotion_points, literary, prompt_data, visual_wording, xianxia_lore
from app.core.episode_shape import EpisodeShape
from app.core import series_rhythm
from app.core.fight_design import plan_rules_for, visual_rules_for
from app.core.wuxia_vfx import plan_rules_for as spectacle_plan_rules
from app.core.screenwriting import filmability, story_state
from app.core.screenwriting.durations import render_episode_target_rule
from app.core.screenwriting.pacing import pacing_for, render_pacing_section
from app.core.screenwriting.speech_rate import speech_rate_units_per_second
from app.core.screenwriting.text_metrics import reading_unit_noun

# The sentences, templates and word tables of every builder below: app/data/prompt/screenwriting_prompts.json.
_WORDING = "screenwriting_prompts"


def _entry(key: str) -> Any:
    """The entry at the dotted ``key`` ("section.name") of the wording table."""
    node: Any = prompt_data.load(_WORDING)
    for part in key.split("."):
        node = node[part]
    return node


def _template(key: str) -> str:
    """A template of the wording table as written (an array of lines is joined with newlines)."""
    entry = _entry(key)
    return "\n".join(str(line) for line in entry) if isinstance(entry, list) else str(entry)


def _says(key: str, /, **values: object) -> str:
    """A template of the wording table, filled in (``key`` is positional: a template may name a ``{key}``)."""
    return _template(key).format(**values)


def _table(key: str) -> Any:
    """A word table or a list of limits of the wording table, used as it stands."""
    return _entry(key)


USER_INSTRUCTIONS_HEADER = _says("common.user_instructions_header")

SourceKind = str  # "outline" | "novel" | "screenplay"


# The language the audience-facing text is written in (titles, hooks, lines, narration, prose,
# visual descriptions). The engine sets it for the duration of a call; JSON keys stay English.
OUTPUT_LANGUAGES = {str(code): str(name) for code, name in _table("common.languages").items()}
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
    return "\n".join(f"- {neutralize_tags(name)}" for name in names) if names else _says("common.none_yet")


def _format_assets_with_desc(mapping: Mapping[str, Any] | None) -> str:
    lines: list[str] = []
    for name, entry in (mapping or {}).items():
        description = ""
        if isinstance(entry, Mapping):
            description = str(entry.get("description") or "").strip()
        safe = neutralize_tags(name)
        if description:
            lines.append(_says("common.asset_line", name=safe, description=neutralize_tags(description).replace(chr(10), chr(10) + '  ')))
        else:
            lines.append(f"- {safe}")
    return "\n".join(lines) if lines else _says("common.none_yet")


def _overview_block(overview: Mapping[str, Any] | None) -> str:
    overview = overview or {}
    # 立意卡（立意 / 母题 / 终局意象）填了才写，每集的写作都照它。
    literary_lines = "".join(f"{neutralize_tags(line)}\n" for line in literary.overview_lines(overview))
    return _says(
        "common.overview_block",
        synopsis=neutralize_tags(overview.get('synopsis', '')),
        genre=neutralize_tags(overview.get('genre', '')),
        theme=neutralize_tags(overview.get('theme', '')),
        literary_lines=literary_lines,
        world_setting=neutralize_tags(overview.get('world_setting', '')),
    )


OMITTED_MARK = _template("common.omitted_mark")


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
            parts.append(_says("common.omitted_mark", count=start - previous_end))
        parts.append(text[start:end].strip("\n"))
        previous_end = end
    return "\n\n".join(parts)


def _aspect_desc(aspect_ratio: str) -> str:
    named = _table("visual.aspect_names")
    return str(named[aspect_ratio]) if aspect_ratio in named else _says("visual.aspect_other", ratio=aspect_ratio)


# --------------------------------------------------------------------------- overview


def build_overview_prompt(source_content: str, *, source_kind: SourceKind, title_hint: str = "") -> str:
    if source_kind == "screenplay":
        task = _says("overview.task_screenplay")
        heading, tag = _says("common.heading_screenplay"), "screenplay"
    elif source_kind == "novel":
        task = _says("overview.task_novel")
        heading, tag = _says("common.heading_novel"), "novel"
    else:
        task = _says("overview.task_director_plan")
        heading, tag = _says("common.heading_director_plan"), "director_plan"
    hint = _says("overview.title_hint", hint=neutralize_tags(title_hint)) if title_hint else ""
    return _says(
        "overview.body",
        task=task, ask=literary.overview_ask(), hint=hint, language=output_language_name(),
        heading=heading, tag=tag, source=neutralize_tags(source_content),
    )


# --------------------------------------------------------------------------- asset inventory


_ASSET_RULES_NOVEL = _says(
    "asset_inventory.rules_novel",
    voice_print=literary.voice_print_rule(), character_block=character_block.rules_line(), writer_rules=breakdown_kinds.WRITER_RULES,
)
_ASSET_RULES_SCREENPLAY = _says(
    "asset_inventory.rules_screenplay",
    character_block=character_block.rules_line(authored=True), writer_rules=breakdown_kinds.WRITER_RULES,
)


_RELATION_RULES = _says("asset_inventory.relation_rules")


def build_asset_inventory_prompt(
    source_content: str,
    *,
    source_kind: SourceKind,
    overview: Mapping[str, Any] | None,
    existing: Mapping[str, Sequence[str]] | None = None,
) -> str:
    rules = _ASSET_RULES_SCREENPLAY if source_kind == "screenplay" else _ASSET_RULES_NOVEL
    if source_kind == "screenplay":
        heading = _says("common.heading_screenplay")
    elif source_kind == "novel":
        heading = _says("common.heading_novel")
    else:
        heading = _says("common.heading_director_plan")
    existing_block = ""
    if existing:
        parts = []
        separator = _says("asset_inventory.name_separator")
        for key, label in (*_table("asset_inventory.existing_labels").items(),
                           *((key, breakdown_kinds.LABELS[kind]) for kind, key in breakdown_kinds.CATALOG_KEYS.items())):
            names = list(existing.get(key) or [])
            if names:
                parts.append(_says("asset_inventory.existing_line", label=label, names=separator.join(neutralize_tags(name) for name in names)))
        if parts:
            existing_block = _says("asset_inventory.existing_block", lines="\n".join(parts))
    return _says(
        "asset_inventory.body",
        overview=_overview_block(overview), rules=rules, relation_rules=_RELATION_RULES, existing=existing_block,
        heading=heading, source=neutralize_tags(source_content),
    )


# --------------------------------------------------------------------------- episode planning


# --------------------------------------------------------------------------- novel adaptation brief


def adaptation_limit(name: str) -> int:
    """A limit of the adaptation brief: ``keep`` / ``compress`` entries, ``narrated_shots`` per drama episode."""
    return int(_table("adaptation.limits")[name])


def build_adaptation_prompt(source_content: str, *, overview: Mapping[str, Any] | None, characters: Mapping[str, Any] | None) -> str:
    """Before a novel is cut into episodes: what it sells, whose story it is, where it opens, what may not be cut."""
    return _says(
        "adaptation.body",
        language=output_language_name(),
        overview=_overview_block(overview),
        characters=_format_assets_with_desc(characters),
        keep=adaptation_limit("keep"),
        compress=adaptation_limit("compress"),
        heading=_says("common.heading_novel"),
        source=neutralize_tags(source_content),
    )


def _brief_text(brief: Mapping[str, Any] | None, name: str) -> str:
    return neutralize_tags(str(brief.get(name) or "").strip()) if isinstance(brief, Mapping) else ""


def _brief_items(brief: Mapping[str, Any] | None, name: str) -> list[str]:
    if not isinstance(brief, Mapping) or not isinstance(brief.get(name), (list, tuple)):
        return []
    items = [neutralize_tags(str(item).strip()) for item in brief[name] if str(item or "").strip()]
    return items[: adaptation_limit(name)]


def _adaptation_ledger_lines(brief: Mapping[str, Any] | None) -> list[str]:
    """The brief as the ledger planner reads it: everything, the skippable parts included. Nothing without a brief."""
    lines: list[str] = []
    if _brief_text(brief, "selling_point"):
        lines.append(_says("adaptation.selling_point", text=_brief_text(brief, "selling_point")))
    if _brief_text(brief, "protagonist"):
        lines.append(_says("adaptation.protagonist", text=_brief_text(brief, "protagonist")))
    if _brief_text(brief, "situation"):
        lines.append(_says("adaptation.situation", text=_brief_text(brief, "situation")))
    if _brief_text(brief, "main_line"):
        lines.append(_says("adaptation.main_line", text=_brief_text(brief, "main_line")))
    if _brief_text(brief, "core"):
        lines.append(_says("adaptation.core", text=_brief_text(brief, "core")))
    keep = _brief_items(brief, "keep")
    if keep:
        lines += [_says("adaptation.keep_ledger"), *(_says("adaptation.item", text=item) for item in keep)]
    skippable = _brief_items(brief, "compress")
    if skippable:
        lines += [_says("adaptation.compress"), *(_says("adaptation.item", text=item) for item in skippable)]
    return ["", _says("adaptation.heading"), *lines] if lines else []


def _adaptation_plan_block(brief: Mapping[str, Any] | None, episode: int) -> str:
    """What an adapted episode is told: the rules of adapting, and the brief's parts a single episode can act on."""
    lines: list[str] = []
    if _brief_text(brief, "protagonist"):
        lines.append(_says("adaptation.protagonist", text=_brief_text(brief, "protagonist")))
    if episode == 1 and _brief_text(brief, "situation"):
        lines.append(_says("adaptation.situation", text=_brief_text(brief, "situation")))
    if _brief_text(brief, "main_line"):
        lines.append(_says("adaptation.main_line", text=_brief_text(brief, "main_line")))
    if _brief_text(brief, "core"):
        lines.append(_says("adaptation.core", text=_brief_text(brief, "core")))
    keep = _brief_items(brief, "keep")
    if keep:
        lines += [_says("adaptation.keep_plan"), *(_says("adaptation.item", text=item) for item in keep)]
    parts = [_says("adaptation.plan_wrap", lines="\n".join(lines))] if lines else []
    rules = _says("script_plan.adaptation_rules")
    if episode == 1:
        rules = f"{rules}\n{_says('script_plan.first_episode_novel')}"
    parts.append(rules)
    return "\n\n".join(parts) + "\n\n"


def _target_volume_line(volume) -> str:
    if volume is None:
        return _says("episode_plan.volume_unset")
    if volume.source == "duration":
        return _says(
            "episode_plan.volume_duration",
            units=volume.units, unit_noun=volume.unit_noun, seconds=volume.seconds, units_per_second=volume.units_per_second,
        )
    if volume.source == "episode_count":
        return _says("episode_plan.volume_episode_count", units=volume.units, unit_noun=volume.unit_noun)
    return _says("episode_plan.volume_units", units=volume.units, unit_noun=volume.unit_noun)


def _context_lines(context_entries: Sequence[Mapping[str, Any]]) -> list[str]:
    lines: list[str] = []
    if context_entries:
        lines += ["", _says("episode_plan.context_heading")]
        for entry in context_entries:
            lines.append(_says(
                "episode_plan.context_line",
                episode=entry.get('episode'),
                title=neutralize_tags(entry.get('title') or _says("episode_plan.untitled")),
                hook=neutralize_tags(entry.get('hook') or ''),
            ))
            # 跨集场记：这一集演完已经定下的事，接着排的集要守住。
            settled = story_state.context_changes(entry)
            if settled:
                lines.append(neutralize_tags(settled))
    return lines


def _relation_rows(relationships: Sequence[Mapping[str, Any]] | None, names: Sequence[str] | None = None) -> list[str]:
    """人物关系逐条一行：「沈砚 → 林晚：暗恋」；``names`` 给了就只留与这些人有关的。"""
    wanted = {str(name) for name in names} if names is not None else None
    rows: list[str] = []
    for item in relationships or []:
        if not isinstance(item, Mapping):
            continue
        source = str(item.get("from") or item.get("from_") or item.get("source") or "").strip()
        target = str(item.get("to") or item.get("target") or "").strip()
        relation = str(item.get("relation") or item.get("label") or "").strip()
        if not (source and target and relation):
            continue
        if wanted is not None and source not in wanted and target not in wanted:
            continue
        arrow = prompt_data.text(_CAST, "arrow_both" if item.get("bidirectional") else "arrow_one_way")
        rows.append(prompt_data.text(_CAST, "relation_line").format(
            source=neutralize_tags(source), arrow=arrow, target=neutralize_tags(target), relation=neutralize_tags(relation),
        ))
    return rows[: prompt_data.number(_CAST, "max_relations")]


def _ledger_cast_lines(cast: Mapping[str, Any] | None) -> list[str]:
    """分集规划看到的角色表与人物关系：创作看板先定下来，账本照着它排戏。没有就不加。"""
    if not isinstance(cast, Mapping):
        return []
    characters = cast.get("characters") if isinstance(cast.get("characters"), Mapping) else {}
    other_role = _says("episode_plan.other_role")
    people = [
        prompt_data.text(_CAST, "character_line").format(
            name=neutralize_tags(name),
            position=neutralize_tags(str((entry or {}).get("position") or other_role) if isinstance(entry, Mapping) else other_role),
        )
        for name, entry in list(characters.items())[: prompt_data.number(_CAST, "max_characters")]
        if str(name).strip()
    ]
    relations = _relation_rows(cast.get("relationships"))
    if not people and not relations:
        return []
    lines = ["", prompt_data.text(_CAST, "ledger_heading"), *people]
    if relations:
        lines += [prompt_data.text(_CAST, "relations_label"), *relations]
    lines.append(prompt_data.text(_CAST, "ledger_rule"))
    return lines


def _relationships_block(relationships: Sequence[Mapping[str, Any]] | None, names: Sequence[str] | None = None) -> str:
    """剧本逐集撰写时的 <relationships> 段；没有关系就是空串，提示词与原来一字不差。"""
    rows = _relation_rows(relationships, names)
    if not rows:
        return ""
    return "\n<relationships>\n" + prompt_data.text(_CAST, "plan_rule") + "\n" + "\n".join(rows) + "\n</relationships>\n"


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
    cast: Mapping[str, Any] | None = None,
    adaptation: Mapping[str, Any] | None = None,
    opens_series: bool = False,
    earlier_state: Sequence[str] = (),
) -> str:
    """Split a source window into episodes anchored on verbatim ``end_anchor`` snippets.

    ``cast`` is the asset inventory: its characters and relationships are settled before the ledger is planned.
    A novel is re-staged rather than cut by chapter: ``adaptation`` is its brief (see
    ``build_adaptation_prompt``), and ``opens_series`` says this window holds episode 1.
    An author's finished screenplay is extracted as before and gets neither.
    """
    is_screenplay = source_kind == "screenplay"
    overview = overview or {}
    lines: list[str] = []
    if is_screenplay:
        lines.append(_says("anchored_plan.intro_screenplay"))
    else:
        lines.append(_says("anchored_plan.intro_novel"))
    lines += ["", _says("common.project_heading"), _says("anchored_plan.creation_type")]
    if overview.get("synopsis"):
        lines.append(_says("common.synopsis_line", synopsis=neutralize_tags(overview['synopsis'])))
    if overview.get("genre"):
        lines.append(_says("common.genre_line", genre=neutralize_tags(overview['genre'])))
    lines.append(_target_volume_line(target_volume))
    lines.append(_says("anchored_plan.max_episodes", count=max_episodes))
    if remaining_episodes is not None:
        final = _says("anchored_plan.remaining_final") if window_is_final else ""
        lines.append(_says("anchored_plan.remaining", count=remaining_episodes, final=final))
    lines += _ledger_cast_lines(cast)
    if not is_screenplay:
        lines += _adaptation_ledger_lines(adaptation)
    lines += [neutralize_tags(line) for line in earlier_state]
    lines += _context_lines(context_entries)
    if instructions:
        lines += ["", USER_INSTRUCTIONS_HEADER, instructions]
    if is_screenplay:
        beats_ending = _says("anchored_plan.beats_ending_screenplay")
    else:
        beats_ending = _says("anchored_plan.beats_ending_source")
    lines += [
        "",
        _says("anchored_plan.rules_heading"),
        _says("anchored_plan.rules", beats_ending=beats_ending, names=emotion_points.names(), menu=emotion_points.menu()),
    ]
    if is_screenplay:
        lines.append(_says("anchored_plan.screenplay_anchor"))
    else:
        # 改编的账本和创作的账本守同几条：节点之间有因果、只写拍得到的事、钩子留了要兑。
        lines += [
            _says("anchored_plan.rules_novel"),
            prompt_data.text("causal_chain", "outline_rule"),
            _says("outline_plan.no_inner_life"),
            literary.hook_rule(),
            # 改编成多集时集尾卡点也换着用；升级与反转的节奏不加——事件照原文，不按日程另编。
            *series_rhythm.outline_rules(max_episodes, cadence=False),
        ]
        if opens_series:
            opening = _brief_text(adaptation, "opening")
            lines.append(_says(
                "anchored_plan.first_episode",
                informational=emotion_points.names_of_informational(),
                opening=_says("anchored_plan.first_episode_opening", opening=opening) if opening else "",
            ))
    lines.append(_says("anchored_plan.anchor_order"))
    if window_is_final:
        lines.append(_says("anchored_plan.final_window"))
    else:
        lines.append(_says("anchored_plan.partial_window"))
    if is_screenplay:
        window_heading = _says("anchored_plan.window_heading_screenplay")
    else:
        window_heading = _says("anchored_plan.window_heading_source")
    lines += ["", window_heading, "---", neutralize_tags(window), "---"]
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
    cast: Mapping[str, Any] | None = None,
    earlier_state: Sequence[str] = (),
    creation_mode: str = "drama",
) -> str:
    """Plan a contiguous run of episodes (title / hook / beats / teaser) from the director plan.

    ``earlier_state`` is the part of the cross-episode sheet older than ``context_entries``
    (see ``story_state.earlier_lasting``).
    """
    overview = overview or {}
    if first == last:
        span = _says("outline_plan.span_one", first=first)
    else:
        span = _says("outline_plan.span_many", first=first, last=last)
    lines = [
        _says("outline_plan.intro", title=neutralize_tags(title), span=span),
        "",
        _says("common.project_heading"),
        _says("outline_plan.batch", total=total, count=last - first + 1, span=span),
    ]
    if target_seconds:
        lines.append(_says("outline_plan.target", seconds=target_seconds))
    if overview.get("synopsis"):
        lines.append(_says("common.synopsis_line", synopsis=neutralize_tags(overview['synopsis'])))
    if overview.get("genre"):
        lines.append(_says("common.genre_line", genre=neutralize_tags(overview['genre'])))
    lines.extend(f"- {neutralize_tags(line)}" for line in literary.overview_lines(overview))
    # 电影短片不套连续剧的爽点公式(每集四段、相邻两集换爽法、集尾双钩子)：它的写法在创作类型的说明里。
    if creation_mode != "film" and _payoff_block(overview):
        lines.append(_PAYOFF_FORMULA)
    if _physique_block(overview):
        lines.append(_physique_block(overview).strip())
    lines += _ledger_cast_lines(cast)
    lines += [neutralize_tags(line) for line in earlier_state]
    lines += _context_lines(context_entries)
    if instructions:
        lines += ["", USER_INSTRUCTIONS_HEADER, instructions]
    lines += [
        "",
        _says("outline_plan.rules_heading"),
        _says("outline_plan.rules", names=emotion_points.names(), menu=emotion_points.menu()),
        literary.outline_rule(),
        prompt_data.text("causal_chain", "outline_rule"),
        prompt_data.text("tension", "outline_rule"),
        literary.hook_rule(),
        # 连续剧的节奏(series_rhythm.json)：集尾卡点换着用、多久升级一次、多久一次大反转。
        *series_rhythm.outline_rules(total),
        _says("outline_plan.finale", total=total),
        _says("outline_plan.no_inner_life"),
        # 剧本之初就讲清可拍性：故事节点里就不写画面文字、瞬移、形态突变(大纲质检会按这几条退回)。
        filmability.writing_rule(),
        "",
        _says("outline_plan.plan_heading"),
        "---",
        neutralize_tags(director_plan),
        "---",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- stage A: script plan


_SCENE_RULE_NOVEL = _says("script_plan.scene_rule_novel")
_SCENE_RULE_SCREENPLAY = _says("script_plan.scene_rule_screenplay")
_SCENE_RULE_OUTLINE = _says("script_plan.scene_rule_director_plan")
_UTTERANCES_NOVEL = _says("script_plan.utterances_novel")
_UTTERANCES_SCREENPLAY = _says("script_plan.utterances_screenplay")
_UTTERANCES_OUTLINE = _says("script_plan.utterances_director_plan")


def spoken_density_rule(spoken_shot_ratio: float, creation_mode: str = "drama") -> str:
    """The ask for talk-heavy episodes: how many shots must carry speech, and what kind."""
    ratio = max(0.0, min(1.0, float(spoken_shot_ratio or 0)))
    if ratio <= 0:
        return ""
    percent = int(round(ratio * 100))
    if creation_mode == "narration":
        return _says("script_plan.density_narration", percent=percent)
    return _says("script_plan.density_drama", percent=percent)


_SOURCE_TEXT_GUIDE = _says("script_plan.source_text_guide")
_VISIBLE_WORDING_RULE = _says(
    "script_plan.visible_wording_rule",
    subjective=visual_wording.subjective_examples(), fast=visual_wording.fast_motion_examples(),
)
_SOURCE_TEXT_OUTLINE = _says("script_plan.source_text_director_plan")

_CAST = "screenwriting_cast"
_PAYOFF_GENRES = prompt_data.pattern("payoff", "genres")
_PAYOFF_FORMULA = "\n".join(prompt_data.words("payoff", "formula"))


def _physique_block(overview: Mapping[str, Any] | None) -> str:
    """仙侠玄幻修真才给的修仙设定参照：体质、法宝、宗门势力(app/data/prompt/xianxia_lore.json)；别的题材是空串。"""
    overview = overview or {}
    story = " ".join(str(overview.get(key) or "") for key in ("synopsis", "world_setting", "theme"))
    return xianxia_lore.block(str(overview.get("genre") or ""), text=story)


def _payoff_block(overview: Mapping[str, Any] | None) -> str:
    """爽剧的写法只给爽剧：正剧和悬疑套打脸与杀伐会串味，所以按题材词判断，判不出来就不加。
    题材词与公式都在 ``app/data/prompt/payoff.json``。"""
    genre = str((overview or {}).get("genre") or "")
    return f"\n\n{_PAYOFF_FORMULA}" if _PAYOFF_GENRES.search(genre) else ""


_HOOK_LANDING = _says("outline.hook_landing")


def _beat_lines(beats: Sequence[Any]) -> list[str]:
    """The "story beats" label and one line per beat; nothing when there are no beats."""
    if not beats:
        return []
    return [_says("outline.beats_label"), *(f"- {neutralize_tags(beat)}" for beat in beats)]


def _outline_block(episode_outline: Mapping[str, Any] | None, next_outline: Mapping[str, Any] | None) -> str:
    parts: list[str] = []
    if episode_outline:
        lines = []
        if episode_outline.get("title"):
            lines.append(_says("outline.title", title=neutralize_tags(episode_outline['title'])))
        lines += _beat_lines(episode_outline.get("story_beats") or [])
        if episode_outline.get("hook"):
            lines.append(_says("outline.hook", hook=neutralize_tags(episode_outline['hook'])))
        if episode_outline.get("next_episode_teaser"):
            lines.append(_says("outline.teaser", teaser=neutralize_tags(episode_outline['next_episode_teaser'])))
        parts.append(_says("outline.plan_wrap", lines="\n".join(lines)))
        if episode_outline.get("hook") or episode_outline.get("next_episode_teaser"):
            parts.append(_HOOK_LANDING)
    if next_outline:
        lines = []
        if next_outline.get("title"):
            lines.append(_says("outline.next_title", title=neutralize_tags(next_outline['title'])))
        lines += _beat_lines(next_outline.get("story_beats") or [])
        parts.append(_says("outline.next_wrap", lines="\n".join(lines)))
    return ("\n\n".join(parts) + "\n\n") if parts else ""


def _story_so_far_block(
    source_kind: SourceKind, previous_outline: Mapping[str, Any] | None, sheet: Sequence[str], landing: Sequence[str],
) -> str:
    """The cross-episode sheet as one episode's plan reads it; nothing for an extracted screenplay or a first episode."""
    if source_kind == "screenplay":
        return ""
    previous: list[str] = []
    if previous_outline:
        if previous_outline.get("title"):
            previous.append(_says("outline.title", title=neutralize_tags(previous_outline['title'])))
        previous += _beat_lines(previous_outline.get("story_beats") or [])
        if previous_outline.get("hook"):
            previous.append(_says("outline.hook", hook=neutralize_tags(previous_outline['hook'])))
    return story_state.plan_block(
        sheet=[neutralize_tags(line) for line in sheet], previous_outline=previous, landing=[neutralize_tags(line) for line in landing],
    )


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
    relationships: Sequence[Mapping[str, Any]] | None = None,
    adaptation: Mapping[str, Any] | None = None,
    previous_episode_outline: Mapping[str, Any] | None = None,
    sheet: Sequence[str] = (),
    landing: Sequence[str] = (),
) -> str:
    """Stage A prompt: source (or outline) → structured shot content.

    ``spoken_shot_ratio`` (outline mode only) asks for talk-heavy episodes: that share of
    the shots must carry speech. Episodes cut from a source keep the source's own lines.
    A novel episode is re-staged: it gets the rules of adapting and what ``adaptation`` (the
    project's brief) settles; in a drama its narration becomes picture and dialogue, in a
    narrated film it stays narration.
    ``sheet`` is what the earlier episodes settled (``story_state.table_before``),
    ``previous_episode_outline`` how the last one ended and ``landing`` what this episode must
    leave behind; an author's finished screenplay is extracted as it stands and is told none of it.
    """
    durations = sorted({int(value) for value in supported_durations})
    if not durations:
        raise ValueError(_says("script_plan.no_durations"))
    if default_duration is not None and default_duration not in durations:
        raise ValueError(_says("script_plan.default_not_supported", default=default_duration, durations=durations))
    durations_str = ", ".join(str(value) for value in durations)
    max_dur = durations[-1]
    if default_duration is not None:
        base_rule = _says("script_plan.duration_default", durations=durations_str, default=default_duration, max_seconds=max_dur)
    else:
        base_rule = _says("script_plan.duration_free", durations=durations_str, max_seconds=max_dur)
    rate = speech_rate_units_per_second(language, speech_rate_override)
    unit = reading_unit_noun(language)
    lower_bound_rule = _says("script_plan.duration_lower_bound", rate=rate, unit=unit, max_seconds=max_dur)
    duration_rule = _says("script_plan.sentences", first=base_rule, second=lower_bound_rule)
    target_rule = render_episode_target_rule(episode_target_seconds, episode_shape)
    if target_rule:
        duration_rule = _says("script_plan.sentences", first=duration_rule, second=target_rule)

    if source_kind == "screenplay":
        task = _says("script_plan.task_screenplay")
        heading, tag = _says("common.heading_screenplay"), "screenplay"
        scene_rule, utter_rule, source_rule = _SCENE_RULE_SCREENPLAY, f"{_UTTERANCES_SCREENPLAY} {acting.pacing_rule(verbatim=True)}", _SOURCE_TEXT_GUIDE
        break_rule = _says("script_plan.break_rule_screenplay")
        language_rule = _says("script_plan.language_rule_screenplay", language=output_language_name())
    elif source_kind == "novel":
        task = _says("script_plan.task_novel")
        heading, tag = _says("common.heading_novel"), "novel"
        utterances = _UTTERANCES_NOVEL if creation_mode == "narration" else _says(
            "script_plan.utterances_novel_drama", limit=adaptation_limit("narrated_shots"),
        )
        scene_rule, utter_rule, source_rule = _SCENE_RULE_NOVEL, f"{utterances} {acting.delivery_rule()} {acting.pacing_rule()}", _SOURCE_TEXT_GUIDE
        break_rule = _says("script_plan.break_rule_novel")
        language_rule = _says("script_plan.language_rule_novel", language=output_language_name())
    else:
        task = _says("script_plan.task_director_plan")
        heading, tag = _says("script_plan.heading_director_plan"), "director_plan"
        density = spoken_density_rule(spoken_shot_ratio, creation_mode)
        # 创作的台词才讲写法；改编 / 提取的台词是原文的。
        scene_rule, utter_rule, source_rule = (
            f"{_SCENE_RULE_OUTLINE}{prompt_data.text('tension', 'scene_rule')}",
            (_UTTERANCES_OUTLINE + (" " + density if density else "") + " " + acting.delivery_rule() + " " + acting.pacing_rule() + " " + literary.dialogue_rule()),
            _SOURCE_TEXT_OUTLINE,
        )
        break_rule = _says("script_plan.break_rule_director_plan")
        language_rule = _says("script_plan.language_rule_director_plan", language=output_language_name())

    # 可拍性：视频提示词里不再重复的通用约束(画面文字、形态突变、瞬移、格内换装、摆拍、同人同框、画风)，写剧本时就满足。
    # 再加画面写法：不写主观评价词，非打斗动作慢而稳(词表在 visual_wording.json，校验器用同一张表)。
    # 人物知道的事要有来处(series_rhythm.json)：场记最常漏的一条。作者上传的成品剧本不加——补镜头、删台词不是提取该做的事。
    knowledge_rule = "" if source_kind == "screenplay" else series_rhythm.knowledge_rule()
    scene_rule = f"{scene_rule}{filmability.writing_rule()}{knowledge_rule}{_VISIBLE_WORDING_RULE}"
    character_names = _names(characters)
    scene_names = _names(scenes)
    prop_names = _names(props)
    # 本集写到打斗才装打戏设计规则，文戏集不占篇幅。
    fight_rules = plan_rules_for(source_text, _outline_block(episode_outline, None))
    # 没有打戏、但有渡劫、突破、御剑这类修仙奇观：给奇观的成立方式。
    fight_rules = fight_rules or spectacle_plan_rules(source_text, _outline_block(episode_outline, None))
    fight_block = f"\n{fight_rules}" if fight_rules else ""
    emotion_rule = _says("script_plan.emotion_rule", names=emotion_points.names(), menu=emotion_points.menu())
    # 题眼台词：改编 / 提取只选哪一句是，创作才讲怎么写。
    key_line_rule = literary.key_line_rule(authored=source_kind == "outline")
    none_yet = _says("common.none_yet")
    return _says(
        "script_plan.body",
        task=task,
        language_rule=language_rule,
        pacing=pacing_for(creation_mode),
        overview=_overview_block(overview),
        payoff="" if creation_mode == "film" else _payoff_block(overview),
        physique=_physique_block(overview),
        style=neutralize_tags(style),
        characters=_format_assets_with_desc(characters),
        relationships=_relationships_block(relationships, list(characters)),
        scenes=_format_name_list(scenes),
        props=_format_name_list(props),
        heading=heading,
        tag=tag,
        source=neutralize_tags(source_text),
        outline=_story_so_far_block(source_kind, previous_episode_outline, sheet, landing) + _outline_block(episode_outline, next_episode_outline),
        adaptation=_adaptation_plan_block(adaptation, episode) if source_kind == "novel" else "",
        episode=episode,
        duration_rule=duration_rule,
        break_rule=break_rule,
        emotion_rule=emotion_rule,
        key_line_rule=key_line_rule,
        subtext_rule=acting.subtext_rule(),
        character_names=", ".join(character_names) or none_yet,
        scene_names=", ".join(scene_names) or none_yet,
        prop_names=", ".join(prop_names) or none_yet,
        scene_rule=scene_rule,
        source_rule=source_rule,
        utter_rule=utter_rule,
        fight_block=fight_block,
    )


# --------------------------------------------------------------------------- stage B: visual layer


# 不写主观评价词、非打斗动作慢而稳：词取自 visual_wording.json，与分镜内容的提示用同一张表。
_SCENE_WRITING_GUIDE = _says("visual.scene_writing_guide", subjective=visual_wording.subjective_examples())
_ACTION_WRITING_GUIDE = _says("visual.action_writing_guide", fast=visual_wording.fast_motion_examples())
_CAMERA_GUIDE = _says("visual.camera_guide")
_LIGHTING_GUIDE = _says("visual.lighting_guide")
_AMBIANCE_GUIDE = _says("visual.ambiance_guide")
_AMBIANCE_AUDIO_GUIDE = _says("visual.ambiance_audio_guide")


def render_scene_content_for_visual(content_scenes: Sequence[Mapping[str, Any]]) -> str:
    if not content_scenes:
        return _says("visual.no_content")
    nothing = _says("visual.nothing")
    blocks: list[str] = []
    for scene in content_scenes:
        if not isinstance(scene, Mapping):
            continue
        sid = neutralize_tags(scene.get("scene_id") or "?")
        duration = scene.get("duration_seconds")
        lines = [f"### {sid}" + (_says("visual.shot_duration", duration=duration) if duration else "")]
        if scene.get("setting"):
            lines.append(_says("visual.shot_setting", setting=neutralize_tags(scene.get('setting'))))
        cast = [item for item in (scene.get("characters_in_scene") or []) if isinstance(item, str)]
        scene_refs = [item for item in (scene.get("scenes") or []) if isinstance(item, str)]
        prop_refs = [item for item in (scene.get("props") or []) if isinstance(item, str)]
        lines.append(_says(
            "visual.shot_assets",
            characters=neutralize_tags(', '.join(cast) or nothing),
            scenes=neutralize_tags(', '.join(scene_refs) or nothing),
            props=neutralize_tags(', '.join(prop_refs) or nothing),
        ))
        description = neutralize_tags(scene.get('scene_description') or _says("visual.no_description"))
        lines.append(_says("visual.shot_description", description=description.replace(chr(10), chr(10) + '  ')))
        utterances = [item for item in (scene.get("utterances") or []) if isinstance(item, Mapping)]
        if utterances:
            lines.append(_says("visual.utterances_label"))
            for utterance in utterances:
                text = neutralize_tags(utterance.get("text") or "")
                if utterance.get("kind") == "dialogue":
                    lines.append(_says("visual.dialogue_line", speaker=neutralize_tags(utterance.get('speaker') or ''), text=text))
                else:
                    lines.append(_says("visual.voiceover_line", text=text))
        if scene.get("source_text"):
            lines.append(_says("visual.source_anchor", source=neutralize_tags(scene.get('source_text')).replace(chr(10), chr(10) + '  ')))
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
    creation_mode: str = "drama",
) -> str:
    """Stage B prompt: fixed shot content → image_prompt / video_prompt per scene_id."""
    return _says(
        "visual.body",
        language=output_language_name(),
        pacing=pacing_for(creation_mode),
        overview=_overview_block(overview),
        style=neutralize_tags(style),
        style_description=neutralize_tags(style_description),
        aspect_ratio=aspect_ratio,
        aspect_desc=_aspect_desc(aspect_ratio),
        characters=_format_assets_with_desc(characters),
        scenes=_format_assets_with_desc(scenes),
        props=_format_assets_with_desc(props),
        shots=render_scene_content_for_visual(content_scenes),
        episode=episode,
        scene_guide=_SCENE_WRITING_GUIDE,
        # 具名光型(light_setups.json)：按本批分镜内容挑出用得上的几条，连同不能叠的组合和防翻车的写法。
        lighting_guide=_LIGHTING_GUIDE + light_setups.guide(light_setups.content_of(content_scenes)),
        kelvin_guide=prompt_data.text('clip_prompt', 'light_kelvin_guide'),
        ambiance_guide=_AMBIANCE_GUIDE,
        action_guide=_ACTION_WRITING_GUIDE,
        camera_guide=_CAMERA_GUIDE,
        audio_guide=_AMBIANCE_AUDIO_GUIDE,
        fight_block=_fight_visual_block(content_scenes),
    )


# --------------------------------------------------------------------------- prose body


_PROSE_EXAMPLE = _says("prose.example")


def _prose_literary_rules(first: int) -> str:
    """母题留白、结尾落在物上，从第 ``first`` 条起编号。"""
    return "\n".join(f"{first + index}. {rule}" for index, rule in enumerate(literary.prose_rules()))


def _prose_length_rule(shot_count: int, language: str | None) -> str:
    unit = reading_unit_noun(language)
    low_per_shot, high_per_shot = (int(value) for value in _table("prose.length_per_shot"))
    low, high = low_per_shot * max(1, shot_count), high_per_shot * max(1, shot_count)
    return _says("prose.length_rule", low=low, high=high, unit=unit)


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
    relationships: Sequence[Mapping[str, Any]] | None = None,
) -> str:
    """Prose stage prompt: the fixed shot content of one episode → its 小说体正文.

    ``previous_ending`` is the tail of the previous episode: its prose when that is
    already written, else (``previous_is_plan``) its last shots told plainly, so
    episodes can be told side by side and still open where the last one closed.
    """
    if previous_is_plan:
        previous_label = _says("prose.previous_label_plan")
    else:
        previous_label = _says("prose.previous_label_prose")
    previous_block = (
        _says("prose.previous_block", label=previous_label, ending=neutralize_tags(previous_ending))
        if previous_ending.strip() else ""
    )
    outline = episode_outline or {}
    outline_lines = [_says("outline.title", title=neutralize_tags(outline['title']))] if outline.get("title") else []
    outline_lines += _beat_lines(outline.get("story_beats") or [])
    if outline.get("hook"):
        outline_lines.append(_says("outline.hook", hook=neutralize_tags(outline['hook'])))
    outline_block = _says("prose.outline_wrap", lines="\n".join(outline_lines)) if outline_lines else ""
    return _says(
        "prose.body",
        episode=episode,
        overview=_overview_block(overview),
        style=neutralize_tags(style),
        characters=_format_assets_with_desc(characters),
        relationships=_relationships_block(relationships, list(characters)),
        outline=outline_block,
        previous=previous_block,
        shots=render_scene_content_for_visual(content_scenes),
        literary_rules=_prose_literary_rules(5),
        length_rule=_prose_length_rule(len(content_scenes), language),
        language=output_language_name(),
        example=_PROSE_EXAMPLE,
    )


__all__ = [
    "USER_INSTRUCTIONS_HEADER",
    "adaptation_limit",
    "append_user_instructions",
    "build_adaptation_prompt",
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
