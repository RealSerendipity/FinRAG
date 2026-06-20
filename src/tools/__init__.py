"""Agent tools — a small registry the ReAct loop (Wave 4) dispatches against.

Five tools ship in Wave 4: retrieve_filing, lookup_metric, compare_companies,
web_search, calculator. They are interchangeable behaviors the agent selects at
runtime, so a stable `Tool` spec + a name→tool registry is warranted here (the
"five concrete implementations at once" case, not premature abstraction). Each
tool is a plain function returning an *observation string*; the spec only adds
the name / description / parameter docs the prompt and dispatcher need.

Public surface
--------------
- `Tool` — name, description, parameter docs, callable
- `REGISTRY` — name → Tool for the default toolset
- `run_tool(name, args)` — dispatch with uniform error-to-observation handling
- `render_tools(tools)` — format a toolset for the ReAct system prompt
"""

from __future__ import annotations

from .calculator import TOOL as _calculator
from .retrieve_filing import TOOL as _retrieve_filing
from .spec import Tool
from .web_search import TOOL as _web_search
from .xbrl import COMPARE_TOOL as _compare_companies
from .xbrl import LOOKUP_TOOL as _lookup_metric

__all__ = ["Tool", "REGISTRY", "run_tool", "render_tools"]


_TOOLS: tuple[Tool, ...] = (
    _retrieve_filing,
    _lookup_metric,
    _compare_companies,
    _web_search,
    _calculator,
)

REGISTRY: dict[str, Tool] = {t.name: t for t in _TOOLS}


def run_tool(name: str, args: dict, *, registry: dict[str, Tool] | None = None) -> str:
    """Dispatch a tool call, converting any failure into an observation string.

    Tool errors must not crash the agent loop: a bad ticker or malformed
    arithmetic should come back as an Observation the model can recover from,
    same as a successful result.
    """
    registry = registry or REGISTRY
    tool = registry.get(name)
    if tool is None:
        return f"Error: unknown tool {name!r}. Available: {', '.join(registry)}"
    if not isinstance(args, dict):
        return f"Error: Action Input for {name!r} must be a JSON object, got {type(args).__name__}"
    try:
        return tool.run(args)
    except TypeError as exc:
        # Wrong / missing argument names — surface the expected parameters.
        return (
            f"Error calling {name!r}: {exc}. "
            f"Expected arguments: {', '.join(tool.parameters) or '(none)'}"
        )
    except Exception as exc:  # noqa: BLE001 — observations must capture every failure
        return f"Error calling {name!r}: {type(exc).__name__}: {exc}"


def render_tools(tools: dict[str, Tool] | None = None) -> str:
    """Render the toolset as a prompt block: one tool per line with its args."""
    tools = tools or REGISTRY
    lines = []
    for tool in tools.values():
        params = ", ".join(f"{k} ({v})" for k, v in tool.parameters.items()) or "no arguments"
        lines.append(f"- {tool.name}: {tool.description}\n    arguments: {params}")
    return "\n".join(lines)
