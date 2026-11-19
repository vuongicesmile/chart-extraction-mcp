FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /usr/local/bin/uv

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-vie \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 chart \
    && install -d -m 700 -o chart -g chart /data

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev
COPY app ./app
USER chart
ENV PATH="/app/.venv/bin:$PATH" HOST=0.0.0.0 CACHE_PATH=/data/charts.sqlite3 \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 8765
CMD ["python", "-m", "app.main"]
