import ast
import operator
from datetime import datetime
from .registry import tool

@tool
def get_current_time(timezone: str = "local") -> str:
    """Get the current date and time. Use this whenever the user asks about
    today, now, or anything time-sensitive.

    Args:
        timezone: Ignored for now; always returns the machine's local time.
    """
    return datetime.now().astimezone().isoformat(timespec="seconds")


_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv, ast.USub: operator.neg, ast.UAdd: operator.pos,
}

def _safe_eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("unsupported expression")

@tool
def calculate(expression: str) -> str:
    """Evaluate an arithmetic expression. Use this for ANY math instead of
    computing it yourself, since you make arithmetic mistakes.

    Args:
        expression: A math expression like "1234 * (56 + 7.8)".
    """
    return str(_safe_eval(ast.parse(expression, mode="eval").body))
@tool
def describe_image(path: str, question: str = "Describe this image in detail") -> str:
    """Look at an image file in the workspace and describe what is in it."""
    # read file → base64 → call a vision model → return the text description