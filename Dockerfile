# syntax=docker/dockerfile:1

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    AUTOPRD_DB_PATH=/app/data/autoprd.db

WORKDIR /app

# sqlite3 is included so the persisted database can be queried from inside the
# container: docker compose exec autoprd sqlite3 /app/data/autoprd.db ...
RUN apt-get update \
    && apt-get install -y --no-install-recommends sqlite3 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app \
    && useradd --system --gid app --create-home app

# Install dependencies first so code changes do not invalidate this layer.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir "setuptools>=68" wheel

# Install the package itself in editable mode: this keeps prd_parser/api.py
# inside /app, so the UI at /app/index.html is found at runtime.
COPY --chown=app:app pyproject.toml README.md ./
COPY --chown=app:app prd_parser ./prd_parser
COPY --chown=app:app index.html ./
RUN pip install --no-cache-dir --no-deps --no-build-isolation -e . \
    && mkdir -p /app/data \
    && chown -R app:app /app

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

CMD ["uvicorn", "prd_parser.api:app", "--host", "0.0.0.0", "--port", "8000"]
