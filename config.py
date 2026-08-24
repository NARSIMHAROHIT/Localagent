"""Every path and setting in one place.

Nothing in this project hard-codes a personal folder. Paths default to folders
inside the project, and every one can be overridden with an environment
variable or a `.env` file sitting next to this file.

    PROJECT_ROOT/
    └── data/                 <- everything the agent creates lives here
        ├── workspace/        <- the file sandbox the agent can read and write
        ├── agent.db          <- the SQL database it queries
        ├── knowledge.db      <- the knowledge base and graph
        └── guard_log.jsonl   <- a record of every tool attempt

To point the agent at a different folder, set AGENT_WORKSPACE. To move
everything at once, set AGENT_DATA_DIR.
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent


def _load_dotenv(path: Path) -> None:
    """Read a simple KEY=value file into the environment, if one exists.

    Values already set in the real environment always win.
    """
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv(PROJECT_ROOT / ".env")


def _path(env_name: str, default: Path) -> Path:
    return Path(os.environ.get(env_name, default)).expanduser().resolve()


# --- where things live -----------------------------------------------------

DATA_DIR = _path("AGENT_DATA_DIR", PROJECT_ROOT / "data")
WORKSPACE_DIR = _path("AGENT_WORKSPACE", DATA_DIR / "workspace")
DB_PATH = _path("AGENT_DB", DATA_DIR / "agent.db")
KB_PATH = _path("AGENT_KB", DATA_DIR / "knowledge.db")
GUARD_LOG_PATH = _path("AGENT_GUARD_LOG", DATA_DIR / "guard_log.jsonl")
MCP_CONFIG_PATH = _path("AGENT_MCP_CONFIG", PROJECT_ROOT / "mcp_servers.json")

# --- the model -------------------------------------------------------------

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
CHAT_MODEL = os.environ.get("AGENT_MODEL", "qwen3:4b")
EMBED_MODEL = os.environ.get("AGENT_EMBED_MODEL", "nomic-embed-text")
NUM_CTX = int(os.environ.get("AGENT_NUM_CTX", "16384"))
MAX_REPLY_TOKENS = int(os.environ.get("AGENT_MAX_REPLY_TOKENS", "1024"))
THINKING = os.environ.get("AGENT_THINKING", "0") == "1"

# --- behaviour -------------------------------------------------------------

GUARD_MODE = os.environ.get("AGENT_GUARD_MODE", "ask")   # readonly | ask | auto | open
MAX_STEPS = int(os.environ.get("AGENT_MAX_STEPS", "10"))
MAX_TOOL_CALLS = int(os.environ.get("AGENT_MAX_TOOL_CALLS", "25"))

API_KEY = os.environ.get("AGENT_API_KEY", "")            # empty = no auth (dev only)
API_HOST = os.environ.get("AGENT_API_HOST", "127.0.0.1")
API_PORT = int(os.environ.get("AGENT_API_PORT", "8000"))
SESSION_TTL_MINUTES = int(os.environ.get("AGENT_SESSION_TTL", "60"))

def ensure_dirs() -> None:
    """Create the folders the agent needs. Safe to call many times."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    KB_PATH.parent.mkdir(parents=True, exist_ok=True)
    GUARD_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def substitute(text: str) -> str:
    """Replace ${...} placeholders in config files with real paths.

    Lets mcp_servers.json stay portable instead of holding one person's
    home directory.
    """
    import sys

    replacements = {
        "${PROJECT_ROOT}": str(PROJECT_ROOT),
        "${DATA_DIR}": str(DATA_DIR),
        "${WORKSPACE}": str(WORKSPACE_DIR),
        "${PYTHON}": sys.executable,
    }
    for key, value in replacements.items():
        text = text.replace(key, value)
    return text


ensure_dirs()


if __name__ == "__main__":
    for name in (
        "PROJECT_ROOT", "DATA_DIR", "WORKSPACE_DIR", "DB_PATH", "KB_PATH",
        "GUARD_LOG_PATH", "MCP_CONFIG_PATH", "OLLAMA_URL", "CHAT_MODEL",
        "EMBED_MODEL", "NUM_CTX", "MAX_REPLY_TOKENS", "THINKING",
        "GUARD_MODE", "MAX_STEPS", "MAX_TOOL_CALLS",
    ):
        print(f"{name:20} {globals()[name]}")
