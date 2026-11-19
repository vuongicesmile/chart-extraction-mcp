import io
from uuid import uuid4

import httpx
import pymupdf
import pytest
from reportlab.pdfgen import canvas
from starlette.testclient import TestClient
from test_mcp import rpc

from app.main import create_app
from app.services.chart_detector import detect
from app.services.pdf_parser import text_lines
from app.services.pie_chart import read_pie
from app.settings import Settings

COLORS = ("#3169C3", "#D65940", "#55A868")


def pie_pdf(angles):
    data = io.BytesIO()
    pdf = canvas.Canvas(data, pagesize=(640, 480))
    pdf.setFont("Helvetica", 20)
    pdf.drawString(45, 435, "Synthetic pie chart for visual PDF testing")
    start = 0
    for color, angle in zip(COLORS, angles, strict=True):
        pdf.setFillColor(color)
        pdf.wedge(185, 75, 455, 345, start, angle, stroke=0, fill=1)
        start += angle
    pdf.save()
    return data.getvalue()


@pytest.mark.parametrize(
    ("angles", "expected"), [((216, 90, 54), "blue"), ((90, 54, 216), "green")]
)
def test_same_pdf_text_different_geometry_changes_mcp_answer(tmp_path, angles, expected):
    document = pie_pdf(angles)
    with pymupdf.open(stream=document, filetype="pdf") as parsed:
        assert parsed[0].get_text().strip() == "Synthetic pie chart for visual PDF testing"

    identifier = str(uuid4())

    def upstream(request):
        if request.url.path == "/api/v1/auths/":
            return httpx.Response(200, json={"id": "reader"})
        assert request.url.path == f"/api/v1/files/{identifier}/content"
        return httpx.Response(200, content=document)

    settings = Settings(
        openwebui_url="http://webui.local",
        cache_path=tmp_path / "cache.sqlite3",
        allowed_hosts="testserver",
    )
    with TestClient(create_app(settings, transport=httpx.MockTransport(upstream))) as client:
        listed = rpc(
            client,
            "tools/call",
            {
                "name": "list_document_charts",
                "arguments": {"file_id": identifier},
            },
        ).json()["result"]["structuredContent"]["charts"]
        [chart] = listed
        assert chart["kind"] == "pie"
        args = {
            "file_id": identifier,
            "chart_id": chart["chart_id"],
            "question": "Which color is the largest slice?",
        }
        result = rpc(
            client,
            "tools/call",
            {
                "name": "extract_chart",
                "arguments": args,
            },
        ).json()["result"]["structuredContent"]
        assert result["chart"]["method"] == "vector"
        assert result["chart"]["chart_type"] == "pie"
        assert result["chart"]["largest_slice"] == expected
        assert result["source"]["page"] == 1
        assert result["source"]["bbox"] == chart["bbox"]
        values = {point["label"]: point["value"] for point in result["chart"]["values"]}
        assert values[expected] == 60.0
        assert sum(values.values()) == pytest.approx(100.0)
        assert all(point["evidence"] == "sector_estimate" for point in result["chart"]["values"])
        cached = rpc(
            client,
            "tools/call",
            {
                "name": "extract_chart",
                "arguments": args,
            },
        ).json()["result"]["structuredContent"]
        assert cached["cached"]


def test_incomplete_circle_is_not_a_pie():
    with pymupdf.open(stream=pie_pdf((90, 90, 90)), filetype="pdf") as parsed:
        assert not detect(parsed[0], text_lines(parsed[0]))


def test_equal_largest_slices_do_not_claim_a_winner():
    with pymupdf.open(stream=pie_pdf((120, 120, 120)), filetype="pdf") as parsed:
        [chart] = detect(parsed[0], text_lines(parsed[0]))
        assert read_pie(chart.sectors).largest_slice is None


def test_raster_pie_uses_opt_in_vision_without_fabricating_percentages(tmp_path):
    import json

    with pymupdf.open(stream=pie_pdf((90, 54, 216)), filetype="pdf") as vector:
        png = vector[0].get_pixmap().tobytes("png")
        with pymupdf.open() as raster:
            page = raster.new_page(width=640, height=480)
            page.insert_image(page.rect, stream=png)
            document = raster.tobytes()
    file_id = str(uuid4())
    vision_calls = []

    def upstream(request):
        if request.url.host == "vision.example":
            vision_calls.append(request)
            payload = json.loads(request.content)
            assert payload["messages"][0]["content"][1]["image_url"]["url"].startswith(
                "data:image/png;base64,"
            )
            result = {
                "chart_type": "pie",
                "largest_slice": "green",
                "values": [{"label": "green", "value": None}],
            }
            return httpx.Response(
                200, json={"choices": [{"message": {"content": json.dumps(result)}}]}
            )
        if request.url.path == "/api/v1/auths/":
            return httpx.Response(200, json={"id": "reader"})
        assert request.url.path == f"/api/v1/files/{file_id}/content"
        return httpx.Response(200, content=document)

    settings = Settings(
        openwebui_url="http://webui.local",
        allowed_hosts="testserver",
        cache_path=tmp_path / "pie.sqlite3",
        vision_base_url="https://vision.example/v1",
        vision_api_key="test-only",
        vision_model="vision",
    )
    with TestClient(create_app(settings, transport=httpx.MockTransport(upstream))) as client:
        args = {"file_id": file_id, "page_number": 1, "question": "Largest pie slice?"}
        response = rpc(
            client,
            "tools/call",
            {
                "name": "extract_chart",
                "arguments": args,
            },
        ).json()["result"]["structuredContent"]
        assert len(vision_calls) == 1
        assert response["chart"]["status"] == "partial"
        assert response["chart"]["largest_slice"] == "green"
        assert response["chart"]["values"][0]["value"] is None
        assert response["source"]["page"] == 1
