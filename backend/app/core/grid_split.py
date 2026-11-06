"""Cut a grid image (a storyboard page, a contact sheet) into its cells, trimming the borders.

Seams are found with the same separator test the character and scene sheets use, so a
white gutter is removed rather than left on the edge of a cell. Where a page has no
visible seam it is cut evenly, and cells that are blank (a page not filled to the end)
are dropped: an empty picture is no use in a pool.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageStat

from app.core.actor_sheet_cutter import _runs, _SeparatorMap

MAX_GRID_SIDE = 8
# How far from its even position a seam may be, as a share of one cell.
_SEAM_SEARCH = 0.2
# Wider than this, a smooth band is the picture's own (a sky, a wall) unless it is border-coloured.
_MAX_SEAM = 0.15
# A border is thin; anything thicker on the outside stays.
_MAX_TRIM = 0.2
_MIN_CELL_PIXELS = 16
_BLANK_STDDEV = 2.0
_LIGHT = 235
_DARK = 20
_BORDER_SHARE = 0.98

Box = tuple[int, int, int, int]


@dataclass(frozen=True)
class GridCell:
    row: int
    column: int
    box: Box
    png: bytes


class _Borders:
    """Which lines of the page are border-coloured: nearly all white, or nearly all black.

    A seam may be any smooth line, but the outside of a picture is only taken off when it is
    plainly a border: a pale sky reaching the edge of a frame is part of the frame.
    """

    def __init__(self, image: Image.Image) -> None:
        gray = image.convert("L")
        self.light = gray.point(lambda value: 255 if value >= _LIGHT else 0)
        self.dark = gray.point(lambda value: 255 if value <= _DARK else 0)

    def flags(self, box: Box, axis: str) -> list[bool]:
        left, top, right, bottom = box
        if right <= left or bottom <= top:
            return []
        size = (right - left, 1) if axis == "x" else (1, bottom - top)
        light = self.light.crop(box).resize(size, Image.Resampling.BOX).tobytes()
        dark = self.dark.crop(box).resize(size, Image.Resampling.BOX).tobytes()
        return [max(first, second) >= 255 * _BORDER_SHARE for first, second in zip(light, dark)]


def _seam(runs: list[tuple[int, int]], expected: int, radius: int, *, widest: int, border: list[bool]) -> tuple[int, int]:
    near = [
        run for run in runs
        if run[0] - radius <= expected <= run[1] + radius and (run[1] - run[0] <= widest or all(border[run[0]:run[1]]))
    ]
    if not near:
        return expected, expected
    return min(near, key=lambda run: 0 if run[0] <= expected <= run[1] else min(abs(run[0] - expected), abs(run[1] - expected)))


def _margins(flags: list[bool]) -> tuple[int, int]:
    """How many lines of border each end carries, within what can still be a border."""
    limit = len(flags) * _MAX_TRIM
    runs = _runs(flags, interior_only=False)
    lead = next((high for low, high in runs if low == 0 and high <= limit), 0)
    tail = next((high - low for low, high in runs if high == len(flags) and high - low <= limit), 0)
    return lead, tail


def _spans(separators: list[bool], border: list[bool], parts: int) -> list[tuple[int, int]]:
    """Each part's (start, end) along one axis, between the seams nearest its even edges."""
    length = len(separators)
    runs = _runs(separators, interior_only=False)
    lead, tail = _margins(border)
    start, end = lead, length - tail
    cell = length / parts
    spans = []
    previous = start
    for index in range(1, parts):
        low, high = _seam(runs, round(length * index / parts), round(cell * _SEAM_SEARCH), widest=round(cell * _MAX_SEAM), border=border)
        spans.append((previous, min(low, end)))
        previous = max(high, start)
    spans.append((previous, end))
    return spans


def _trim(borders: _Borders, box: Box) -> Box:
    """Take off whatever border this one cell still carries on each side."""
    left, top, right, bottom = box
    lead, tail = _margins(borders.flags(box, "x"))
    left, right = left + lead, right - tail
    lead, tail = _margins(borders.flags(box, "y"))
    return left, top + lead, right, bottom - tail


def _is_blank(cell: Image.Image) -> bool:
    return max(ImageStat.Stat(cell.convert("L")).stddev) < _BLANK_STDDEV


def split_grid(content: bytes, rows: int, columns: int) -> list[GridCell]:
    """The non-blank cells in reading order, as PNG. Row and column are 0-based positions in the grid."""
    if not (1 <= rows <= MAX_GRID_SIDE and 1 <= columns <= MAX_GRID_SIDE):
        raise ValueError(f"行列数必须在 1 到 {MAX_GRID_SIDE} 之间")
    if rows * columns < 2:
        raise ValueError("至少要切成两格")
    with Image.open(io.BytesIO(content)) as opened:
        image = opened.convert("RGB")
    width, height = image.size
    if width < columns * _MIN_CELL_PIXELS or height < rows * _MIN_CELL_PIXELS:
        raise ValueError(f"图片只有 {width}×{height}，切不出 {rows}×{columns} 格")
    seps = _SeparatorMap(image)
    borders = _Borders(image)
    whole: Box = (0, 0, width, height)
    y_spans = _spans(seps.separators(whole, "y"), borders.flags(whole, "y"), rows)
    x_spans = _spans(seps.separators(whole, "x"), borders.flags(whole, "x"), columns)
    cells: list[GridCell] = []
    for row, (top, bottom) in enumerate(y_spans):
        for column, (left, right) in enumerate(x_spans):
            if right - left < _MIN_CELL_PIXELS or bottom - top < _MIN_CELL_PIXELS:
                continue
            box = _trim(borders, (left, top, right, bottom))
            if box[2] - box[0] < _MIN_CELL_PIXELS or box[3] - box[1] < _MIN_CELL_PIXELS:
                continue
            cell = image.crop(box)
            if _is_blank(cell):
                continue
            buffer = io.BytesIO()
            cell.save(buffer, format="PNG", optimize=True)
            cells.append(GridCell(row=row, column=column, box=box, png=buffer.getvalue()))
    if not cells:
        raise ValueError("这张图切不出有内容的格子")
    return cells
