"""The only place that talks to Ollama. Messages in, one message out."""

import re
import time

import requests

from config import CHAT_MODEL, MAX_REPLY_TOKENS, NUM_CTX, OLLAMA_URL, THINKING

THINK_BLOCK = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


class LLMError(RuntimeError):
    pass


def _no_think(messages):
    """Older Ollama builds ignore the `think` field. Qwen3 also honours a
    /no_think marker in the prompt, so add one to the last user message.

    Builds a new list and a new dict, so the caller's history is not mutated.
    """
    out = list(messages)
    for i in range(len(out) - 1, -1, -1):
        if out[i].get("role") == "user":
            content = out[i].get("content") or ""
            if "/no_think" not in content:
                out[i] = {**out[i], "content": content + " /no_think"}
            break
    return out


def _strip_thinking(message):
    """If the model reasoned anyway, keep only the real answer."""
    content = message.get("content") or ""
    if "</think>" in content:
        message["content"] = THINK_BLOCK.sub("", content).strip()
    return message

def chat_with_stats(messages, tools=None, temperature=0.0, format=None, think=None):
    """Same as chat(), but also returns what the call cost."""
    use_think = THINKING if think is None else think
    payload = {
        "model": CHAT_MODEL,
        "messages": messages if use_think else _no_think(messages),
        "stream": False,
        "think": use_think,
        "options": {
            "temperature": temperature,
            "num_ctx": NUM_CTX,
            "num_predict": MAX_REPLY_TOKENS,
        },
    }
    if tools:
        payload["tools"] = tools
    if format:
        payload["format"] = format

    started = time.perf_counter()
    try:
        r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=300)
    except requests.Timeout:
        raise LLMError(
            "Ollama took too long to reply. Usually the prompt is too big or too "
            "many tools are loaded. Check len(tool_specs())."
        )
    except requests.ConnectionError:
        raise LLMError(f"Can't reach Ollama at {OLLAMA_URL}. Is `ollama serve` running?")

    if r.status_code == 400 and "think" in r.text.lower():
        payload.pop("think", None)
        try:
            r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=300)
        except requests.RequestException as e:
            raise LLMError(f"Ollama request failed: {e}")

    if r.status_code != 200:
        raise LLMError(f"Ollama {r.status_code}: {r.text.strip()}")

    body = r.json()
    stats = {
        "seconds": round(time.perf_counter() - started, 3),
        "prompt_tokens": body.get("prompt_eval_count", 0),
        "reply_tokens": body.get("eval_count", 0),
        # Ollama reports durations in nanoseconds
        "load_seconds": round(body.get("load_duration", 0) / 1e9, 3),
        "model": body.get("model", CHAT_MODEL),
        "done_reason": body.get("done_reason", ""),
        "tools_offered": len(tools or []),
    }
    return _strip_thinking(body["message"]), stats


def chat(messages, tools=None, temperature=0.0, format=None, think=None):
    """Messages in, one message out. Use chat_with_stats if you want the numbers."""
    message, _ = chat_with_stats(messages, tools, temperature, format, think)
    return message


if __name__ == "__main__":
    print(chat([{"role": "user", "content": "Say hi in exactly five words."}]))
