"""calculator tool — evaluate an arithmetic expression safely.

Financial questions often end in a ratio or a percent change the LLM should not
compute in its head (it is unreliable at multi-digit arithmetic). This evaluates
a restricted expression grammar via `ast` — numbers and the operators
+ - * / // % ** and parentheses only. No names, calls, or attribute access, so
there is no `eval` injection surface.
"""

from __future__ import annotations

import ast
import operator

from .spec import Tool

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
# A few safe numeric builtins the model reaches for (e.g. round a ratio). Each
# takes only the evaluated numeric args — no attribute access or arbitrary names.
_FUNCS = {"round": round, "abs": abs, "min": min, "max": max}


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError(f"unsupported constant: {node.value!r}")
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        return _BIN_OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id not in _FUNCS or node.keywords:
            raise ValueError(f"unsupported function: {getattr(node.func, 'id', '?')!r}")
        return _FUNCS[node.func.id](*[_eval(a) for a in node.args])
    raise ValueError(f"unsupported expression element: {type(node).__name__}")


def calculator(expression: str) -> str:
    """Evaluate `expression` and return the numeric result as a string."""
    expr = str(expression).strip()
    if not expr:
        return "Error: empty expression"
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        return f"Error: could not parse expression {expr!r}: {exc.msg}"
    try:
        result = _eval(tree.body)
    except ZeroDivisionError:
        return "Error: division by zero"
    except ValueError as exc:
        return f"Error: {exc}"
    # Render integers without a trailing .0; keep float precision otherwise.
    if isinstance(result, float) and result.is_integer():
        result = int(result)
    return f"{expr} = {result}"


TOOL = Tool(
    name="calculator",
    description="Evaluate an arithmetic expression (ratios, percent changes, sums). "
    "Numbers and + - * / // % ** and parentheses only.",
    parameters={"expression": "arithmetic expression, e.g. '(416161-391035)/391035*100'"},
    func=calculator,
)
