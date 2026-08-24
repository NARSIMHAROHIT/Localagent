import inspect
from typing import get_type_hints

REGISTRY = {}          # name -> {"fn": callable, "spec": dict}
MAX_RESULT_CHARS = 4000

PY_TO_JSON = {
    str: "string", int: "integer", float: "number",
    bool: "boolean", list: "array", dict: "object",
}

def _parse_arg_docs(doc: str) -> dict:
    """Pull 'name: description' lines out of an Args: block."""
    out, in_args = {}, False
    for line in (doc or "").splitlines():
        s = line.strip()
        if s.lower().startswith(("args:", "arguments:")):
            in_args = True
            continue
        if in_args:
            if not s:
                continue
            if s.endswith(":") or ":" not in s:
                break
            key, _, desc = s.partition(":")
            out[key.strip()] = desc.strip()
    return out

def tool(fn):
    """Decorator: registers fn as a tool and derives its JSON schema."""
    doc = inspect.getdoc(fn) or ""
    summary = doc.split("\n\n")[0].strip()
    arg_docs = _parse_arg_docs(doc)
    hints = get_type_hints(fn)

    props, required = {}, []
    for name, param in inspect.signature(fn).parameters.items():
        props[name] = {
            "type": PY_TO_JSON.get(hints.get(name, str), "string"),
            "description": arg_docs.get(name, ""),
        }
        if param.default is inspect.Parameter.empty:
            required.append(name)

    REGISTRY[fn.__name__] = {
        "fn": fn,
        "spec": {
            "type": "function",
            "function": {
                "name": fn.__name__,
                "description": summary,
                "parameters": {
                    "type": "object",
                    "properties": props,
                    "required": required,
                },
            },
        },
    }
    return fn


def tool_specs(names=None):
    """Schemas to hand the model. Pass names to expose only a subset."""
    items = REGISTRY.items()
    return [v["spec"] for k, v in items if names is None or k in names]


def call_tool(name: str, args: dict) -> str:
    """Execute a tool. ALWAYS returns a string — never raises."""
    entry = REGISTRY.get(name)
    if entry is None:
        return f"ERROR: no tool named '{name}'. Available: {', '.join(REGISTRY)}"
    try:
        result = entry["fn"](**(args or {}))
    except TypeError as e:
        return f"ERROR: bad arguments for '{name}': {e}"
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"

    text = result if isinstance(result, str) else repr(result)
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + f"\n...[truncated, {len(text)} chars total]"
    return text