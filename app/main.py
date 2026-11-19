import asyncio
import os
from contextlib import asynccontextmanager

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.services.chart_service import ChartService
from app.settings import Settings
from app.tools import extract_chart, get_source, list_charts


def create_app(settings: Settings | None = None, transport=None):
    settings = settings or Settings()
    http = httpx.AsyncClient(
        timeout=httpx.Timeout(30, connect=5),
        follow_redirects=False,
        trust_env=False,
        transport=transport,
    )
    service = ChartService(settings, http)

    hosts = [part.strip() for part in settings.allowed_hosts.split(",") if part.strip()]
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[entry for host in hosts for entry in (host, f"{host}:*")],
        allowed_origins=[
            entry
            for host in hosts
            for entry in (f"http://{host}", f"http://{host}:*", f"https://{host}")
        ],
    )
    mcp = FastMCP(
        "Chart Extraction",
        instructions="Read and cite on-demand charts from Open WebUI PDFs.",
        json_response=True,
        stateless_http=True,
        transport_security=security,
        max_request_body_size=32_768,
    )
    list_charts.register(mcp, service)
    extract_chart.register(mcp, service)
    get_source.register(mcp, service)

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_request: Request):
        return JSONResponse({"status": "ok"})

    app = mcp.streamable_http_app()

    class OpenWebUISession:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] == "http" and scope["path"] == "/mcp":
                authorization = Request(scope).headers.get("authorization", "")
                scheme, _, token = authorization.partition(" ")
                if scheme.lower() != "bearer" or not token or len(token) > 8192:
                    await JSONResponse(
                        {"error": "Open WebUI session required."},
                        status_code=401,
                        headers={"WWW-Authenticate": "Bearer"},
                    )(scope, receive, send)
                    return
                try:
                    verified = await service.files.authenticate(authorization)
                except httpx.HTTPError:
                    await JSONResponse(
                        {"error": "Open WebUI session service unavailable."},
                        status_code=502,
                    )(scope, receive, send)
                    return
                if not verified:
                    await JSONResponse(
                        {"error": "Invalid Open WebUI session."},
                        status_code=401,
                        headers={"WWW-Authenticate": "Bearer"},
                    )(scope, receive, send)
                    return
            await self.app(scope, receive, send)

    # Lifespan of the HTTP session manager is outside request lifespans for stateless mode.
    # Close the shared HTTP client on application shutdown rather than after a tool call.
    previous_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def app_lifespan(current_app):
        await asyncio.to_thread(service.cache.initialize)
        async with http, previous_lifespan(current_app):
            yield

    app.router.lifespan_context = app_lifespan
    app.add_middleware(OpenWebUISession)
    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        create_app(), host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8765"))
    )
