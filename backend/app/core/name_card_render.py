# -*- coding: utf-8 -*-
"""Drawing the name cards (see character_intro): vertical text on a transparent frame the compositor lays over a clip.

One picture holds every card that shows in the same window. The name stands in a tall column next to a thin rule on
the frame's edge; the identity is a smaller column beside it, a little lower, towards the middle of the frame.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Mapping, Sequence

from app.core import character_intro, prompt_data

logger = logging.getLogger(__name__)


def _style() -> Mapping[str, Any]:
    return prompt_data.value("character_intro", "style")


def _column(draw, text: str, font, *, centre_x: float, top: float, step: float, fill, stroke_fill, stroke: int) -> float:
    """Stack ``text`` one character per row, centred on ``centre_x``; returns where the column ends."""
    for index, char in enumerate(text):
        draw.text((centre_x, top + step * index + step / 2), char, font=font, fill=fill, anchor="mm",
                  stroke_width=stroke, stroke_fill=stroke_fill)
    return top + step * len(text)


def card_width(card: Mapping[str, Any]) -> int:
    style = _style()
    width = int(style["rule_width"]) + int(style["rule_gap"]) + int(style["name_size"])
    return width + (int(style["column_gap"]) + int(style["identity_size"]) if card.get("identity") else 0)


def render(cards: Sequence[Mapping[str, Any]], out_path: str, *, width: int, height: int, font_path: str | None) -> bool:
    """Draw the cards that share one window. False when there is no font to draw with (the film goes out without them)."""
    if not font_path or not cards:
        return False
    try:
        from PIL import Image, ImageDraw, ImageFont

        style = _style()
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        top = height * float(style["top"])
        widest = max(card_width(card) for card in cards)
        for card in cards:
            name, identity = str(card.get("name") or ""), str(card.get("identity") or "")
            right = card.get("side") != "left"
            # 同一侧并排的第二个人往画面中间挪一个位置。
            offset = int(style["margin_x"]) + int(card.get("slot") or 0) * (widest + int(style["slot_gap"]))
            name_size = int(style["name_size"])
            shrink = float(style["long_name_shrink"]) if len(name) > int(style["long_name_chars"]) else 1.0
            name_font = ImageFont.truetype(font_path, int(name_size * shrink))
            identity_font = ImageFont.truetype(font_path, int(style["identity_size"]))
            name_step = name_size * shrink * float(style["name_step"])
            rule_w, rule_gap = int(style["rule_width"]), int(style["rule_gap"])
            # 从画面边缘往中间排：细竖线、姓名、身份。direction 是「往中间」的方向。
            edge = width - offset if right else offset
            direction = -1 if right else 1
            rule_x = edge + direction * rule_w / 2
            name_x = edge + direction * (rule_w + rule_gap + name_size / 2)
            identity_x = edge + direction * (rule_w + rule_gap + name_size + int(style["column_gap"]) + int(style["identity_size"]) / 2)
            bottom = _column(draw, name, name_font, centre_x=name_x, top=top, step=name_step,
                             fill=tuple(style["name_color"]), stroke_fill=tuple(style["stroke_color"]), stroke=int(style["name_stroke"]))
            draw.rectangle([rule_x - rule_w / 2, top + name_step * 0.12, rule_x + rule_w / 2, bottom - name_step * 0.12], fill=tuple(style["rule_color"]))
            if identity:
                _column(draw, identity, identity_font, centre_x=identity_x, top=top + name_size * float(style["identity_drop"]),
                        step=int(style["identity_size"]) * float(style["identity_step"]),
                        fill=tuple(style["identity_color"]), stroke_fill=tuple(style["stroke_color"]), stroke=int(style["identity_stroke"]))
        image.save(out_path)
        return True
    except Exception as error:  # a card that cannot be drawn must not cost the film
        logger.warning("[NameCard] 出场字幕渲染失败: %s", str(error)[:160])
        return False


def layers(cards: Sequence[Mapping[str, Any]] | None, work: str, index: int, *, trim_start: float, kept: float,
           width: int, height: int, font_path: str | None) -> list[tuple[str, float, float, float]]:
    """The pictures to lay over one clip: (png, start, end, fade seconds), one per window."""
    fade = float(prompt_data.value("character_intro", "timing")["fade"])
    groups: dict[tuple[float, float], list[Mapping[str, Any]]] = {}
    for card in cards or []:
        shown = character_intro.window(card, trim_start=trim_start, kept=kept)
        if shown:
            groups.setdefault(shown, []).append(card)
    out = []
    for number, ((start, end), group) in enumerate(sorted(groups.items())):
        png = os.path.join(work, f"name_{index}_{number}.png")
        if render(group, png, width=width, height=height, font_path=font_path):
            out.append((png, start, end, min(fade, (end - start) / 3)))
    return out


__all__ = ["card_width", "layers", "render"]
