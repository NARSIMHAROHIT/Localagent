# Localagent

A local AI agent built from scratch — no agent framework. It runs on
[Ollama](https://ollama.com), calls tools, remembers documents with graph RAG,
speaks MCP in both directions, and asks before it does anything destructive.

Roughly 1,500 lines of plain Python. Every part is meant to be readable.

## What it can do

- **Files** — list, read, write, edit, search and delete, locked inside one sandbox folder
- **SQL** — inspect the schema, run read-only queries, insert, update and delete rows
- **Web** — search, fetch pages and pull out readable text, with local-network addresses blocked
- **Documents** — save results as a PDF
- **Knowledge base** — store documents as chunks and search them by meaning
- **Graph RAG** — pull entities and relationships out of documents, then answer
  "how is X connected to Y" by walking the graph
- **MCP** — use tools from other MCP servers, and publish its own tools to other apps
- **Guardrails** — a permission policy with an approval prompt, plus secret redaction and an audit log

## Requirements

- Python 3.10+
- [Ollama](https://ollama.com) running locally
- Optional: Node (`npx`) or `uv` (`uvx`) if you want to use third-party MCP servers

## Setup

```bash
git clone git@github.com:NARSIMHAROHIT/Localagent.git
cd Localagent

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

ollama pull qwen3:4b               # a tool-calling chat model
ollama pull nomic-embed-text       # the embedding model

python scripts/setup_db.py         # create the demo SQL database
python scripts/seed_workspace.py   # put sample files in the workspace

python agent.py
```

## Where things live

Nothing is hard-coded to a personal folder. Everything the agent creates goes
into `data/`, next to the code, and `data/` is git-ignored.

```
Localagent/
├── agent.py              the loop and the REPL
├── config.py             every path and setting, in one file
├── llm.py                the only code that talks to Ollama
├── embeddings.py         text -> vectors
├── guardrails.py         the permission policy
├── mcp_client.py         use other people's MCP tools
├── mcp_server.py         publish our tools over MCP
├── mcp_servers.json      which MCP servers to start
├── tools/
│   ├── registry.py       @tool decorator, schemas, dispatcher
│   ├── basic.py          time, arithmetic
│   ├── files.py          the sandboxed file tools
│   ├── database.py       the SQL tools
│   ├── web.py            search and fetch
│   ├── documents.py      PDF output
│   ├── knowledge.py      the knowledge base
│   └── graph.py          graph RAG
├── scripts/              one-time setup helpers
├── samples/              example documents
└── data/                 created at run time, git-ignored
    ├── workspace/        the only folder the file tools may touch
    ├── agent.db
    ├── knowledge.db
    └── guard_log.jsonl
```

## Changing the folders

Every path has a default and an environment variable. Copy `.env.example` to
`.env` and uncomment what you want to change:

```bash
cp .env.example .env
```

```ini
AGENT_WORKSPACE=~/Documents/agent-workspace
AGENT_GUARD_MODE=auto
AGENT_MODEL=qwen3:8b
```

Or set them for a single run:

```bash
AGENT_WORKSPACE=~/Projects/report-drafts python agent.py
```

Check what got picked up:

```bash
python config.py
```

## Try it

```
you> what files are in the workspace?
you> what is the total order amount per customer?
you> save https://en.wikipedia.org/wiki/Knowledge_graph to the knowledge base
you> build the knowledge graph
you> how is Anita Rao connected to Fenwick Systems?
you> read https://example.com and save a summary as reports/summary.pdf
you> delete the file todo.txt
```

The last one will stop and ask you first.

## Safety

Limits live in Python, not in the prompt, so the model cannot talk its way past
them:

- File tools resolve every path and refuse anything outside the workspace,
  including symlinks that point out of it
- Read queries run over a genuinely read-only SQLite connection
- Insert and update never let the model write SQL — it supplies values, the code
  builds the statement with placeholders
- `db_update` and `db_delete` require a filter, so "change every row" is impossible
- Web fetches resolve the hostname and refuse private and loopback addresses
- Deleting anything needs a typed approval, and every attempt is logged to
  `data/guard_log.jsonl`

Guard modes: `readonly`, `ask` (default), `auto`, `open`.

## Using the tools from another app

`mcp_server.py` publishes every tool over MCP. To use them in Claude Desktop,
add this to `claude_desktop_config.json` with real absolute paths:

```json
{
  "mcpServers": {
    "localagent": {
      "command": "/absolute/path/Localagent/.venv/bin/python",
      "args": ["/absolute/path/Localagent/mcp_server.py"]
    }
  }
}
```

To test any tool without the model in the way:

```bash
mcp dev mcp_server.py
```

## Adding a tool

Write a function, decorate it, import the module. The JSON schema is generated
from your type hints and docstring.

```python
from .registry import tool

@tool
def word_count(text: str) -> str:
    """Count the words in a piece of text. Use this instead of counting
    yourself, because you miscount long passages.

    Args:
        text: The text to count.
    """
    return str(len(text.split()))
```

Then add the name to `DEFAULT_TOOLS` in `agent.py` so the model is offered it,
and classify it in `guardrails.py` (`SAFE`, `WRITE` or `DANGER`) — anything
unclassified is treated as a write and will prompt for approval.

See `MCP_GUIDE.md` for the longer version, including how to add MCP servers and
when to prefer them over local tools.

## Notes

- Tool schemas go into the prompt on every call. Keep the offered list under
  ~25 or the model starts choosing badly. `agent.py` prints both counts at startup.
- Building the graph costs one model call per chunk, so it is slow. Searching it
  costs none.
- `web_search` scrapes DuckDuckGo's HTML. If the layout changes, swap in a search
  API — it is one function.
