"""The Tool spec, in its own module so tool implementations and the registry can
both import it without a circular dependency through `src.tools.__init__`."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Tool:
    """A single agent-callable tool.

    `parameters` maps each argument name to a one-line description; the agent
    sees it in the prompt and must pass matching keys in its Action Input JSON.
    `func` returns the observation string fed back into the loop.
    """

    name: str
    description: str
    parameters: dict[str, str]
    func: Callable[..., str]

    def run(self, args: dict) -> str:
        return self.func(**args)
