from __future__ import annotations

import ast
import math
import operator
from pathlib import Path
from urllib.parse import quote_plus, urlsplit

from .models import SearchResult

_BINARY = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCTIONS = {
    "sqrt": math.sqrt, "abs": abs, "round": round, "sin": math.sin, "cos": math.cos,
    "tan": math.tan, "log": math.log, "log10": math.log10,
}
_CONSTANTS = {"pi": math.pi, "e": math.e}
# Keeps a mistyped power from freezing the search box.
_MAX_EXPONENT = 1000
_MAX_LENGTH = 100


def calculate(text: str) -> str | None:
    """Evaluate plain arithmetic; return None for anything that is not a sum."""
    expression = text.strip().replace("^", "**").replace("×", "*").replace("÷", "/")
    if not expression or len(expression) > _MAX_LENGTH:
        return None
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, ValueError):
        return None
    # A bare number or word is a search, not a calculation.
    if not isinstance(tree.body, (ast.BinOp, ast.Call)):
        return None
    try:
        value = _evaluate(tree.body)
    except (ValueError, TypeError, ArithmeticError):
        return None
    return _format(value)


def _evaluate(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    if isinstance(node, ast.Name) and node.id in _CONSTANTS:
        return _CONSTANTS[node.id]
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_evaluate(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        left, right = _evaluate(node.left), _evaluate(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > _MAX_EXPONENT:
            raise ValueError("exponent too large")
        return _BINARY[type(node.op)](left, right)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _FUNCTIONS
        and not node.keywords
    ):
        return _FUNCTIONS[node.func.id](*(_evaluate(argument) for argument in node.args))
    raise ValueError("unsupported expression")


def _format(value: float) -> str | None:
    if isinstance(value, complex) or not math.isfinite(value):
        return None
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        value = int(value)
    return str(value) if isinstance(value, int) else f"{value:.10g}"


def calculator_result(text: str) -> SearchResult | None:
    answer = calculate(text)
    if answer is None:
        return None
    return SearchResult(
        kind="calc",
        name=f"= {answer}",
        detail=f"{text.strip()}  |  Enter copies the answer",
        created_at=None,
        payload=answer,
    )


def web_result(text: str, url_template: str) -> SearchResult | None:
    query = text.strip()
    if not query or "{query}" not in url_template:
        return None
    return SearchResult(
        kind="web",
        name=f"Search the web for “{query}”",
        detail=urlsplit(url_template).netloc,
        created_at=None,
        payload=url_template.replace("{query}", quote_plus(query)),
    )


def recent_files(limit: int) -> list[SearchResult]:
    """Files the desktop recorded as recently used, newest first."""
    import gi

    gi.require_version("Gtk", "4.0")
    from gi.repository import Gio, Gtk

    items = []
    for item in Gtk.RecentManager.get_default().get_items():
        path = Gio.File.new_for_uri(item.get_uri()).get_path()
        visited = item.get_visited()
        if path and visited and Path(path).exists():
            items.append((visited.to_unix(), Path(path)))
    items.sort(key=lambda entry: entry[0], reverse=True)
    return [
        SearchResult(
            kind="folder" if path.is_dir() else "file",
            name=path.name,
            detail=str(path.parent),
            created_at=None,
            path=path,
            source_path=path,
        )
        for _visited, path in items[:limit]
    ]
