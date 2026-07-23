"""Wave 4 tests: tools, ReAct parsing, and the agent loop.

Offline by default — the calculator, the registry/dispatch, the ReAct parser, and
a full agent run driven by a stubbed LLM + stub tools need no network or keys.
The live XBRL and LangGraph paths clean-skip when their prerequisites are absent.
"""

from __future__ import annotations

import json
import os

import pytest

from src.agent import Agent, _coerce_args, _parse
from src.tools import REGISTRY, Tool, render_tools, run_tool
from src.tools.calculator import calculator
from src.tools.spec import Tool as SpecTool


# ---------------------------------------------------------------------------
# calculator
# ---------------------------------------------------------------------------
def test_calculator_arithmetic() -> None:
    assert calculator("(416161-391035)/391035*100").endswith("6.425511782832739")
    assert calculator("2 + 3 * 4") == "2 + 3 * 4 = 14"
    assert calculator("round(6.4255, 1)").endswith("= 6.4")
    assert calculator("abs(-5)").endswith("= 5")


def test_calculator_rejects_unsafe() -> None:
    assert "Error" in calculator("__import__('os').system('ls')")
    assert "Error" in calculator("foo(1)")
    assert "division by zero" in calculator("1/0")
    assert "Error" in calculator("")


# ---------------------------------------------------------------------------
# registry + dispatch
# ---------------------------------------------------------------------------
def test_registry_has_five_tools() -> None:
    assert set(REGISTRY) == {
        "retrieve_filing", "lookup_metric", "compare_companies", "web_search", "calculator"
    }
    for tool in REGISTRY.values():
        assert isinstance(tool, (Tool, SpecTool))
        assert tool.description and tool.parameters


def test_run_tool_unknown_and_bad_args() -> None:
    assert "unknown tool" in run_tool("nope", {})
    assert "must be a JSON object" in run_tool("calculator", ["1+1"])  # type: ignore[arg-type]
    assert "Expected arguments" in run_tool("calculator", {"wrong": "1+1"})


def test_run_tool_captures_exceptions() -> None:
    def boom() -> str:
        raise RuntimeError("kaboom")

    reg = {"boom": Tool("boom", "d", {}, boom)}
    out = run_tool("boom", {}, registry=reg)
    assert "Error calling 'boom'" in out and "kaboom" in out


def test_web_search_skips_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    assert "TAVILY_API_KEY not set" in run_tool("web_search", {"query": "x"})


def test_render_tools_lists_args() -> None:
    rendered = render_tools()
    assert "calculator" in rendered and "expression" in rendered


# ---------------------------------------------------------------------------
# ReAct parser
# ---------------------------------------------------------------------------
def test_parse_final_answer() -> None:
    assert _parse("Thought: done\nFinal Answer: 42") == ("final", "42")


def test_parse_action_json() -> None:
    kind, payload = _parse('Action: calculator\nAction Input: {"expression": "1+1"}')
    assert kind == "action" and payload == ("calculator", {"expression": "1+1"})


def test_parse_action_inline_and_bare_value() -> None:
    # Action Input on the same line as Action.
    k1, p1 = _parse('Action: calculator Action Input: {"expression": "2*2"}')
    assert p1 == ("calculator", {"expression": "2*2"})
    # Bare (non-JSON) value coerced onto a single-arg tool.
    k2, p2 = _parse("Action: calculator\nAction Input: (1+2)/3")
    assert p2 == ("calculator", {"expression": "(1+2)/3"})


def test_parse_invalid_when_multiarg_without_json() -> None:
    kind, reason = _parse("Action: lookup_metric\nAction Input: AAPL revenue")
    assert kind == "invalid"


def test_final_answer_wins_over_trailing_action() -> None:
    kind, payload = _parse("Final Answer: 7\nAction: calculator\nAction Input: {}")
    assert kind == "final" and payload.startswith("7")


def test_coerce_args_multiarg_needs_json() -> None:
    assert _coerce_args("AAPL revenue", REGISTRY["lookup_metric"]) is None


# ---------------------------------------------------------------------------
# agent loop — stubbed LLM + stub tools (no network)
# ---------------------------------------------------------------------------
class _ScriptedLLM:
    """A stand-in for src.agent.chat that replays a fixed list of completions."""

    def __init__(self, turns: list[str]) -> None:
        self.turns = turns
        self.calls = 0

    def __call__(self, messages, *, system=None, temperature=0.0, max_tokens=1024):
        text = self.turns[min(self.calls, len(self.turns) - 1)]
        self.calls += 1
        from src.llm import LLMResponse

        return LLMResponse(text=text, usage={"input_tokens": 1, "output_tokens": 1})


def _echo_tools() -> dict[str, Tool]:
    return {"calculator": REGISTRY["calculator"]}


def test_agent_runs_tool_then_finishes(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    script = [
        'Thought: compute\nAction: calculator\nAction Input: {"expression": "2+2"}',
        "Thought: done\nFinal Answer: The result is 4.",
    ]
    monkeypatch.setattr("src.agent.chat", _ScriptedLLM(script))
    agent = Agent(tools=_echo_tools(), runs_dir=tmp_path)
    result = agent.run("what is 2+2?")

    assert result.stopped == "final_answer"
    assert result.answer == "The result is 4."
    assert result.tools_used == ["calculator"]
    assert result.steps[0].observation == "2+2 = 4"
    # Trace is written and replayable.
    events = [json.loads(line) for line in open(result.trace_path)]
    assert events[0]["event"] == "start"
    assert any(e["event"] == "final" for e in events)
    assert events[-1]["event"] == "end"


def test_agent_recovers_from_bad_action(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    script = [
        "Thought: oops\nAction: calculator\nAction Input: not json and not bare-able for multiarg",
        'Thought: retry\nAction: calculator\nAction Input: {"expression": "1+1"}',
        "Final Answer: 2",
    ]
    # First turn: 'not json...' is a bare value -> coerced to expression -> calculator errors,
    # which still produces a recoverable observation rather than crashing.
    monkeypatch.setattr("src.agent.chat", _ScriptedLLM(script))
    agent = Agent(tools=_echo_tools(), runs_dir=tmp_path)
    result = agent.run("add")
    assert result.stopped == "final_answer"
    assert result.answer == "2"


def test_agent_stops_at_max_steps(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    # Always asks for a tool, never finalizes.
    loop = ['Action: calculator\nAction Input: {"expression": "1+1"}']
    monkeypatch.setattr("src.agent.chat", _ScriptedLLM(loop))
    agent = Agent(tools=_echo_tools(), max_steps=3, runs_dir=tmp_path)
    result = agent.run("loop forever")
    assert result.stopped == "max_steps"
    assert len(result.steps) == 3


def test_agent_session_memory_carries_context(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    captured: list[list[dict]] = []

    class _Capture(_ScriptedLLM):
        def __call__(self, messages, **kw):
            captured.append(list(messages))
            return super().__call__(messages, **kw)

    monkeypatch.setattr("src.agent.chat", _Capture(["Final Answer: ok"]))
    agent = Agent(tools=_echo_tools(), runs_dir=tmp_path)
    agent.run("first question")
    agent.run("second question")
    # The second run's first LLM call should include the first Q/A as prior turns.
    second_run_first_call = captured[1]
    joined = " ".join(m["content"] for m in second_run_first_call)
    assert "first question" in joined and "second question" in joined


# ---------------------------------------------------------------------------
# live paths (skipped when prerequisites are missing)
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not os.environ.get("EDGAR_USER_AGENT"), reason="needs EDGAR network access")
def test_lookup_metric_live_apple_rd() -> None:
    import httpx

    from src.tools.xbrl import lookup_metric

    try:
        out = lookup_metric("AAPL", "rd_expense", 2024)
    except httpx.HTTPError as exc:
        pytest.skip(f"SEC unreachable: {exc}")
    # SEC may be unreachable / rate-limited; only assert structure when it returned a value.
    if not out.startswith("Error"):
        assert "rd_expense FY2024" in out and "31,370 million" in out


def test_langgraph_importable() -> None:
    pytest.importorskip("langgraph")
    import src.agent_lg as lg

    assert hasattr(lg, "run_agent_lg")
