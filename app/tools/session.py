from mcp.server.fastmcp import Context
from mcp.server.fastmcp.exceptions import ToolError

from app.services.file_resolver import ChartError


async def call(ctx: Context, operation, *arguments):
    request = ctx.request_context.request
    authorization = request.headers.get("authorization", "") if request is not None else ""
    try:
        return await operation(*arguments, authorization=authorization)
    except ChartError as error:
        raise ToolError(str(error)) from error
