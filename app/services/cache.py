import sqlite3
import time
from pathlib import Path

from app.schemas.chart import ChartData


class ChartCache:
    def __init__(self, path: Path, ttl_hours: int):
        self.path = path
        self.ttl = ttl_hours * 3600

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with sqlite3.connect(self.path) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                "CREATE TABLE IF NOT EXISTS charts (key TEXT PRIMARY KEY, "
                "data TEXT NOT NULL, expires_at REAL NOT NULL)"
            )
            db.execute("CREATE INDEX IF NOT EXISTS chart_expiry ON charts(expires_at)")

    def read(self, key: str) -> ChartData | None:
        with sqlite3.connect(self.path) as db:
            row = db.execute(
                "SELECT data FROM charts WHERE key=? AND expires_at>?", (key, time.time())
            ).fetchone()
        return ChartData.model_validate_json(row[0]) if row else None

    def write(self, key: str, chart: ChartData) -> None:
        expires = time.time() + self.ttl
        with sqlite3.connect(self.path) as db:
            db.execute("DELETE FROM charts WHERE expires_at<=?", (time.time(),))
            db.execute(
                "INSERT INTO charts VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE "
                "SET data=excluded.data, expires_at=excluded.expires_at",
                (key, chart.model_dump_json(), expires),
            )
