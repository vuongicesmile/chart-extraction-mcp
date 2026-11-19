from typing import Annotated
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import Field

from app.schemas.chart import ChartList
from app.services.chart_service import ChartService
from app.tools.session import call


def register(mcp: FastMCP, service: ChartService) -> None:
    @mcp.tool()
    async def list_document_charts(
        file_id: UUID,
        ctx: Context,
        start_page: Annotated[int, Field(ge=1)] = 1,
    ) -> ChartList:
        """Locate bar and pie charts in an authorized Open WebUI PDF. Pass the attachment UUID,
        never a filename. Page numbers are 1-based. Continue using next_page when present.
        A candidate may be an illustration; extract_chart verifies what it can read.
        """
        return await call(ctx, service.list, file_id, start_page)
