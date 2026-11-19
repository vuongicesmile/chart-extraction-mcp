import asyncio
import hashlib
import re
from dataclasses import dataclass
from threading import Lock
from uuid import UUID

import httpx

from app.schemas.chart import Box, ChartData, ChartList, ChartSource, Extraction, Source
from app.services.cache import ChartCache
from app.services.chart_detector import DetectedChart, detect
from app.services.chart_extractor import read_bars, read_raster, read_vision
from app.services.file_resolver import ChartError, FileResolver, ResolvedPDF
from app.services.pdf_parser import TextLine, open_pdf, page_at, render, text_lines
from app.services.pie_chart import read_pie
from app.settings import Settings

CHART_ID = re.compile(r"p([1-9]\d{0,6})-[a-f0-9]{16}")
EXTRACTOR_VERSION = "5"


@dataclass(frozen=True)
class LocatedChart:
    chart: DetectedChart
    lines: list[TextLine]


def scan(document: ResolvedPDF, start: int, limit: int, vision_enabled: bool) -> ChartList:
    with open_pdf(document.content) as pdf:
        page_at(pdf, start)
        last = min(pdf.page_count, start + limit - 1)
        charts = []
        for number in range(start, last + 1):
            page = page_at(pdf, number)
            charts.extend(detect(page, text_lines(page), vision_enabled))
        return ChartList(
            file_id=document.file_id,
            source_file=document.filename,
            total_pages=pdf.page_count,
            next_page=last + 1 if last < pdf.page_count else None,
            charts=[chart.reference for chart in charts],
        )


def locate(
    document: ResolvedPDF, number: int, chart_id: str | None, vision_enabled: bool
) -> LocatedChart:
    with open_pdf(document.content) as pdf:
        page = page_at(pdf, number)
        lines = text_lines(page)
        charts = detect(page, lines, vision_enabled)
        if chart_id is not None:
            charts = [chart for chart in charts if chart.reference.chart_id == chart_id]
        if not charts:
            raise ChartError(
                "No matching chart on this page. Use list_document_charts to locate it."
            )
        if len(charts) != 1:
            raise ChartError(
                "Multiple charts on this page. Use list_document_charts and pass chart_id."
            )
        chart = charts[0]
        return LocatedChart(chart, lines)


def render_chart(document: ResolvedPDF, number: int, bbox: Box) -> bytes:
    with open_pdf(document.content) as pdf:
        return render(page_at(pdf, number), bbox)


# Keep the lock inside the worker so disconnects cannot leave MuPDF running concurrently.
_pdf_lock = Lock()


def pdf_call(operation, *args):
    with _pdf_lock:
        return operation(*args)


class ChartService:
    def __init__(self, settings: Settings, http: httpx.AsyncClient):
        self.settings = settings
        self.http = http
        self.files = FileResolver(settings, http)
        self.cache = ChartCache(settings.cache_path, settings.cache_ttl_hours)
        self.cache_locks = [asyncio.Lock() for _ in range(32)]
        self.vision_enabled = bool(
            settings.vision_base_url and settings.vision_api_key and settings.vision_model
        )

    async def list(self, file_id: UUID, start: int, authorization: str) -> ChartList:
        document = await self.files.resolve(file_id, authorization)
        return await asyncio.to_thread(
            pdf_call, scan, document, start, self.settings.max_pages_per_scan, self.vision_enabled
        )

    @staticmethod
    def chart_page(page: int | None, chart_id: str | None) -> int:
        if chart_id is not None:
            match = CHART_ID.fullmatch(chart_id)
            if match is None:
                raise ChartError("Use a chart_id returned by list_document_charts.")
            chart_page = int(match[1])
            if page is not None and page != chart_page:
                raise ChartError("page_number does not match chart_id.")
            return chart_page
        if page is None:
            raise ChartError("Provide page_number or a chart_id from list_document_charts.")
        return page

    @staticmethod
    def source(document: ResolvedPDF, chart: DetectedChart) -> Source:
        reference = chart.reference
        return Source(
            file_id=document.file_id,
            source_file=document.filename,
            page=reference.page,
            bbox=reference.bbox,
            url=f"{document.url}#page={reference.page}",
        )

    async def get_source(self, file_id: UUID, chart_id: str, authorization: str) -> ChartSource:
        document = await self.files.resolve(file_id, authorization)
        page = self.chart_page(None, chart_id)
        result = await asyncio.to_thread(
            pdf_call, locate, document, page, chart_id, self.vision_enabled
        )
        return ChartSource(
            chart_id=chart_id,
            source=self.source(document, result.chart),
            context=result.chart.context,
        )

    async def extract(
        self,
        file_id: UUID,
        question: str,
        page_number: int | None,
        chart_id: str | None,
        authorization: str,
    ) -> Extraction:
        # Always ask Open WebUI for authorized bytes before touching the shared cache.
        document = await self.files.resolve(file_id, authorization)
        page = self.chart_page(page_number, chart_id)
        result = await asyncio.to_thread(
            pdf_call, locate, document, page, chart_id, self.vision_enabled
        )
        chart = result.chart
        vision_enabled = self.vision_enabled
        file_hash = hashlib.sha256(document.content).hexdigest()
        fingerprint = (
            EXTRACTOR_VERSION,
            file_hash,
            chart.reference.chart_id,
            self.settings.ocr_language,
            str(self.settings.vision_base_url) if vision_enabled else "",
            self.settings.vision_model if vision_enabled else "",
            self.settings.vision_max_tokens if vision_enabled else None,
        )
        key = hashlib.sha256(repr(fingerprint).encode()).hexdigest()
        lock = self.cache_locks[int(key[:2], 16) % len(self.cache_locks)]
        async with lock:
            data = await asyncio.to_thread(self.cache.read, key)
            cached = data is not None
            if data is None:
                if chart.sectors:
                    data = read_pie(chart.sectors)
                elif chart.bars:
                    data = read_bars(chart, result.lines)
                else:
                    data = ChartData(
                        status="unreadable",
                        method="none",
                        warnings=["No readable vector geometry."],
                    )
                if data.status != "ok" and (vision_enabled or not chart.bars):
                    png = await asyncio.to_thread(
                        pdf_call,
                        render_chart,
                        document,
                        page,
                        chart.reference.bbox,
                    )
                    if not chart.bars and chart.reference.kind == "bar":
                        data = await asyncio.to_thread(
                            read_raster,
                            chart,
                            png,
                            self.settings.ocr_language,
                        )
                    if data.status != "ok" and vision_enabled:
                        fallback = await read_vision(self.settings, png, self.http)
                        known = {
                            point.label.casefold(): point.value
                            for point in data.values
                            if point.evidence == "label"
                        }
                        guessed = {point.label.casefold(): point.value for point in fallback.values}
                        conflicts = known and any(
                            guessed.get(key) != value for key, value in known.items()
                        )
                        if conflicts and fallback.status == "ok":
                            data.warnings.append(
                                "Vision disagreed with printed labels; kept the original values."
                            )
                        elif data.status != "partial" or fallback.status == "ok":
                            data = fallback
                # Allow retrying transient provider errors and unreadable inputs.
                if data.status in ("ok", "partial", "unsupported"):
                    await asyncio.to_thread(self.cache.write, key, data)
        return Extraction(
            chart_id=chart.reference.chart_id,
            question=question,
            source=self.source(document, chart),
            context=chart.context,
            chart=data,
            cached=cached,
        )
