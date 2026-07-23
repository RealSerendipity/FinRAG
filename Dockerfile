# Production image for finrag (Wave 5A) — ONE image, BOTH services: the FastAPI
# backend (localhost:8000) and the Streamlit UI (:8501, the public surface).
# `docker run -p 8501:8501 finrag` brings up the whole app. Domain-agnostic: all
# host/secret config comes from the environment at runtime (see .env), nothing baked in.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Install dependencies first (cached layer): only the files uv needs to resolve.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --extra full --no-install-project --no-dev

# Then the application code, and install the project itself.
COPY src ./src
COPY prompts ./prompts
COPY sql ./sql
COPY deploy/entrypoint.sh ./deploy/entrypoint.sh
RUN uv sync --frozen --extra full --no-dev && chmod +x deploy/entrypoint.sh

# Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

# /app first on the import path so `import src` resolves to /app/src regardless of
# how uv installed the project — keeps prompts/ and sql/ (read at import time via
# Path(__file__)) pointing at /app/prompts and /app/sql.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app
EXPOSE 8501

# Agent traces (runs/<id>.jsonl) default to the repo dir; redirect to a writable
# path so the container's read-only-ish app dir doesn't break /agent.
ENV FINRAG_RUNS_DIR=/tmp/finrag-runs

# Liveness = the UI is serving (it depends on the in-container API).
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health').status==200 else 1)"

# Start both services (API in background, UI in foreground) via the entrypoint.
CMD ["bash", "deploy/entrypoint.sh"]
