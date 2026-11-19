from uuid import uuid4

import httpx
from starlette.testclient import TestClient

from app.main import create_app
from app.settings import Settings

HEADERS = {"Accept": "application/json, text/event-stream", "Authorization": "Bearer allowed"}


def rpc(client, method, params=None, headers=None):
    return client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or {},
        },
        headers=HEADERS if headers is None else headers,
    )


def test_mcp_streamable_http_discovery_permissions_source_and_cache(tmp_path, sample_pdf):
    file_id = str(uuid4())
    file_calls = []

    def upstream(request):
        if request.url.path == "/api/v1/auths/":
            valid = request.headers.get("Authorization") in ("Bearer allowed", "Bearer viewer")
            return httpx.Response(200 if valid else 401, json={"id": "verified"} if valid else {})
        file_calls.append(request.url.path)
        if (
            request.url.path != f"/api/v1/files/{file_id}/content"
            or request.headers.get("Authorization") != "Bearer allowed"
        ):
            return httpx.Response(404)
        return httpx.Response(
            200,
            content=sample_pdf,
            headers={
                "Content-Disposition": "attachment; filename*=UTF-8''B%C3%A1o-c%C3%A1o.pdf",
            },
        )

    app = create_app(
        Settings(
            cache_path=tmp_path / "data.sqlite3",
            allowed_hosts="testserver",
            openwebui_url="http://webui.local",
            openwebui_public_url="http://webui.local",
        ),
        transport=httpx.MockTransport(upstream),
    )
    with TestClient(app) as client:
        assert rpc(client, "tools/list", headers={"Accept": HEADERS["Accept"]}).status_code == 401
        assert (
            rpc(
                client,
                "tools/list",
                headers={
                    **HEADERS,
                    "Authorization": "Bearer expired",
                },
            ).status_code
            == 401
        )
        assert (
            rpc(client, "tools/list", headers={**HEADERS, "Host": "invalid.local"}).status_code
            == 421
        )
        initialized = rpc(
            client,
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {
                    "name": "test",
                    "version": "1",
                },
            },
        )
        assert initialized.status_code == 200
        assert initialized.json()["result"]["serverInfo"]["name"] == "Chart Extraction"
        discovery = rpc(client, "tools/list").json()["result"]["tools"]
        assert {t["name"] for t in discovery} == {
            "list_document_charts",
            "extract_chart",
            "get_chart_source",
        }
        assert all("ctx" not in t["inputSchema"]["properties"] for t in discovery)
        listing = rpc(
            client,
            "tools/call",
            {
                "name": "list_document_charts",
                "arguments": {"file_id": file_id},
            },
        ).json()["result"]["structuredContent"]
        [chart] = listing["charts"]
        assert listing["source_file"] == "Báo-cáo.pdf"
        assert chart["page"] == 1
        call = {
            "name": "extract_chart",
            "arguments": {
                "file_id": file_id,
                "chart_id": chart["chart_id"],
                "question": "Q2 revenue?",
            },
        }
        result = rpc(client, "tools/call", call).json()["result"]["structuredContent"]
        assert result["chart"]["values"][1]["value"] == 50
        assert not result["cached"]
        second = rpc(client, "tools/call", call).json()["result"]["structuredContent"]
        assert second["cached"]
        denied = rpc(
            client,
            "tools/call",
            call,
            {
                **HEADERS,
                "Authorization": "Bearer viewer",
            },
        ).json()["result"]
        assert denied["isError"]
        assert "unavailable" in denied["content"][0]["text"]
        assert "values" not in denied
        source = rpc(
            client,
            "tools/call",
            {
                "name": "get_chart_source",
                "arguments": {"file_id": file_id, "chart_id": chart["chart_id"]},
            },
        ).json()["result"]["structuredContent"]
        assert (
            source["source"]["url"] == f"http://webui.local/api/v1/files/{file_id}/content#page=1"
        )
        before_invalid = len(file_calls)
        invalid = rpc(
            client,
            "tools/call",
            {
                "name": "list_document_charts",
                "arguments": {"file_id": "../../file.pdf"},
            },
        ).json()["result"]
        assert invalid["isError"]
        assert len(file_calls) == before_invalid
        assert len(file_calls) == 5
