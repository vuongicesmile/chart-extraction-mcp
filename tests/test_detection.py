import pymupdf
import pytest
from conftest import bar_pdf

from app.services.chart_detector import detect
from app.services.file_resolver import ChartError
from app.services.pdf_parser import open_pdf, page_at, text_lines


def test_detects_vector_bar_chart_at_one_based_page():
    with open_pdf(bar_pdf(empty_first=True)) as doc:
        first = page_at(doc, 1)
        assert detect(first, text_lines(first)) == []
        page = page_at(doc, 2)
        found = detect(page, text_lines(page))
        assert len(found) == 1
        [chart] = found
        assert chart.reference.page == 2
        assert chart.reference.chart_id.startswith("p2-")
        assert chart.reference.kind == "bar"
        assert len(chart.bars) == 3
        assert detect(page, text_lines(page)) == found


def test_detects_embedded_bar_chart():
    with open_pdf(bar_pdf(raster=True)) as doc:
        page = doc[0]
        [chart] = detect(page, text_lines(page))
        assert chart.reference.kind == "bar"
        assert not chart.bars


def test_rejects_invalid_page_and_nondocument():
    with pytest.raises(ChartError, match="could not be opened"), open_pdf(b"not PDF"):
        pass
    with pymupdf.open(stream=bar_pdf(), filetype="pdf") as doc:
        with pytest.raises(ChartError, match="between 1 and 1"):
            page_at(doc, 2)
