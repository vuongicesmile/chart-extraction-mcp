import math
from collections import defaultdict
from dataclasses import dataclass

from app.schemas.chart import Box, ChartData, DataPoint

PALETTE = {
    "blue": (49, 105, 195),
    "red": (214, 65, 54),
    "green": (85, 168, 104),
    "orange": (244, 153, 56),
    "yellow": (231, 212, 55),
    "purple": (135, 85, 170),
    "pink": (220, 119, 169),
    "gray": (141, 141, 141),
    "brown": (135, 83, 50),
    "teal": (46, 153, 155),
}


@dataclass(frozen=True)
class Sector:
    x: float
    y: float
    radius: float
    angle: float
    sweep: float
    rgb: tuple[int, int, int]


def read_sector(drawing: dict) -> Sector | None:
    items = drawing["items"]
    color = drawing.get("fill")
    if not color or len(color) != 3 or not 3 <= len(items) <= 8:
        return None
    if items[0][0] != "l" or items[-1][0] != "l" or any(s[0] != "c" for s in items[1:-1]):
        return None
    center, start = items[0][1:]
    if center.distance_to(items[-1][2]) > 0.8:
        return None
    radius = start.distance_to(center)
    if radius < 20 or radius > 1400:
        return None
    tolerance = max(0.8, radius * 0.02)
    sweep = 0.0
    previous = start
    for _, left, control1, control2, right in items[1:-1]:
        mid = (left + control1 * 3 + control2 * 3 + right) / 8
        if left.distance_to(previous) > tolerance or any(
            abs(point.distance_to(center) - radius) > tolerance for point in (left, mid, right)
        ):
            return None
        a = math.atan2(left.y - center.y, left.x - center.x)
        b = math.atan2(right.y - center.y, right.x - center.x)
        angle = math.degrees(math.remainder(b - a, math.tau))
        if not 0.2 < abs(angle) <= 110 or (sweep and angle * sweep <= 0):
            return None
        sweep += angle
        previous = right
    if previous.distance_to(items[-1][1]) > tolerance:
        return None
    angle = math.degrees(math.atan2(start.y - center.y, start.x - center.x))
    rgb = tuple(round(channel * 255) for channel in color)
    return Sector(center.x, center.y, radius, angle % 360, sweep, rgb)


def find_pies(drawings: list[dict]) -> list[tuple[Box, tuple[Sector, ...]]]:
    groups = defaultdict(list)
    for drawing in drawings[:4000]:
        sector = read_sector(drawing)
        if sector:
            groups[(round(sector.x), round(sector.y), round(sector.radius))].append(sector)
    charts = []
    for wedges in groups.values():
        if not 2 <= len(wedges) <= 24 or len({w.rgb for w in wedges}) != len(wedges):
            continue
        direction = 1 if wedges[0].sweep > 0 else -1
        if any(w.sweep * direction <= 0 for w in wedges):
            continue
        ordered = sorted(wedges, key=lambda w: (w.angle * direction) % 360)
        if any(
            abs(math.remainder((a.angle + a.sweep - b.angle), 360)) > 1.5
            for a, b in zip(ordered, ordered[1:] + ordered[:1], strict=True)
        ):
            continue
        if abs(sum(abs(w.sweep) for w in ordered) - 360) > 1.5:
            continue
        x, y, r = ordered[0].x, ordered[0].y, ordered[0].radius
        charts.append(((x - r, y - r, x + r, y + r), tuple(ordered)))
    return charts


def read_pie(sectors: tuple[Sector, ...]) -> ChartData:
    hex_codes = ["#" + "".join(f"{channel:02x}" for channel in w.rgb) for w in sectors]
    names = [min(PALETTE, key=lambda label: math.dist(w.rgb, PALETTE[label])) for w in sectors]
    labels = [
        code if names.count(name) > 1 else name for name, code in zip(names, hex_codes, strict=True)
    ]
    values = [
        DataPoint(
            label=label,
            color_hex=code,
            value=round(abs(w.sweep) * 100 / 360, 2),
            evidence="sector_estimate",
        )
        for w, label, code in zip(sectors, labels, hex_codes, strict=True)
    ]
    ordered = sorted(values, key=lambda point: point.value, reverse=True)
    largest = ordered[0].label if ordered[0].value - ordered[1].value > 0.5 else None
    return ChartData(
        chart_type="pie",
        status="ok",
        method="vector",
        unit="%",
        values=values,
        largest_slice=largest,
        warnings=[
            "Percentages are geometry estimates. Labels are inferred from fill colors; "
            "legend categories were not resolved."
        ],
    )
