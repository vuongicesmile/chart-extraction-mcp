from typing import Annotated
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import Field

from app.schemas.chart import Extraction
from app.services.chart_service import ChartService
from app.tools.session import call


def register(mcp: FastMCP, service: ChartService) -> None:
    @mcp.tool()
    async def extract_chart(
        file_id: UUID,
        question: Annotated[str, Field(min_length=1, max_length=600)],
        ctx: Context,
        page_number: Annotated[int, Field(ge=1)] | None = None,
        chart_id: str | None = None,
    ) -> Extraction:
        """Read a bar chart when asked about values or comparisons in a PDF chart.
        Use the authorized attachment UUID and 1-based page or a chart_id from
        list_document_charts. If several charts are on the page, pass chart_id.
        Answer from chart.values and context, cite source.url and source.page,
        mark axis estimates as approximate, and leave unreadable values unknown.
        """
        return await call(ctx, service.extract, file_id, question, page_number, chart_id)
