from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

Box = tuple[float, float, float, float]


class Source(BaseModel):
    file_id: UUID
    source_file: str
    page: int
    bbox: Box
    url: str


class ChartContext(BaseModel):
    heading: str | None = None
    caption: str | None = None
    before: str | None = None
    after: str | None = None


class ChartReference(BaseModel):
    chart_id: str
    page: int
    bbox: Box
    kind: Literal["bar", "candidate"]
    caption: str | None = None


class ChartList(BaseModel):
    file_id: UUID
    source_file: str
    total_pages: int
    next_page: int | None
    charts: list[ChartReference]


class DataPoint(BaseModel):
    label: str
    value: float | None = None
    evidence: Literal["label", "axis_estimate", "vision", "unreadable"]


class ChartData(BaseModel):
    status: Literal["ok", "partial", "unreadable", "unsupported"]
    method: Literal["vector", "ocr", "vision", "none"]
    title: str | None = None
    x_axis: str | None = None
    y_axis: str | None = None
    unit: str | None = None
    values: list[DataPoint] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class Extraction(BaseModel):
    chart_id: str
    question: str
    source: Source
    context: ChartContext
    chart: ChartData
    cached: bool


class ChartSource(BaseModel):
    chart_id: str
    source: Source
    context: ChartContext
