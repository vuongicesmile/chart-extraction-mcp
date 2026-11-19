import shutil

import pytest
from conftest import bar_pdf

from app.services.chart_detector import detect
from app.services.chart_extractor import read_bars, read_raster
from app.services.pdf_parser import open_pdf, render, text_lines


@pytest.mark.parametrize(
    ("values", "printed"),
    [
        ((25, 50, 75), True),
        ((12, 57, 99), True),
        ((34, 62, 86), False),
    ],
)
def test_reads_simple_bars(values, printed):
    with open_pdf(bar_pdf(values, printed=printed)) as doc:
        page = doc[0]
        lines = text_lines(page)
        [chart] = detect(page, lines)
        result = read_bars(chart, lines)
    assert result.status == "ok"
    assert result.title == "Revenue by quarter"
    assert result.y_axis == "Revenue (USD)"
    assert result.x_axis == "Quarter"
    assert result.unit == "USD"
    assert [point.label for point in result.values] == ["Q1", "Q2", "Q3"]
    assert [point.value for point in result.values] == pytest.approx(values, abs=0.2)
    assert all(p.evidence == ("label" if printed else "axis_estimate") for p in result.values)


def test_does_not_invent_values_without_labels_or_scale(sample_pdf):
    with open_pdf(sample_pdf) as doc:
        page = doc[0]
        lines = text_lines(page)
        [chart] = detect(page, lines)
        no_numbers = [line for line in lines if not line.text.isdecimal()]
        data = read_bars(chart, no_numbers)
    assert data.status == "unreadable"
    assert all(point.value is None for point in data.values)


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="Requires Tesseract")
def test_ocr_reads_raster_chart():
    with open_pdf(bar_pdf(raster=True)) as doc:
        page = doc[0]
        [chart] = detect(page, text_lines(page))
        result = read_raster(chart, render(page, chart.reference.bbox), "eng")
    assert result.status == "ok"
    assert [point.value for point in result.values] == pytest.approx([25, 50, 75], abs=2)


def test_vision_validates_values_and_rejects_non_bar_charts():
    import asyncio
    import json

    import httpx

    from app.services.chart_extractor import read_vision
    from app.settings import Settings

    settings = Settings(
        vision_base_url="https://vision.example/v1",
        vision_api_key="test",
        vision_model="vision",
    )

    async def run(result):
        def provider(request):
            assert request.url.path == "/v1/chat/completions"
            assert request.headers["Authorization"] == "Bearer test"
            payload = json.loads(request.content)
            image = payload["messages"][0]["content"][1]["image_url"]["url"]
            assert image.startswith("data:image/png;base64,")
            return httpx.Response(
                200, json={"choices": [{"message": {"content": json.dumps(result)}}]}
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            return await read_vision(settings, b"fake crop", client)

    bar = asyncio.run(
        run(
            {
                "chart_type": "bar",
                "unit": "USD",
                "values": [{"label": "A", "value": 20}, {"label": "B", "value": None}],
            }
        )
    )
    assert bar.status == "partial"
    assert [point.evidence for point in bar.values] == ["vision", "unreadable"]
    assert bar.values[1].value is None
    non_bar = asyncio.run(run({"chart_type": "other", "values": [{"label": "A", "value": 20}]}))
    assert non_bar.status == "unsupported"
    assert not non_bar.values


def test_unsupported_pdf_or_cross_host_redirect_fails_closed(tmp_path):
    import asyncio
    from uuid import uuid4

    import httpx

    from app.services.file_resolver import ChartError, FileResolver
    from app.settings import Settings

    async def run():
        seen = []

        def handler(request):
            seen.append(request.url.host)
            return httpx.Response(307, headers={"Location": "https://elsewhere.example/file"})

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            follow_redirects=False,
        ) as client:
            settings = Settings(openwebui_url="http://webui.local", cache_path=tmp_path / "test.db")
            with pytest.raises(ChartError, match="could not return"):
                await FileResolver(settings, client).resolve(uuid4(), "Bearer token")
        assert seen == ["webui.local"]

    asyncio.run(run())
