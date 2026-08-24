"""Turn text into number-vectors so we can search by meaning."""

import numpy as np
import requests

from config import EMBED_MODEL, OLLAMA_URL


def _normalise(vec):
    """Scale to length 1, so comparing two vectors is a single multiply."""
    arr = np.asarray(vec, dtype=np.float32)
    size = np.linalg.norm(arr)
    return arr / size if size else arr


def embed_texts(texts):
    """Return one normalised numpy vector per input string."""
    if isinstance(texts, str):
        texts = [texts]

    # Newer Ollama: one call for the whole batch.
    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/embed",
            json={"model": EMBED_MODEL, "input": texts},
            timeout=180,
        )
        if r.status_code == 200:
            return [_normalise(v) for v in r.json()["embeddings"]]
    except requests.RequestException:
        pass

    # Older Ollama: one call per string.
    out = []
    for t in texts:
        r = requests.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={"model": EMBED_MODEL, "prompt": t},
            timeout=180,
        )
        if r.status_code != 200:
            raise RuntimeError(
                f"embedding failed ({r.status_code}): {r.text[:200]}. "
                f"Did you run: ollama pull {EMBED_MODEL}?"
            )
        out.append(_normalise(r.json()["embedding"]))
    return out


if __name__ == "__main__":
    v = embed_texts("hello")
    print(f"{EMBED_MODEL} -> {len(v[0])} dimensions")
