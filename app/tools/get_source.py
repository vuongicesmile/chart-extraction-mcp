from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP

from app.schemas.chart import ChartSource
from app.services.chart_service import ChartService
from app.tools.session import call


def register(mcp: FastMCP, service: ChartService) -> None:
    @mcp.tool()
    async def get_chart_source(file_id: UUID, chart_id: str, ctx: Context) -> ChartSource:
        """Get a chart's authorized PDF URL, page, geometry and surrounding text.
        Pass the attachment UUID and the chart_id from list_document_charts.
        """
        return await call(ctx, service.get_source, file_id, chart_id)
