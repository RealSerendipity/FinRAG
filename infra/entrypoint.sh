#!/usr/bin/env bash
# One container, both services: the FastAPI backend (API, localhost:8000) and the
# Streamlit UI (the public surface, :8501). The UI is the only exposed port; it
# reaches the API in-process over localhost. `docker run -p 8501:8501 ...` is all
# a user needs to bring up the whole app.
set -euo pipefail

# Bridge the UI to the in-container API, and carry the gate token through if the
# API is token-gated (so the browser never needs it).
export FINRAG_API_URL="http://127.0.0.1:8000"
export FINRAG_API_TOKEN="${API_TOKEN:-}"

uvicorn src.api:app --host 127.0.0.1 --port 8000 &
api_pid=$!

# Serve the UI at root by default; under API_ROOT_PATH (e.g. /finrag) when set, so
# the same image works both at localhost:8501 and behind a subpath reverse proxy.
ui_args=(--server.address 0.0.0.0 --server.port 8501
         --server.headless true --browser.gatherUsageStats false)
[ -n "${API_ROOT_PATH:-}" ] && ui_args+=(--server.baseUrlPath "${API_ROOT_PATH}")
streamlit run src/ui.py "${ui_args[@]}" &
ui_pid=$!

# Forward container termination to both children.
trap 'kill -TERM "$api_pid" "$ui_pid" 2>/dev/null || true' TERM INT

# If either service exits, stop the other so the container goes down cleanly
# instead of serving a half-broken app.
wait -n
kill "$api_pid" "$ui_pid" 2>/dev/null || true
