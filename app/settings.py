from pathlib import Path

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_ignore_empty=True)
    openwebui_url: AnyHttpUrl = AnyHttpUrl("http://open-webui:8080")
    openwebui_public_url: AnyHttpUrl | None = None
    cache_path: Path = Path("data/charts.sqlite3")
    max_pdf_bytes: int = Field(25_000_000, ge=1024, le=100_000_000)
    max_pages_per_scan: int = Field(10, ge=1, le=30)
    cache_ttl_hours: int = Field(168, ge=1, le=720)
    allowed_hosts: str = "localhost,127.0.0.1,chart-mcp"
    vision_base_url: AnyHttpUrl | None = None
    vision_api_key: SecretStr | None = None
    vision_model: str = ""
    vision_max_tokens: int = Field(1000, ge=100, le=8192)
    ocr_language: str = Field("eng", pattern=r"^[a-zA-Z_]+(?:\+[a-zA-Z_]+)*$")
