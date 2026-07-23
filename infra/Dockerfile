# Production image for finrag (Wave 5A) — ONE image, BOTH services: the FastAPI
# backend (localhost:8000) and the Streamlit UI (:8501, the public surface).
# `docker run -p 8501:8501 finrag` brings up the whole app. Domain-agnostic: all
# host/secret config comes from the environment at runtime (see .env), nothing baked in.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app/backend

# Install dependencies first (cached layer): only the files uv needs to resolve.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --extra full --no-install-project --no-dev

# Then the application code, and install the project itself.
COPY backend/src ./src
COPY backend/prompts ./prompts
COPY backend/sql ./sql
COPY infra/entrypoint.sh /app/infra/entrypoint.sh
RUN uv sync --frozen --extra full --no-dev && chmod +x /app/infra/entrypoint.sh

# Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

# Keep the backend project root on the import path so `import src` and the
# adjacent prompts/ and sql/ runtime resources resolve consistently.
ENV PATH="/app/backend/.venv/bin:$PATH" \
    PYTHONPATH=/app/backend
EXPOSE 8501

# Agent traces (runs/<id>.jsonl) default to the repo dir; redirect to a writable
# path so the container's read-only-ish app dir doesn't break /agent.
ENV FINRAG_RUNS_DIR=/tmp/finrag-runs

# Liveness = the UI is serving (it depends on the in-container API).
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health').status==200 else 1)"

# Start both services (API in background, UI in foreground) via the entrypoint.
CMD ["bash", "/app/infra/entrypoint.sh"]
