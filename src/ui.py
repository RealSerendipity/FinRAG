"""Streamlit single-page demo (Wave 5A).

Two modes over the same backend, chosen with the sidebar toggle:
- **RAG** (`POST /ask`): one retrieval over filings + a cited answer (fast).
- **Agent** (`POST /agent`): a multi-step ReAct loop that calls tools
  (retrieve / XBRL metric / compare / calculator / web search) and returns the
  final answer plus the steps it took.
An ingest panel at the bottom pulls a new SEC filing into the store.

Run with:  uv run streamlit run src/ui.py
Point at a backend with FINRAG_API_URL (default http://127.0.0.1:8000).
Set FINRAG_API_TOKEN when the backend is token-gated (sent as a Bearer header).
"""

from __future__ import annotations

import json
import os

import requests
import streamlit as st

API_URL = os.environ.get("FINRAG_API_URL", "http://127.0.0.1:8000").rstrip("/")
API_TOKEN = os.environ.get("FINRAG_API_TOKEN", "").strip()
_TIMEOUT = 180


def _auth_headers(extra: dict | None = None) -> dict:
    """Merge the optional Bearer token into request headers (no-op when unset)."""
    headers = dict(extra or {})
    if API_TOKEN:
        headers["Authorization"] = f"Bearer {API_TOKEN}"
    return headers


def _stream_ask(payload: dict) -> dict:
    """POST /ask and fold the SSE event stream into the final answer dict.

    Returns the `answer` event payload, or {"error": ...} on an error event /
    transport failure. Server-Sent Events are `event:`/`data:` line pairs
    separated by blank lines.
    """
    try:
        resp = requests.post(
            f"{API_URL}/ask", json=payload, stream=True,
            headers=_auth_headers({"Accept": "text/event-stream"}), timeout=_TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        return {"error": f"request failed: {exc}"}

    event, data = None, None
    for raw in resp.iter_lines(decode_unicode=True):
        if raw is None:
            continue
        line = raw.strip()
        if line.startswith("event:"):
            event = line[len("event:"):].strip()
        elif line.startswith("data:"):
            data = line[len("data:"):].strip()
        elif line == "":  # blank line terminates one event
            if event == "answer" and data:
                return json.loads(data)
            if event == "error" and data:
                return {"error": json.loads(data).get("error", "unknown error")}
            event, data = None, None
    return {"error": "stream ended without an answer"}


def _post(path: str, payload: dict) -> dict:
    """POST JSON to a non-streaming endpoint; return the parsed dict or {"error": ...}."""
    try:
        resp = requests.post(
            f"{API_URL}{path}", json=payload, headers=_auth_headers(), timeout=_TIMEOUT
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        return {"error": f"request failed: {exc}"}


def _render_metrics(result: dict) -> None:
    """Latency / token / cost line + Langfuse trace link (Wave 5B), shared by both modes."""
    usage = result.get("usage", {})
    bits = [
        f"⏱ {result.get('latency_ms', '?')} ms",
        f"🔢 {usage.get('input_tokens', 0)}+{usage.get('output_tokens', 0)} tok",
        f"💲 ${result.get('cost_usd', 0):.6f}",
    ]
    st.caption(" · ".join(bits))
    if result.get("trace_url"):
        st.caption(f"[View Langfuse trace]({result['trace_url']})")


st.set_page_config(page_title="finrag — SEC filing Q&A", page_icon="📑")
st.title("📑 finrag")
st.caption("Ask questions over SEC filings — answers are grounded in cited chunks.")

# Sidebar: mode toggle first, then mode-specific controls so the page reflects the choice.
with st.sidebar:
    mode = st.radio(
        "Mode",
        ["RAG (single-shot)", "Agent (multi-step tools)"],
        help=(
            "RAG: one retrieval over the filings, then a single cited answer — fast, "
            "best for direct factual questions. Agent: a ReAct loop that reasons and "
            "calls tools (filing retrieval, SEC XBRL metric lookup, company comparison, "
            "calculator, web search) across several steps — better for multi-step, "
            "numeric, or cross-company questions."
        ),
    )
    is_agent = mode.startswith("Agent")
    st.divider()

    # Scope filters only apply to RAG; the agent picks its own scope via tools.
    ticker, year, use_year, top_k = "AAPL", 2024, True, 5
    if is_agent:
        st.caption(
            "🛠️ **Agent mode** — the agent chooses its own tools and scope, so the "
            "Ticker / year / top_k filters don't apply here. Switch to RAG mode to use them."
        )
    else:
        st.header("Scope")
        ticker = st.text_input("Ticker", value="AAPL", help="e.g. AAPL. Leave blank to search all.")
        year = st.number_input("Fiscal year", min_value=1994, max_value=2030, value=2024, step=1)
        use_year = st.checkbox("Filter by year", value=True)
        top_k = st.slider("Chunks (top_k)", min_value=1, max_value=20, value=5)

    st.divider()
    try:
        health = requests.get(f"{API_URL}/health", timeout=5).json()
        st.caption(f"Health: {health.get('status')} · tracing: {health.get('tracing')}")
    except requests.RequestException:
        st.caption("Health: unreachable")

# Pre-fill a sensible default per mode so the page is click-to-answer out of the
# box. A mode-keyed widget means switching modes swaps in that mode's example;
# the user can overwrite it freely.
default_question = (
    "How did Apple's R&D-to-revenue ratio change from FY2023 to FY2024?"
    if is_agent
    else "What was Apple's total net sales in fiscal 2024?"
)
question = st.text_input("Question", value=default_question, key=f"question_{is_agent}")

if st.button("Ask", type="primary") and question.strip():
    if is_agent:
        with st.spinner("Running the agent (reasoning + tools)…"):
            result = _post("/agent", {"question": question.strip()})
        if "error" in result:
            st.error(result["error"])
        else:
            st.markdown(result["answer"])
            tools = result.get("tools_used", [])
            if tools:
                st.caption("Tools used: " + ", ".join(f"`{t}`" for t in tools))
            steps = result.get("steps", [])
            if steps:
                with st.expander(f"Reasoning trace ({len(steps)} steps)"):
                    for i, s in enumerate(steps, start=1):
                        if s.get("action"):
                            st.markdown(f"**Step {i} — `{s['action']}`**")
                            st.code(
                                json.dumps(s.get("action_input"), ensure_ascii=False),
                                language="json",
                            )
                            observation = s.get("observation") or ""
                            st.text(observation[:600] + ("…" if len(observation) > 600 else ""))
                        elif s.get("thought"):
                            st.markdown(f"**Step {i}** — {s['thought']}")
            _render_metrics(result)
    else:
        payload: dict = {"question": question.strip(), "top_k": int(top_k)}
        if ticker.strip():
            payload["ticker"] = ticker.strip().upper()
        if use_year:
            payload["year"] = int(year)
        with st.spinner("Retrieving and generating…"):
            result = _stream_ask(payload)
        if "error" in result:
            st.error(result["error"])
        else:
            st.markdown(result["text"])
            citations = result.get("citations", [])
            if citations:
                st.subheader(f"Citations ({len(citations)})")
                for cit in citations:
                    with st.expander(f"chunk {cit['chunk_id']}"):
                        st.write(cit["quote"])
            _render_metrics(result)

# Ingest panel — let users pull a new filing into the store themselves.
st.divider()
with st.expander("⬇️  Ingest a filing — add a company / year to the store"):
    st.caption(
        "Fetch a filing from SEC EDGAR and index it so you can ask about it. "
        "This downloads and embeds the document, so it may take ~1–2 minutes."
    )
    c1, c2, c3 = st.columns(3)
    ing_ticker = c1.text_input("Ticker", value="MSFT", key="ing_ticker")
    ing_year = c2.number_input("Year", min_value=1994, max_value=2030, value=2024, key="ing_year")
    ing_form = c3.selectbox("Form", ["10-K", "10-Q", "8-K", "20-F", "DEF 14A"], key="ing_form")
    if st.button("Ingest filing"):
        if not ing_ticker.strip():
            st.warning("Enter a ticker first.")
        else:
            with st.spinner(f"Ingesting {ing_ticker.upper()} {ing_form} {int(ing_year)}…"):
                res = _post(
                    "/ingest",
                    {"tickers": [ing_ticker.strip().upper()],
                     "form_type": ing_form, "year": int(ing_year)},
                )
            if "error" in res:
                st.error(res["error"])
            else:
                for r in res.get("results", []):
                    if "error" in r:
                        st.error(f"{r['ticker']}: {r['error']}  ({r['elapsed_s']}s)")
                    else:
                        st.success(
                            f"{r['ticker']}: ingested {r['chunks']} chunks in {r['elapsed_s']}s — "
                            "ask a question about it above."
                        )
