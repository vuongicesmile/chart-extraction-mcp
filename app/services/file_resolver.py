import re
from dataclasses import dataclass
from urllib.parse import unquote
from uuid import UUID

import httpx

from app.settings import Settings


class ChartError(Exception):
    """A safe error that can be exposed to a caller."""


@dataclass(frozen=True)
class ResolvedPDF:
    file_id: UUID
    filename: str
    content: bytes
    url: str


class FileResolver:
    def __init__(self, settings: Settings, http: httpx.AsyncClient):
        self.settings = settings
        self.http = http

    async def authenticate(self, authorization: str) -> bool:
        response = await self.http.get(
            f"{str(self.settings.openwebui_url).rstrip('/')}/api/v1/auths/",
            headers={"Authorization": authorization},
        )
        if response.status_code in (401, 403, 404):
            return False
        response.raise_for_status()
        return response.status_code == 200

    async def resolve(self, file_id: UUID, authorization: str) -> ResolvedPDF:
        path = f"/api/v1/files/{file_id}/content"
        endpoint = str(self.settings.openwebui_url).rstrip("/") + path
        public = self.settings.openwebui_public_url
        try:
            async with self.http.stream(
                "GET", endpoint, headers={"Authorization": authorization}
            ) as response:
                if response.status_code in (401, 403, 404):
                    raise ChartError("PDF unavailable for this Open WebUI session.")
                if response.status_code != 200:
                    raise ChartError("Open WebUI could not return the original PDF.")
                announced = response.headers.get("content-length", "")
                if announced.isdecimal() and int(announced) > self.settings.max_pdf_bytes:
                    raise ChartError("PDF exceeds the configured size limit.")
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > self.settings.max_pdf_bytes:
                        raise ChartError("PDF exceeds the configured size limit.")
                    content.extend(chunk)
                disposition = response.headers.get("content-disposition", "")
        except httpx.HTTPError as error:
            raise ChartError("Open WebUI file service is unavailable.") from error
        if b"%PDF-" not in content[:1024]:
            raise ChartError("The selected file is not a PDF.")
        match = re.search(r"filename\*=(?:UTF-8'')([^;]+)", disposition, re.IGNORECASE)
        raw_name = unquote(match[1].strip().strip('"')) if match else ""
        filename = raw_name.replace("\\", "/").rsplit("/", 1)[-1].strip() or f"{file_id}.pdf"
        return ResolvedPDF(
            file_id=file_id,
            filename=filename,
            content=bytes(content),
            url=(str(public).rstrip("/") if public else "") + path,
        )
