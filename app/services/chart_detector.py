import hashlib
import io
import re
from collections import defaultdict
from dataclasses import dataclass
from itertools import groupby
from statistics import median

import pymupdf
from PIL import Image

from app.schemas.chart import Box, ChartContext, ChartReference
from app.services.context_linker import context_for
from app.services.pdf_parser import TextLine, render
from app.services.pie_chart import Sector, find_pies


@dataclass(frozen=True)
class DetectedChart:
    reference: ChartReference
    plot: Box
    bars: tuple[Box, ...]
    context: ChartContext
    sectors: tuple[Sector, ...] = ()


def overlaps(left: Box, right: Box) -> float:
    a, b = pymupdf.Rect(left), pymupdf.Rect(right)
    intersection = (a & b).get_area()
    return intersection / min(a.get_area(), b.get_area()) if intersection else 0


def group_bars(rectangles: list[Box], max_width: float) -> list[tuple[Box, ...]]:
    groups = defaultdict(list)
    for rect in sorted(set(rectangles)):
        x0, y0, x1, y1 = rect
        if 3 <= x1 - x0 <= max_width and y1 - y0 >= 7:
            key = round(y1 / 2)
            groups[key].append(rect)
    charts = []
    for matching in groups.values():
        for _, widths in groupby(
            sorted(matching, key=lambda r: round((r[2] - r[0]) / 3)),
            key=lambda r: round((r[2] - r[0]) / 3),
        ):
            bars = sorted(widths)
            width = median(r[2] - r[0] for r in bars)
            blocks = [[]]
            for bar in bars:
                if blocks[-1] and bar[0] - blocks[-1][-1][2] > width * 4.5:
                    blocks.append([])
                if not blocks[-1] or bar[0] >= blocks[-1][-1][2] - 0.8:
                    blocks[-1].append(bar)
            for block in blocks:
                if len(block) >= 2 and max(r[3] - r[1] for r in block) > width * 0.65:
                    charts.append(tuple(block))
    return charts


def raster_groups(png: bytes) -> tuple[list[tuple[Box, ...]], tuple[int, int]]:
    # Flat-color bars form several vertical rectangles on a common baseline.
    with Image.open(io.BytesIO(png)) as image:
        image.thumbnail((320, 240), Image.Resampling.NEAREST)
        rows = image.get_flattened_data()
        width, height = image.size
    colors = defaultdict(list)
    for y in range(height):
        x = 0
        for color, run in groupby(rows[y * width : (y + 1) * width]):
            length = sum(1 for _ in run)
            if 4 <= length <= width * 0.25 and (max(color) - min(color) > 25 or max(color) < 130):
                colors[(x, x + length, color)].append(y)
            x += length
    rectangles = []
    for (x0, x1, _), ys in colors.items():
        for _, adjacent in groupby(enumerate(ys), key=lambda pair: pair[1] - pair[0]):
            bounds = [item[1] for item in adjacent]
            if len(bounds) >= 9:
                rectangles.append((x0, bounds[0], x1, bounds[-1] + 1))
    # Different series may use different colors.
    return group_bars(rectangles, width * 0.25), (width, height)


def detect(
    page: pymupdf.Page, lines: list[TextLine], vision_enabled: bool = False
) -> list[DetectedChart]:
    drawings = page.get_drawings()
    rects = [
        tuple(item[1])
        for drawing in drawings[:4000]
        if drawing.get("fill") is not None
        for item in drawing["items"]
        if item[0] == "re"
    ][:4000]
    candidates = []
    for bars in group_bars(rects, min(100, page.rect.width * 0.24)):
        plot = (
            min(bar[0] for bar in bars),
            min(bar[1] for bar in bars),
            max(bar[2] for bar in bars),
            max(bar[3] for bar in bars),
        )
        x0, y0, x1, y1 = plot
        # Include chart text around the color fills. Prose is linked separately.
        ticks = [
            line.box[1]
            for line in lines
            if not line.vertical
            and x0 - 80 <= line.box[2] < x0
            and y0 - 90 <= line.box[1] <= y1 + 5
            and re.fullmatch(r"[+-]?[0-9][0-9,.]*[%kKmM]?", line.text)
        ]
        axis_top = min([y0, *ticks])
        zone = pymupdf.Rect(x0 - 95, axis_top - 43, x1 + 38, y1 + 42) & page.rect
        has_labels = any(
            not line.vertical
            and len(line.text) < 45
            and y1 <= line.box[1] <= y1 + 30
            and line.box[2] >= x0
            and line.box[0] <= x1
            for line in lines
        )
        if has_labels and not any(overlaps(plot, row[1]) > 0.7 for row in candidates):
            candidates.append((tuple(zone), plot, bars, "bar", ()))
    for plot, sectors in find_pies(drawings):
        x0, y0, x1, y1 = plot
        zone = pymupdf.Rect(x0 - 15, y0 - 30, x1 + 15, y1 + 12) & page.rect
        candidates.append((tuple(zone), plot, (), "pie", sectors))
    image_boxes = [pymupdf.Rect(info["bbox"]) & page.rect for info in page.get_image_info()[:24]]
    image_boxes = [rect for rect in image_boxes if rect.width >= 100 and rect.height >= 65]
    for rect in image_boxes:
        box = tuple(rect)
        if any(overlaps(box, row[0]) > 0.7 for row in candidates):
            continue
        context = context_for(box, lines)
        if raster_groups(render(page, box, 320))[0]:
            candidates.append((box, box, (), "bar", ()))
        elif context.caption or (vision_enabled and len(image_boxes) == 1):
            candidates.append((box, box, (), "candidate", ()))
    result = []
    for box, plot, bars, kind, sectors in sorted(
        candidates, key=lambda row: (row[0][1], row[0][0])
    ):
        rounded = tuple(round(point, 2) for point in box)
        locator = hashlib.sha256(repr((rounded, plot, bars)).encode()).hexdigest()[:16]
        page_no = page.number + 1
        context = context_for(rounded, lines)
        result.append(
            DetectedChart(
                ChartReference(
                    chart_id=f"p{page_no}-{locator}",
                    page=page_no,
                    bbox=rounded,
                    kind=kind,
                    caption=context.caption,
                ),
                plot,
                bars,
                context,
                sectors,
            )
        )
    return result
