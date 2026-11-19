from dataclasses import dataclass
from statistics import median

import pymupdf

from app.schemas.chart import Box
from app.services.file_resolver import ChartError


@dataclass(frozen=True)
class TextLine:
    text: str
    box: Box
    size: float
    vertical: bool


def open_pdf(content: bytes) -> pymupdf.Document:
    try:
        document = pymupdf.open(stream=content, filetype="pdf")
    except (RuntimeError, ValueError) as error:
        raise ChartError("The PDF could not be opened.") from error
    if document.needs_pass or not document.page_count:
        document.close()
        raise ChartError("The PDF is encrypted or empty.")
    return document


def page_at(document: pymupdf.Document, number: int) -> pymupdf.Page:
    if number < 1 or number > document.page_count:
        raise ChartError(f"Page number must be between 1 and {document.page_count}.")
    page = document[number - 1]
    if page.rect.width > 3000 or page.rect.height > 3000:
        raise ChartError("The selected PDF page is too large to process.")
    # Use a common coordinate system for rendered pixels and PDF text geometry.
    if page.rotation:
        page.set_rotation(0)
    return page


def text_lines(page: pymupdf.Page) -> list[TextLine]:
    result = []
    for block in page.get_text(
        "dict", flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES
    )["blocks"]:
        for line in block.get("lines", []):
            spans = line["spans"]
            text = "".join(span["text"] for span in spans).strip()
            if text:
                result.append(
                    TextLine(
                        text[:1000],
                        tuple(line["bbox"]),
                        median(span["size"] for span in spans),
                        abs(line["dir"][0]) < 0.25,
                    )
                )
    return sorted(result, key=lambda line: (line.box[1], line.box[0]))


def render(page: pymupdf.Page, box: Box, pixels: int = 1400) -> bytes:
    region = pymupdf.Rect(box) & page.rect
    zoom = min(3, pixels / max(region.width, region.height))
    return page.get_pixmap(
        matrix=pymupdf.Matrix(zoom, zoom),
        clip=region,
        alpha=False,
        colorspace=pymupdf.csRGB,
    ).tobytes("png")
