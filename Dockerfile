FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --system novel && useradd --system --gid novel --create-home novel

COPY pyproject.toml README.md alembic.ini ./
COPY migrations ./migrations
COPY src ./src

RUN python -m pip install --upgrade pip && python -m pip install .

RUN mkdir -p /app/logs && chown -R novel:novel /app
USER novel

FROM runtime AS worker
HEALTHCHECK NONE
CMD ["novel-harness", "worker"]

FROM runtime AS api
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]
CMD ["uvicorn", "novel_harness.api:app", "--host", "0.0.0.0", "--port", "8000"]
