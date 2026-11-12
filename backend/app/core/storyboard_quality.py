"""Deterministic prompt compilation and storyboard continuity checks."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.core import prompt_data
from app.core.actor_sheet_layout import ACTOR_SHEET_LAYOUT, FULL_BODY_PROPORTION_RULE
from app.core.face_card import card_negatives, parse_face_card, render_face_card
from app.schema.production import NineGridStoryboard, StoryboardPanel


class ContinuityIssue(BaseModel):
    panel_index: int = Field(ge=1, le=9)
    code: str
    message: str


class StoryboardContinuityReport(BaseModel):
    passed: bool
    issues: list[ContinuityIssue]


# The sheet and nine-grid prompt sentences, the cell captions and the continuity messages:
# app/data/prompt/storyboard_quality.json.
_WORDING = "storyboard_quality"


def _says(key: str, /, **values: object) -> str:
    """A sentence of the table's ``says``, filled in (``key`` is positional: a template may name a ``{key}``).

    A template written as an array of lines is one sentence, its lines joined end to end.
    """
    template = prompt_data.load(_WORDING)["says"][key]
    if isinstance(template, list):
        template = "".join(str(line) for line in template)
    return str(template).format(**values)


def _rows(rows: list[list[str]]) -> tuple[tuple[str, ...], ...]:
    return tuple(tuple(str(caption) for caption in row) for row in rows)


# 每个子格下方的编号中文标注(画在图上，让每一格自带说明)。顺序与 ACTOR_SHEET_LAYOUT 的格子顺序一致。
_ELEMENT_CAPTIONS = _rows(prompt_data.value(_WORDING, "element_captions"))
_DETAIL_CAPTIONS = _rows(prompt_data.value(_WORDING, "detail_captions"))


def _numbered(rows: tuple[tuple[str, ...], ...]) -> list[str]:
    """把各行标注编成「第一行：1. A、2. B；」的连续编号。"""
    lines, number = [], 1
    ordinals = prompt_data.text(_WORDING, "row_ordinals")
    separator = prompt_data.text(_WORDING, "list_separator")
    for index, row in enumerate(rows):
        items = []
        for caption in row:
            items.append(_says("numbered_item", number=number, caption=caption))
            number += 1
        lines.append(_says("numbered_row", ordinal=ordinals[index], items=separator.join(items)))
    return lines


def _identity_clause(identity_dna: str) -> tuple[str, str]:
    """身份 DNA 按人物资产卡分层写进设定集，返回 (正向身份句, 追加的禁止项)。

    设定集同时有脸部特写和全身格，所以五层全写，再告诉模型哪层落在哪些格；
    否定片段和防混血锚点进禁止项，不留在正向描述里。没解析出长相层的 DNA 原样保留。
    """
    card = parse_face_card(identity_dna)
    if not card.has_face_layers:
        return _says("identity_dna", dna=identity_dna), ""
    clause = _says("identity_card", card=render_face_card(card))
    negatives = card_negatives(card)
    separator = prompt_data.text(_WORDING, "list_separator")
    return clause, _says("card_exclusions", items=separator.join(negatives)) if negatives else ""


def build_actor_sheet_prompt(name: str, identity_dna: str, visual_style: str, *, era_note: str = "") -> str:
    """把数字演员设定集写成一段可执行的画面描述。

    版面数字、网格形状和三栏标题全部取自 ACTOR_SHEET_LAYOUT，切图器读的是同一份常量。
    结构按用户给定的设定集提示词组织：全局画布 → 左栏主肖像 → 中栏全身与元素(中左全身立绘、
    中右三视图与 2×4 元素) → 右栏 4×3 细节矩阵 → 全局排版规则；每个子格下方一行编号中文标注。
    身份 DNA 按 face_card 的人物资产卡分层；era_note(时代服饰约束)不参与分层，原样跟在后面。

    刻意只写画面本身：没有 markdown、没有元指令、不引用任何文档。
    原因见 model_gateway.generate_character_sheet 的注释——把方法论文档塞进文生图
    模型会被内容审核判 content_policy_violation，整批设定图直接全灭。
    """
    identity_clause, card_exclusions = _identity_clause(identity_dna)
    layout = ACTOR_SHEET_LAYOUT
    portrait_title, middle_title, details_title = (
        region.title for region in layout.regions if region.title
    )
    left = round(layout.left_portrait_width * 100)
    middle = round(layout.middle_width * 100)
    right = round(layout.right_details_width * 100)
    mid_left = round(layout.middle_inner_split * 100)
    mid_right = 100 - mid_left
    three_rows, three_columns = layout.three_view_grid
    element_rows, element_columns = layout.element_grid
    detail_rows, detail_columns = layout.detail_matrix_grid
    row_separator = prompt_data.text(_WORDING, "row_separator")
    element_lines = row_separator.join(_numbered(_ELEMENT_CAPTIONS))
    detail_lines = row_separator.join(_numbered(_DETAIL_CAPTIONS))
    return _says(
        "actor_sheet",
        name=name, aspect=layout.aspect_ratio_label,
        portrait_title=portrait_title, middle_title=middle_title, details_title=details_title,
        left=left, middle=middle, right=right, mid_left=mid_left, mid_right=mid_right,
        three_rows=three_rows, three_columns=three_columns, proportion_rule=FULL_BODY_PROPORTION_RULE,
        element_rows=element_rows, element_columns=element_columns, element_cells=element_rows * element_columns,
        element_lines=element_lines,
        detail_rows=detail_rows, detail_columns=detail_columns, detail_cells=detail_rows * detail_columns,
        detail_lines=detail_lines,
        identity_clause=identity_clause, era_note=era_note, visual_style=visual_style, card_exclusions=card_exclusions,
    )


def build_nine_grid_prompt(board: NineGridStoryboard) -> str:
    """Compile a board to a single precise 3x3 generation prompt."""
    assets = board.assets
    separator = prompt_data.text(_WORDING, "list_separator")
    lines = [
        _says("grid_title", title=board.title),
        _says("grid_page", page=board.page_number, pages=board.total_pages, count=len(board.panels), empty=board.empty_slots),
        _says("grid_beats"),
        _says("grid_rhythm", rhythm=board.rhythm_profile),
        _says("grid_purpose"),
        _says("grid_characters", items=separator.join(assets.characters)),
        _says("grid_scenes", items=separator.join(assets.scenes)),
        _says("grid_props", items=separator.join(assets.props)),
        _says("grid_effects", items=separator.join(assets.effects)),
        _says("grid_consistency"),
    ]
    for panel in board.panels:
        mode_label = prompt_data.value(_WORDING, "generation_modes")[panel.generation_mode]
        lines.append(_says(
            "grid_panel",
            index=panel.index, purpose=panel.shot_purpose, beat=panel.story_beat, duration=panel.duration_seconds,
            characters=separator.join(panel.characters), shot_size=panel.shot_size,
            lens_mm=panel.lens_mm, aperture=panel.aperture,
            angle=panel.camera_angle, movement=panel.camera_movement, reason=panel.camera_reason,
            composition=panel.composition, axis=panel.action_axis, eyeline=panel.eyeline,
            scene=panel.scene, action=panel.subject_action, expression=panel.expression,
            props=separator.join(panel.props), effects=separator.join(panel.effects),
            blocking=panel.blocking, lighting=panel.lighting, mode=mode_label,
            start=panel.start_state, end=panel.end_state,
            sound=panel.sound, edit_in=panel.edit_in, edit_out=panel.edit_out,
            continuity_in=panel.continuity_in or prompt_data.text(_WORDING, "establishing"),
            continuity_out=panel.continuity_out,
        ))
    for index in range(len(board.panels) + 1, 10):
        lines.append(_says("grid_empty_slot", index=index))
    lines.append(_says("grid_closing"))
    return "\n".join(lines)


def validate_storyboard_continuity(
    panels: list[StoryboardPanel],
) -> StoryboardContinuityReport:
    issues: list[ContinuityIssue] = []
    for panel in panels:
        if panel.index > 1 and not panel.continuity_in.strip():
            issues.append(ContinuityIssue(
                panel_index=panel.index,
                code="missing_continuity_in",
                message=_says("missing_continuity_in"),
            ))
        if not panel.props:
            issues.append(ContinuityIssue(
                panel_index=panel.index,
                code="missing_prop_state",
                message=_says("missing_prop_state"),
            ))
        if not panel.effects:
            issues.append(ContinuityIssue(
                panel_index=panel.index,
                code="missing_effect_state",
                message=_says("missing_effect_state"),
            ))
    return StoryboardContinuityReport(passed=not issues, issues=issues)
