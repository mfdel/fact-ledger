# syntax=docker/dockerfile:1

# ---- build: resolve and install locked dependencies with uv
FROM ghcr.io/astral-sh/uv:python3.14-trixie-slim AS builder
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

# ---- runtime: slim image, no build tools, non-root user
FROM python:3.14-slim-trixie AS runtime
# Base image lags Debian security fixes (e.g. CVE-2026-75804, CVE-2026-84782, CVE-2026-103111).
RUN apt-get update && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip uninstall --yes --root-user-action=ignore pip \
    && groupadd --system app && useradd --system --gid app --home-dir /app app \
    && mkdir -p /app/data && chown app:app /app/data
WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app alembic.ini /app/alembic.ini
# Outside /app/data, so a volume for the database cannot hide the dictionary.
COPY --chown=app:app data/dictionary /app/dictionary
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FACT_LEDGER_ENV=prod \
    FACT_LEDGER_DATABASE_URL=sqlite:////app/data/fact_ledger.db \
    FACT_LEDGER_DICTIONARY_DIR=/app/dictionary
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]
CMD ["fact-ledger", "serve", "--host", "0.0.0.0", "--port", "8000"]
