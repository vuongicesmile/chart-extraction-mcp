import re
from statistics import median

from app.schemas.chart import Box, ChartContext
from app.services.pdf_parser import TextLine

CAPTION = re.compile(
    r"^(?:(?:fig(?:ure)?\.?|chart|biểu đồ|hình)\s*(?:[\d.]+\s*)?[:.–-]?)(?=\s|\d|$)",
    re.IGNORECASE,
)
HEADING = re.compile(r"^(?:\d+(?:\.\d+)*[.)]?\s+|chapter\s+|section\s+)", re.IGNORECASE)


def context_for(box: Box, lines: list[TextLine]) -> ChartContext:
    x0, y0, x1, y1 = box
    horizontal = [
        line
        for line in lines
        if not line.vertical and line.box[2] >= x0 - 45 and line.box[0] <= x1 + 45
    ]
    captions = [
        line
        for line in horizontal
        if CAPTION.search(line.text)
        and (0 <= line.box[1] - y1 <= 90 or 0 <= y0 - line.box[3] <= 70)
    ]
    caption = min(
        captions,
        key=lambda line: min(abs(line.box[1] - y1), abs(y0 - line.box[3])),
        default=None,
    )
    normal_size = (
        median(
            (line.size for line in horizontal),
        )
        if horizontal
        else 0
    )
    headings = [
        line
        for line in horizontal
        if line.box[3] < y0
        and line is not caption
        and len(line.text) <= 130
        and (line.size >= normal_size + 1.5 or HEADING.match(line.text))
    ]
    heading = headings[-1] if headings else None
    prose = [
        line
        for line in horizontal
        if len(line.text) >= 35 and line not in (caption, heading) and not CAPTION.search(line.text)
    ]
    before = [line.text for line in prose if 0 <= y0 - line.box[3] <= 135][-4:]
    after = [line.text for line in prose if 0 <= line.box[1] - y1 <= 135][:4]
    return ChartContext(
        heading=heading.text if heading else None,
        caption=caption.text if caption else None,
        before=" ".join(before)[:900] or None,
        after=" ".join(after)[:900] or None,
    )
