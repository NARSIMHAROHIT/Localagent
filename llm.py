"""The only place that talks to Ollama. Messages in, one message out."""

import requests

from config import CHAT_MODEL, MAX_REPLY_TOKENS, NUM_CTX, OLLAMA_URL, THINKING


class LLMError(RuntimeError):
    pass


def chat(messages, tools=None, temperature=0.0, format=None, think=None):
    """Send the whole conversation and get the next assistant message back.

    The model is stateless. `messages` IS the memory.
    """
    payload = {
        "model": CHAT_MODEL,
        "messages": messages,
        "stream": False,
        # Reasoning models write a long internal monologue by default. For a
        # tool-calling agent that is mostly wasted tokens, so it is off.
        "think": THINKING if think is None else think,
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

    try:
        r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=300)
    except requests.Timeout:
        raise LLMError(
            "Ollama took too long to reply. Usually the prompt is too big or too "
            "many tools are loaded. Check len(tool_specs())."
        )
    except requests.ConnectionError:
        raise LLMError(f"Can't reach Ollama at {OLLAMA_URL}. Is `ollama serve` running?")

    # Older Ollama builds do not know the top-level "think" field. Retry without it.
    if r.status_code == 400 and "think" in r.text.lower():
        payload.pop("think", None)
        try:
            r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=300)
        except requests.RequestException as e:
            raise LLMError(f"Ollama request failed: {e}")

    if r.status_code != 200:
        raise LLMError(f"Ollama {r.status_code}: {r.text.strip()}")

    return r.json()["message"]


if __name__ == "__main__":
    print(chat([{"role": "user", "content": "Say hi in exactly five words."}]))
