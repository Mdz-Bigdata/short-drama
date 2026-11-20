# -*- coding: utf-8 -*-
"""The drawing and the ffmpeg of film finishing: styled subtitles, the title card on a frame, the grade, the ending card.

:mod:`app.core.film_finishing` decides what a film's finishing settings are; this module turns the parts the
compositor is told about into PNGs and short silent segments, with PIL and local ffmpeg only. It is reached from
:func:`app.core.media_compositor.compose_film` only when a film has finishing settings, so a film without any goes
through the compositor's own code untouched.

Like the compositor, nothing here raises into the render: a part that cannot be made returns ``None`` / ``False`` /
``""`` and the caller falls back to the plain card, the default subtitle or no grade.
"""

from __future__ import annotations

import logging
import math
import os
import subprocess
from collections.abc import Mapping
from functools import lru_cache
from typing import Any, Optional

from app.core import film_finishing, prompt_data
from app.core import media_compositor as mc

logger = logging.getLogger("app.core.film_finishing_render")

_DATA = "film_finishing"


def _table(key: str) -> Any:
    return prompt_data.value(_DATA, key)


def _rgb(values: Any) -> tuple[int, int, int]:
    red, green, blue = (int(part) for part in values)
    return red, green, blue


# ---------------------------------------------------------------------------- subtitles


def render_subtitle_png(text: str, out_path: str, style: Mapping[str, Any] | None = None) -> bool:
    """A subtitle as a transparent full-frame PNG in the film's subtitle style.

    With the default style the picture is the compositor's own ``_render_subtitle_png``, pixel for pixel.
    """
    font_path = mc._font_path()
    if not font_path:
        return False
    try:
        from PIL import Image, ImageDraw, ImageFont

        look = film_finishing.subtitle_metrics(style, height=mc.OUT_H)
        font = ImageFont.truetype(font_path, look["font_px"])
        image = Image.new("RGBA", (mc.OUT_W, mc.OUT_H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        lines = mc.wrap_subtitle(
            text, lambda line: len(line) <= look["max_chars"] and draw.textlength(line, font=font) <= mc.OUT_W - look["side_margin"],
        )[: mc.SUBTITLE_MAX_LINES]
        if not lines:
            image.save(out_path)
            return True
        line_height = look["line_height"]
        top = mc.OUT_H - look["bottom_safe"] - line_height * len(lines)
        spread = (-look["outline_px"], 0, look["outline_px"]) if look["outline_px"] else ()
        for index, line in enumerate(lines):
            width = draw.textlength(line, font=font)
            x = (mc.OUT_W - width) / 2
            y = top + index * line_height
            draw.rectangle([x - look["box_pad_x"], y - look["box_top"], x + width + look["box_pad_x"], y + look["box_bottom"]],
                           fill=(0, 0, 0, look["box_alpha"]))
            mid = y + look["text_mid"]
            for dx in spread:
                for dy in spread:
                    if dx or dy:
                        draw.text((x + dx, mid + dy), line, font=font, fill=(0, 0, 0, 255), anchor="lm")
            draw.text((x, mid), line, font=font, fill=(*look["color"], 255), anchor="lm")
        image.save(out_path)
        return True
    except Exception as exc:
        logger.warning("[Finishing] styled subtitle failed: %s", str(exc)[:160])
        return False


# ---------------------------------------------------------------------------- the title card


class _Painter:
    """Draws the card's text either straight onto an opaque picture or as a transparent layer to lay over a moving one.

    Straight drawing is what the compositor's own title card does. The layer is built shape by shape with real
    alpha compositing, so its soft edges carry the ink's colour and no dark fringe shows over a bright frame.
    """

    def __init__(self, size: tuple[int, int], base: Any = None):
        from PIL import Image, ImageDraw

        self._image_module = Image
        self._draw_module = ImageDraw
        self.layered = base is None
        self.image = Image.new("RGBA", size, (0, 0, 0, 0)) if base is None else base
        self.measure = ImageDraw.Draw(self.image)

    def _ink(self, fill: tuple[int, int, int], paint: Any) -> None:
        if not self.layered:
            paint(self.measure, fill)
            return
        mask = self._image_module.new("L", self.image.size, 0)
        paint(self._draw_module.Draw(mask), 255)
        ink = self._image_module.new("RGBA", self.image.size, (*fill, 255))
        ink.putalpha(mask)
        self.image = self._image_module.alpha_composite(self.image, ink)

    def text(self, xy: tuple[float, float], text: str, font: Any, fill: tuple[int, int, int]) -> None:
        self._ink(fill, lambda draw, colour: draw.text(xy, text, font=font, fill=colour))

    def rectangle(self, box: list[float], fill: tuple[int, int, int]) -> None:
        self._ink(fill, lambda draw, colour: draw.rectangle(box, fill=colour))


def _title_lines(title: str, font: Any, measure: Any) -> list[str]:
    card = _table("card")
    lines, current = [], ""
    for ch in (title or mc.UNTITLED_FILM).strip():
        if measure.textlength(current + ch, font=font) > mc.OUT_W - card["title_side_margin"] and current:
            lines.append(current)
            current = ch
        else:
            current += ch
    if current:
        lines.append(current)
    return lines[: int(card["title_max_lines"])]


def title_characters(title: str) -> int:
    """How many characters of the title the card shows (it keeps three lines), for the reveal's steps."""
    font_path = mc._font_path()
    if not font_path:
        return 0
    from PIL import Image, ImageDraw, ImageFont

    measure = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    return sum(len(line) for line in _title_lines(title, ImageFont.truetype(font_path, int(_table("card")["title_font_px"])), measure))


def paint_title(painter: _Painter, title: str, *, upto: Optional[int] = None) -> None:
    """The title card's rule, title and tagline, laid out as ``media_compositor._render_title_png`` lays them out.

    ``upto`` shows only the first that many characters (each where it sits in the full title), for the reveal.
    """
    from PIL import ImageFont

    card = _table("card")
    font_path = mc._font_path()
    big = ImageFont.truetype(font_path, int(card["title_font_px"]))
    small = ImageFont.truetype(font_path, int(card["tagline_font_px"]))
    measure = painter.measure
    lines = _title_lines(title, big, measure)
    line_height = card["title_line_height"]
    total = line_height * len(lines)
    top = (mc.OUT_H - total) / 2 - card["block_lift"]
    painter.rectangle([mc.OUT_W / 2 - card["rule_half_width"], top - card["rule_above"],
                       mc.OUT_W / 2 + card["rule_half_width"], top - card["rule_above"] + card["rule_thickness"]], _rgb(card["rule"]))
    shadow = card["shadow_px"]
    left = upto
    for index, line in enumerate(lines):
        x = (mc.OUT_W - measure.textlength(line, font=big)) / 2
        y = top + index * line_height
        shown = line if left is None else line[: max(0, left)]
        if left is not None:
            left -= len(line)
        if not shown:
            continue
        for dx in (-shadow, shadow):
            for dy in (-shadow, shadow):
                painter.text((x + dx, y + dy), shown, big, _rgb(card["shadow"]))
        painter.text((x, y), shown, big, _rgb(card["text"]))
    tagline = mc._title_tagline()
    painter.text(((mc.OUT_W - measure.textlength(tagline, font=small)) / 2, top + total + card["tagline_gap"]), tagline, small,
                 _rgb(card["tagline"]))


def _plain_card() -> Any:
    from PIL import Image

    return Image.new("RGB", (mc.OUT_W, mc.OUT_H), _rgb(_table("card")["background"]))


def _run(command: list[str], timeout: int = 90) -> None:
    subprocess.run(command, check=True, timeout=timeout, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def background_image(ff: str, work: str, background: Mapping[str, Any]) -> Any:
    """The chosen moment of the chosen clip, filling the frame, blurred a little and dimmed so the title reads; else ``None``."""
    from PIL import Image, ImageFilter, ImageOps

    rule = _table("title")["background"]
    source = os.path.join(work, "title_source.mp4")
    if not mc._download(str(background.get("video_url") or ""), source):
        return None
    seconds = mc._probe_duration(source) or 0.0
    at = max(0.0, float(background.get("at") or 0.0))
    if seconds > 0:
        at = min(at, max(0.0, seconds - float(rule["end_margin_seconds"])))
    frame = os.path.join(work, "title_frame.png")
    for moment in dict.fromkeys((at, 0.0)):
        try:
            _run([ff, "-y", "-ss", f"{moment:.3f}", "-i", source, "-frames:v", "1", frame], timeout=60)
        except Exception:
            continue
        if os.path.isfile(frame) and os.path.getsize(frame) > 0:
            break
    else:
        return None
    with Image.open(frame) as opened:
        picture = ImageOps.fit(opened.convert("RGB"), (mc.OUT_W, mc.OUT_H), Image.LANCZOS)
    if rule["blur_radius"]:
        picture = picture.filter(ImageFilter.GaussianBlur(float(rule["blur_radius"])))
    return Image.blend(picture, Image.new("RGB", picture.size, (0, 0, 0)), float(rule["dim"]))


def _zoom_filter(seconds: float) -> str:
    rule = _table("title")["zoom"]
    frames = max(1, int(round(seconds * mc.OUT_FPS)))
    over = int(rule["oversample"])
    return (f"scale={mc.OUT_W * over}:{mc.OUT_H * over},"
            f"zoompan=z='1+{float(rule['amount']):.4f}*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d=1:s={mc.OUT_W}x{mc.OUT_H}:fps={mc.OUT_FPS},setsar=1")


def _encode(ff: str, inputs: list[str], seconds: float, out: str, *, vf: str = "", graph: str = "", label: str = "") -> None:
    command = [ff, "-y", *inputs, "-t", f"{seconds}"]
    command += ["-filter_complex", graph, "-map", label] if graph else ["-vf", vf]
    _run([*command, "-r", str(mc.OUT_FPS), "-c:v", "libx264", "-pix_fmt", "yuv420p", out])


def title_segment(ff: str, work: str, title: str, spec: Mapping[str, Any] | None) -> Optional[str]:
    """The title card as a silent segment of ``TITLE_DUR`` seconds, on the chosen frame and with the chosen animation.

    ``None`` when it cannot be made (no font, ffmpeg refused): the compositor then draws its plain card.
    A background that cannot be fetched leaves the dark card, still animated as asked.
    """
    if not spec or not mc._font_path():
        return None
    try:
        animation = str(spec.get("animation") or "")
        seconds = float(mc.TITLE_DUR)
        size = (mc.OUT_W, mc.OUT_H)
        still = ["-loop", "1", "-framerate", str(mc.OUT_FPS)]
        plain = f"scale={mc.OUT_W}:{mc.OUT_H},setsar=1"
        out = os.path.join(work, "seg_title.mp4")
        backdrop = background_image(ff, work, spec["background"]) if spec.get("background") else None
        if backdrop is None and spec.get("background"):
            logger.warning("[Finishing] title background frame unavailable; using the plain card")
        base = backdrop if backdrop is not None else _plain_card()

        if animation == "reveal":
            total = title_characters(title)
            steps = max(1, min(total, int(_table("title")["reveal"]["max_steps"])))
            inputs, graph = [], [f"[0:v]{plain}[r1]"]
            for step in range(1, steps + 1):
                card = base.copy()
                paint_title(_Painter(size, card), title, upto=math.ceil(total * step / steps))
                path = os.path.join(work, f"title_reveal_{step}.png")
                card.save(path)
                inputs += [*still, "-i", path] if step == 1 else ["-i", path]
                if step > 1:
                    start = float(_table("title")["reveal"]["seconds"]) * (step - 1) / steps
                    graph.append(f"[r{step - 1}][{step - 1}:v]overlay=0:0:enable='gte(t,{start:.3f})'[r{step}]")
            _encode(ff, inputs, seconds, out, graph=";".join(graph), label=f"[r{steps}]")
        elif animation == "zoom" and backdrop is not None:
            # The frame behind moves, the title does not: the title is its own layer on top.
            backdrop_path, text_path = os.path.join(work, "title_backdrop.png"), os.path.join(work, "title_text.png")
            backdrop.save(backdrop_path)
            layer = _Painter(size)
            paint_title(layer, title)
            layer.image.save(text_path)
            _encode(ff, [*still, "-i", backdrop_path, "-i", text_path], seconds, out,
                    graph=f"[0:v]{_zoom_filter(seconds)}[b];[b][1:v]overlay=0:0[v]", label="[v]")
        else:
            card_path = os.path.join(work, "title_card.png")
            paint_title(_Painter(size, base), title)
            base.save(card_path)
            # Without a frame behind it the whole card pushes in (a plain dark card has nothing to show a zoom).
            _encode(ff, [*still, "-i", card_path], seconds, out, vf=_zoom_filter(seconds) if animation == "zoom" else plain)
        return out if os.path.isfile(out) and os.path.getsize(out) > 0 else None
    except Exception as exc:
        logger.warning("[Finishing] styled title card failed, falling back to the plain card: %s", str(exc)[:160])
        return None


# ---------------------------------------------------------------------------- the ending card


def render_ending_png(text: str, out_path: str) -> bool:
    """The ending card: the user's line, centred on the same dark card as the title. Nothing else is written on it."""
    font_path = mc._font_path()
    if not font_path:
        return False
    try:
        from PIL import ImageDraw, ImageFont

        rule, card = _table("ending"), _table("card")
        image = _plain_card()
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype(font_path, int(rule["font_px"]))
        lines = mc.wrap_subtitle(text, lambda line: draw.textlength(line, font=font) <= mc.OUT_W - 2 * rule["side_margin"])[: int(rule["max_lines"])]
        top = (mc.OUT_H - rule["line_height"] * len(lines)) / 2
        shadow = card["shadow_px"]
        for index, line in enumerate(lines):
            x = (mc.OUT_W - draw.textlength(line, font=font)) / 2
            mid = top + index * rule["line_height"] + rule["line_height"] / 2
            for dx in (-shadow, shadow):
                for dy in (-shadow, shadow):
                    draw.text((x + dx, mid + dy), line, font=font, fill=_rgb(card["shadow"]), anchor="lm")
            draw.text((x, mid), line, font=font, fill=_rgb(card["text"]), anchor="lm")
        image.save(out_path)
        return True
    except Exception as exc:
        logger.warning("[Finishing] ending card drawing failed: %s", str(exc)[:160])
        return False


def ending_segment(ff: str, work: str, ending: Mapping[str, Any] | None) -> Optional[str]:
    """The ending card as a silent segment, or ``None`` when there is no line or it cannot be made (the film ends on its last shot)."""
    text = str((ending or {}).get("text") or "").strip()
    seconds = float((ending or {}).get("seconds") or 0.0)
    if not text or seconds <= 0:
        return None
    try:
        png, out = os.path.join(work, "ending.png"), os.path.join(work, "seg_ending.mp4")
        if not render_ending_png(text, png):
            return None
        _encode(ff, ["-loop", "1", "-i", png], seconds, out, vf=f"scale={mc.OUT_W}:{mc.OUT_H},setsar=1")
        return out if os.path.isfile(out) and os.path.getsize(out) > 0 else None
    except Exception as exc:
        logger.warning("[Finishing] ending card segment failed: %s", str(exc)[:160])
        return None


# ---------------------------------------------------------------------------- the grade


@lru_cache(maxsize=4)
def _filters(ff: str) -> Optional[frozenset[str]]:
    """The filters this ffmpeg build has; ``None`` when it would not say (then every filter is assumed present)."""
    try:
        listing = subprocess.run([ff, "-hide_banner", "-filters"], capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return None
    names = frozenset(parts[1] for parts in (line.split() for line in listing.splitlines()) if len(parts) >= 3 and "->" in parts[2])
    return names or None


def grade_prefix(ff: str, grade: Mapping[str, Any] | None) -> str:
    """The film-wide grade as the start of a shot's filter chain (``"eq=…,"``), or ``""`` for no grade.

    It goes before the shot is fitted and padded, so the bars beside a narrow clip and a one-frame blackout stay black,
    and subtitles and the cards are never graded. A filter this ffmpeg build lacks is left out rather than failing the film.
    """
    wanted = film_finishing.grade_filters(grade)
    if not wanted:
        return ""
    known = _filters(ff)
    kept = [text for name, text in wanted if known is None or name in known]
    if len(kept) < len(wanted):
        logger.warning("[Finishing] this ffmpeg lacks %s; that part of the grade is skipped",
                       ", ".join(name for name, _text in wanted if known is not None and name not in known))
    return ",".join(kept) + "," if kept else ""


__all__ = ["background_image", "ending_segment", "grade_prefix", "paint_title", "render_ending_png", "render_subtitle_png",
           "title_characters", "title_segment"]
