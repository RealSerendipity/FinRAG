"""Wave 4 agent eval — run the ReAct agent over eval/agent_questions.jsonl.

Per item: run a fresh agent (no carried memory), judge the final answer for
correctness against the expected answer (LLM judge, reused from Wave 2), and
record tool-call accuracy (did the agent invoke the tools the task needs?) and
step count. Aggregates task success rate, tool-call accuracy, and average steps,
then writes eval/reports/wave_4.md.

Network note: lookup_metric / compare_companies hit the SEC XBRL API; when SEC is
unreachable those items surface tool-error observations and are reported as
network-blocked, separate from genuine agent failures.

Usage
-----
    uv run python eval/agent_eval.py [--limit N] [--engine react|langgraph] [--out PATH]
    uv run python eval/run_eval.py --suite agent      # same thing
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from eval import metrics  # noqa: E402

QUESTIONS_PATH = Path(__file__).parent / "agent_questions.jsonl"
DEFAULT_REPORT = Path(__file__).parent / "reports" / "wave_4.md"
PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "react_v1.txt"

# Observation markers that mean a tool could not reach an external service, so a
# wrong/empty answer is a network outage rather than an agent-logic failure.
_NETWORK_MARKERS = ("ConnectError", "SSL", "web_search unavailable", "request failed", "Timeout")


def load_questions(path: Path) -> list[dict]:
    items = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    ids = [it["id"] for it in items]
    if len(ids) != len(set(ids)):
        sys.exit("agent_questions.jsonl contains duplicate ids")
    return items


def check_env() -> None:
    missing = [v for v in ("NVIDIA_API_KEY", "LLM_PROVIDER") if not os.environ.get(v)]
    if missing:
        sys.exit(f"Missing required env vars: {missing}. Configure .env first.")


def _runner(engine: str):
    if engine == "langgraph":
        from src.agent_lg import run_agent_lg
        return run_agent_lg
    from src.agent import run_agent
    return run_agent


def run_item(item: dict, runner) -> dict:
    error = None
    try:
        result = runner(item["question"])
    except Exception as exc:  # noqa: BLE001 — one item must not abort the sweep
        return {
            "item": item, "answer": "", "steps": 0, "tools_used": [],
            "tool_match": False, "correct": None, "reason": f"run error: {exc}",
            "judge": "error", "network_blocked": False, "error": f"{type(exc).__name__}: {exc}",
        }

    # Tool-call accuracy: the agent stayed on a valid tool path for this task.
    # A numeric fact may legitimately come from retrieve_filing OR lookup_metric,
    # so we score against the set of acceptable tools (not one exact prediction):
    # it must use tools (no answering from memory), every tool used must be
    # acceptable, and the calculator must appear when the task needs arithmetic.
    acceptable = set(item.get("acceptable_tools", []))
    requires_calc = bool(item.get("requires_calc", False))
    tools_used = result.tools_used
    used_set = set(tools_used)
    tool_match = (
        bool(used_set)
        and used_set.issubset(acceptable)
        and (not requires_calc or "calculator" in used_set)
    )
    observations = " ".join(s.observation or "" for s in result.steps)
    network_blocked = any(m in observations for m in _NETWORK_MARKERS)

    verdict = metrics.judge_answer(item["question"], item["expected_answer"], result.answer, [])
    return {
        "item": item,
        "answer": result.answer,
        "steps": len(result.steps),
        "tools_used": tools_used,
        "tool_match": tool_match,
        "correct": verdict["correct"],
        "reason": verdict["reason"],
        "judge": verdict["judge"],
        "network_blocked": network_blocked,
        "error": error,
    }


def summarize(results: list[dict]) -> dict:
    reachable = [r for r in results if not r["network_blocked"]]
    correct_vals = [1.0 if r["correct"] else 0.0 for r in results if r["correct"] is not None]
    reachable_correct = [
        1.0 if r["correct"] else 0.0 for r in reachable if r["correct"] is not None
    ]
    return {
        "n_total": len(results),
        "n_reachable": len(reachable),
        "n_network_blocked": len(results) - len(reachable),
        "task_success": metrics.mean(correct_vals),
        "task_success_reachable": metrics.mean(reachable_correct),
        "tool_accuracy": metrics.mean([1.0 if r["tool_match"] else 0.0 for r in results]),
        "avg_steps": metrics.mean([float(r["steps"]) for r in results]),
        "errors": sum(1 for r in results if r["error"]),
    }


def fmt(value, digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}"


def write_report(results: list[dict], s: dict, out_path: Path, engine: str) -> None:
    prompt_sha = hashlib.sha256(PROMPT_PATH.read_bytes()).hexdigest()[:12]
    provider = os.environ.get("LLM_PROVIDER", "<unset>")
    model = os.environ.get("LLM_MODEL", "<default>")
    categories = sorted({r["item"]["category"] for r in results})

    lines = [
        f"# Wave 4 — Agent eval report (engine: {engine})",
        "",
        f"- Suite: `eval/agent_questions.jsonl` ({s['n_total']} multi-step tasks, "
        f"categories: {', '.join(categories)})",
        "- Tools: retrieve_filing, lookup_metric, compare_companies, web_search, calculator",
        f"- Agent: hand-written ReAct loop (`src/agent.py`), max 8 steps, "
        f"prompt `prompts/react_v1.txt` (sha256 `{prompt_sha}`)",
        f"- LLM: `{provider}` / `{model}`; judge: see Wave 2 config (correctness only)",
        f"- SEC reachable this run: {s['n_reachable']}/{s['n_total']} items "
        f"({s['n_network_blocked']} network-blocked on the XBRL/web tools)",
        "",
        "## Headline metrics",
        "",
        f"- **task success rate** (all items): {fmt(s['task_success'])}",
        f"- **task success rate** (SEC-reachable items only): {fmt(s['task_success_reachable'])}",
        f"- **tool-call accuracy** (expected tools invoked): {fmt(s['tool_accuracy'])}",
        f"- **average steps / task**: {fmt(s['avg_steps'], 1)}",
        f"- run errors: {s['errors']}",
        "",
        "Task success = LLM-judge correctness of the final answer vs the expected "
        "answer. Tool-call accuracy = fraction of tasks where every tool the task "
        "needs was actually invoked. Network-blocked items (SEC XBRL unreachable) "
        "are reported separately so an outage is not counted as an agent failure.",
        "",
        "## Per-item results",
        "",
        "| id | category | steps | tools used | acceptable tools | tool✓ | correct | blocked |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        it = r["item"]
        calc = " (+calc)" if it.get("requires_calc") else ""
        acceptable = ", ".join(it.get("acceptable_tools", []))
        lines.append(
            f"| `{it['id']}` | {it['category']} | {r['steps']} "
            f"| {', '.join(r['tools_used']) or '—'} | {acceptable}{calc} "
            f"| {'yes' if r['tool_match'] else 'no'} "
            f"| {'—' if r['correct'] is None else ('yes' if r['correct'] else 'no')} "
            f"| {'yes' if r['network_blocked'] else ''} |"
        )

    lines += ["", "## Answers + judge reasons", ""]
    for r in results:
        it = r["item"]
        lines += [
            f"### `{it['id']}` ({it['category']})",
            "",
            f"**Question.** {it['question']}",
            "",
            f"**Expected.** {it['expected_answer']}",
            "",
            f"**Answer.** {r['answer']}",
            "",
            f"**Tools.** used={r['tools_used']} acceptable={it.get('acceptable_tools', [])} "
            f"(match={r['tool_match']}){' — NETWORK BLOCKED' if r['network_blocked'] else ''}",
            "",
        ]
        if r["reason"]:
            lines += [f"**Judge ({r['judge']}).** correct={r['correct']} — {r['reason']}", ""]

    lines += [
        "## Theory ↔ Practice",
        "",
        "ReAct (Yao 2022) interleaves reasoning traces with tool actions; this "
        "agent is a hand-written Thought → Action → Observation loop (no framework) "
        "so the control flow is fully inspectable and every step is logged to "
        "`runs/<id>.jsonl` for replay. The split between retrieve_filing (RAG over "
        "prose) and lookup_metric (structured XBRL) follows the rule of thumb that "
        "numeric questions should hit structured data, not chunked text. The "
        "LangGraph rewrite (`src/agent_lg.py`) expresses the identical loop as a "
        "two-node graph; the side-by-side is in `eval/reports/wave_4_langgraph_compare.md`.",
        "",
    ]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines))
    print(f"\nWrote {out_path}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="run only the first N items")
    parser.add_argument("--engine", choices=("react", "langgraph"), default="react")
    parser.add_argument("--out", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)

    check_env()
    items = load_questions(QUESTIONS_PATH)
    if args.limit:
        items = items[: args.limit]
    runner = _runner(args.engine)

    results = []
    for i, item in enumerate(items, start=1):
        print(f"[{i}/{len(items)}] {item['id']}", flush=True)
        results.append(run_item(item, runner))

    s = summarize(results)
    write_report(results, s, args.out, args.engine)
    headline = {
        k: (round(v, 4) if isinstance(v, float) else v)
        for k, v in s.items()
    }
    print("SUMMARY " + json.dumps(headline))


if __name__ == "__main__":
    main()
