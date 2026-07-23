"""LangGraph rewrite of the ReAct loop (Wave 4 A/B).

The same Thought → Action → Observation loop as `src.agent`, expressed as a
LangGraph `StateGraph` with two nodes — `reason` (call the LLM, parse) and `act`
(run the tool) — and a conditional edge that ends on a Final Answer or the step
limit. It reuses the parser, prompt, and tools from `src.agent`, so the only
variable is the orchestration: the comparison report contrasts the explicit
hand-written `while` loop with this graph definition. Same observations, same
trace format, so a run is replayable identically.

Public surface
--------------
- `run_agent_lg(question, ...)` -> AgentResult (mirrors src.agent.run_agent)
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, StateGraph

from src.agent import (
    _MAX_STEPS,
    _MAX_TOKENS,
    _OBSERVATION_CAP,
    _PROMPT_TEMPLATE,
    _RUNS_DIR,
    _STOP_MARKER,
    _THOUGHT_RE,
    AgentResult,
    Step,
    _parse,
)
from src.llm import chat
from src.tools import REGISTRY, render_tools, run_tool


class _State(TypedDict, total=False):
    messages: list[dict]
    steps: list[Step]
    pending: dict | None
    answer: str
    stopped: str


def _build_graph(system: str, max_steps: int):
    def reason(state: _State) -> _State:
        steps = state["steps"]
        messages = state["messages"]
        if len(steps) >= max_steps:
            return {
                "stopped": "max_steps",
                "answer": "Stopped: reached the step limit without a final answer.",
            }
        resp = chat(messages, system=system, temperature=0.0, max_tokens=_MAX_TOKENS)
        raw = _STOP_MARKER.split(resp.text, maxsplit=1)[0].strip()
        messages.append({"role": "assistant", "content": raw})
        thought_m = _THOUGHT_RE.search(raw)
        thought = thought_m.group(1).strip() if thought_m else ""

        kind, payload = _parse(raw, REGISTRY)
        if kind == "final":
            steps.append(Step(thought, None, None, None, raw))
            return {"messages": messages, "steps": steps,
                    "answer": str(payload), "stopped": "final_answer"}
        if kind == "invalid":
            obs = (
                f"Error: {payload}. Respond with either 'Action:' + 'Action Input:' "
                "(single-line JSON) or 'Final Answer:'."
            )
            steps.append(Step(thought, None, None, obs, raw))
            messages.append({"role": "user", "content": f"Observation: {obs}"})
            return {"messages": messages, "steps": steps, "pending": None}
        name, args = payload  # type: ignore[misc]
        return {"messages": messages, "pending": {"thought": thought, "name": name,
                                                  "args": args, "raw": raw}}

    def act(state: _State) -> _State:
        p = state["pending"]
        obs = run_tool(p["name"], p["args"])
        if len(obs) > _OBSERVATION_CAP:
            obs = obs[:_OBSERVATION_CAP] + " …[truncated]"
        state["steps"].append(Step(p["thought"], p["name"], p["args"], obs, p["raw"]))
        state["messages"].append({"role": "user", "content": f"Observation: {obs}"})
        return {"messages": state["messages"], "steps": state["steps"], "pending": None}

    def route(state: _State) -> str:
        if state.get("stopped"):
            return END
        return "act" if state.get("pending") else "reason"

    graph = StateGraph(_State)
    graph.add_node("reason", reason)
    graph.add_node("act", act)
    graph.set_entry_point("reason")
    graph.add_conditional_edges("reason", route, {"act": "act", "reason": "reason", END: END})
    graph.add_edge("act", "reason")
    return graph.compile()


def run_agent_lg(
    question: str,
    *,
    max_steps: int = _MAX_STEPS,
    runs_dir: Path = _RUNS_DIR,
) -> AgentResult:
    """Run a question through the LangGraph ReAct graph; return an AgentResult."""
    question = str(question).strip()
    if not question:
        raise ValueError("question must not be empty")

    system = _PROMPT_TEMPLATE.replace("{tools}", render_tools(REGISTRY)).replace(
        "{tool_names}", ", ".join(REGISTRY)
    )
    app = _build_graph(system, max_steps)
    # recursion_limit bounds graph super-steps; 2 nodes/loop iteration + slack.
    final_state = app.invoke(
        {
            "messages": [{"role": "user", "content": f"Question: {question}"}],
            "steps": [],
            "pending": None,
            "answer": "",
            "stopped": "",
        },
        {"recursion_limit": max_steps * 2 + 4},
    )

    run_id = uuid.uuid4().hex[:12]
    runs_dir.mkdir(parents=True, exist_ok=True)
    trace_path = runs_dir / f"{run_id}.jsonl"
    steps: list[Step] = final_state["steps"]
    result = AgentResult(
        question=question,
        answer=final_state.get("answer", ""),
        steps=steps,
        trace_path=str(trace_path),
        stopped=final_state.get("stopped", ""),
    )
    with trace_path.open("w") as trace:
        trace.write(json.dumps({"event": "start", "run_id": run_id,
                                "question": question, "engine": "langgraph"}) + "\n")
        for i, s in enumerate(steps, start=1):
            is_final = s.action is None and i == len(steps) and result.stopped == "final_answer"
            ev = "final" if is_final else "step"
            trace.write(json.dumps({
                "event": ev, "step": i, "thought": s.thought, "action": s.action,
                "action_input": s.action_input, "observation": s.observation,
                **({"answer": result.answer} if ev == "final" else {}),
            }) + "\n")
        trace.write(json.dumps({"event": "end", "stopped": result.stopped,
                                "steps": len(steps), "tools_used": result.tools_used}) + "\n")
    return result


def _main() -> None:
    import sys

    if len(sys.argv) < 2:
        print('Usage: python -m src.agent_lg "your question"', file=sys.stderr)
        raise SystemExit(2)
    result = run_agent_lg(" ".join(sys.argv[1:]))
    print()
    for i, step in enumerate(result.steps, start=1):
        if step.action:
            print(f"[step {i}] {step.action}({json.dumps(step.action_input)})")
            print(f"         → {step.observation.splitlines()[0][:140]}")
    print(f"\nAnswer: {result.answer}")
    print(f"\n({result.stopped}, {len(result.steps)} steps, trace: {result.trace_path})")


if __name__ == "__main__":
    _main()
