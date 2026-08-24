# Tools and MCP — a working guide

How to add capabilities to the agent, and how to decide which kind to add.

---

## 1. The two kinds of tools

Everything the agent can do lives in one place: `REGISTRY` in `tools/registry.py`.
Things get into that registry in two ways.

**Local tools** — plain Python functions in `tools/*.py`, marked with `@tool`.
They run inside the agent's own process. Calling one is a normal function call.

**MCP tools** — tools provided by a separate program that speaks MCP.
`mcp_client.py` connects to that program, asks what tools it has, and copies
them into the same registry.

Once they are in the registry, the agent cannot tell them apart. Same schema
format, same dispatcher, same error handling. The difference is only where the
code actually runs.

```
tools/*.py        --@tool-->        REGISTRY  <--register_mcp_server--  other programs
                                       |
                                  agent.py loop
```

There is also a third piece, going the other way:

**`mcp_server.py`** — publishes *your* tools so other apps (Claude Desktop,
Claude Code, editors) can use them. Your agent does not need this file to run.

---

## 2. Adding a new local tool

Three steps. This is the default way to add a capability.

### Step 1 — write the function

In an existing file under `tools/`, or a new one:

```python
from .registry import tool

@tool
def word_count(text: str, unique_only: bool = False) -> str:
    """Count the words in a piece of text. Use this instead of counting
    yourself, because you miscount long passages.

    Args:
        text: The text to count.
        unique_only: Count distinct words instead of all words.
    """
    words = text.split()
    return str(len(set(words)) if unique_only else len(words))
```

Rules that matter:

- **Type hints are required.** They become the JSON schema.
- **The first line of the docstring is prompt text.** The model reads it to
  decide whether to call the tool. Write it as an instruction: say *when* to
  use it, not just what it does.
- **The `Args:` block becomes per-parameter descriptions.** Keep the exact
  `name: description` shape or they get dropped.
- **Parameters with a default become optional**, everything else is required.
- **Return a string.** Anything else gets `repr()`d.
- **Raise on failure with a helpful message.** The dispatcher catches it and
  feeds the message back to the model, which then retries. Your exception text
  is part of your prompt — write it to a reader who can fix the problem.

### Step 2 — import the module in `agent.py`

```python
import tools.mynewfile
```

Importing is what registers it. No import, no tool. This is the single most
common reason a new tool "does not exist".

### Step 3 — test it without the model

```bash
mcp dev mcp_server.py
```

The Inspector page lets you call the tool directly with your own arguments.
Much faster than guessing why the model will not call it.

---

## 3. Adding a new MCP server

### Step 1 — find the command that starts it

Most servers run with `npx` (Node) or `uvx` (Python). Test it in a terminal
first — a working server prints something like "running on stdio" and then
waits. Ctrl+C to stop.

```bash
npx -y @modelcontextprotocol/server-filesystem /path/to/folder
uvx mcp-server-time --local-timezone America/Chicago
```

If it fails here, it will fail in the agent too, and the agent's error message
is easier to miss.

### Step 2 — add it to `mcp_servers.json`

```json
{
  "files": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/abs/path/workspace"]
  },
  "time": {
    "command": "uvx",
    "args": ["mcp-server-time", "--local-timezone", "America/Chicago"]
  },
  "mine": {
    "command": "/abs/path/.venv/bin/python",
    "args": ["/abs/path/my_server.py"],
    "env": {"AGENT_WORKSPACE": "/abs/path/workspace"}
  }
}
```

Notes:

- **Use absolute paths** for `command` and for script arguments. The server is
  started as a child process and does not inherit your shell's habits.
- **For a Python server, point at the venv's python**, not bare `python`.
- **Environment variables do not carry over.** If a server needs
  `AGENT_WORKSPACE` or an API key, put it in `"env"`.
- **JSON has no comments and needs commas between entries.** One outer `{ }`,
  each server as a key inside it.

Validate before running:

```bash
python -c "import json;print(list(json.load(open('mcp_servers.json'))))"
```

### Step 3 — restart the agent

```
[mcp] files: added 11 tools
[mcp] time: added 2 tools
```

Tool names get prefixed with the label from the config, so the filesystem
server's `read_file` becomes `files_read_file` and cannot collide with yours.

### Step 4 — decide whether it belongs in the prompt

New MCP tools are connected but that does not mean they should be visible to
every agent. See section 6 on prompt size.

---

## 4. Publishing your own tools over MCP

`mcp_server.py` loops over the registry and hands everything to FastMCP:

```python
from mcp.server.fastmcp import FastMCP
from tools.registry import REGISTRY
import tools.basic, tools.files, tools.knowledge   # registration

server = FastMCP("ollama-agent-tools")
for name, entry in REGISTRY.items():
    server.add_tool(entry["fn"], name=name,
                    description=entry["spec"]["function"]["description"])

if __name__ == "__main__":
    server.run()
```

To expose only *some* tools, import only those modules. A knowledge-base-only
server is just `import tools.knowledge` and nothing else.

To use it from Claude Desktop, edit
`~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "my-agent-tools": {
      "command": "/abs/path/.venv/bin/python",
      "args": ["/abs/path/mcp_server.py"]
    }
  }
}
```

Restart the app. Absolute paths both times.

---

## 5. Which one should I use?

### The short rule

> **Local tool** when the code is yours and lives in this project.
> **MCP tool** when you are crossing a boundary — another app, another
> language, someone else's code, or something you want isolated.

### Side by side

| | Local tool | MCP tool |
|---|---|---|
| Speed per call | instant | ~5–20 ms overhead |
| Runs in | your process | a separate process |
| Shares Python variables | yes | no |
| Shares files and databases | yes | yes |
| A crash takes down | the agent | only that server |
| Picking up a code edit | restart the agent | restart the server |
| Environment variables | inherited | must be declared in config |
| Usable by other apps | no | yes |
| Debugging | normal stack traces | error text over a pipe |

### Use a local tool when

- You are writing the function yourself.
- It is called often, or in a loop.
- It needs shared in-memory state with the agent.
- You are still iterating on it and want fast edit-run cycles.

### Use an MCP tool when

- Someone already wrote it and you do not want to reimplement it.
- It is written in another language.
- You want the same tool available in Claude Desktop *and* your agent.
- It is risky — runs untrusted code, hits flaky sites, might hang. A separate
  process contains the damage.
- It needs different credentials or a different sandbox than the agent has.

### Do not use MCP when

- The code is in this repo already. You would gain a process and lose speed.
- The tool is called dozens of times per task.
- You are debugging it. Direct calls give you real stack traces.

### A useful middle path

Both can point at the same code. Keep `import tools.knowledge` in `agent.py`
for speed, *and* run a small MCP server exposing the same module so Claude
Desktop can use it. One implementation, two doors.

---

## 6. Prompt size — the thing that bites

Every tool in `tool_specs()` is sent to the model on **every single call**.
Connect three MCP servers and the tool list can triple.

Two things go wrong at once:

1. You run out of context window and Ollama returns a 500 with
   `truncating input prompt` in its log.
2. The model chooses worse, because it now has six tools that all sound like
   "read a file".

### Check your count

```python
from tools.registry import tool_specs
print(len(tool_specs()))
```

Around 15 is comfortable. Past 25, accuracy drops noticeably.

### Fix 1 — a bigger window

In `llm.py`:

```python
"options": {"temperature": temperature, "num_ctx": 16384}
```

Ollama defaults small to save memory. 16384 is fine on an Apple Silicon Mac
with 16 GB; use 8192 if memory is tight.

### Fix 2 — give each agent only what it needs

```python
researcher = Agent(allowed_tools=[
    "web_search", "fetch_url", "kb_add_url", "kb_search",
])

analyst = Agent(allowed_tools=[
    "db_schema", "db_query", "calculate", "write_pdf",
])
```

Servers stay connected; their tools simply are not offered. This is faster,
cheaper and more accurate than one agent holding everything.

---

## 7. Troubleshooting

**`json.decoder.JSONDecodeError` on startup**
`mcp_servers.json` is malformed — usually a missing comma between two servers,
or a stray brace. Validate it with the one-liner in section 3.

**A server never appears in the `[mcp]` lines**
Its exception was caught and printed. Look at the lines above the prompt. Run
the command by hand in a terminal to see the real error.

**First run times out, later runs work**
`npx` was downloading the package. Raise the timeout in `mcp_client.py`:

```python
def start(self, timeout=120):
```

**A server works in the terminal but not from the agent**
Almost always paths or environment. Use absolute paths, point at the venv's
python, and put any needed variables in `"env"`.

**Ollama returns 500 and its log says `truncating input prompt`**
Too many tokens. See section 6.

**The program hangs on exit**
MCP child processes are still running. Register cleanup:

```python
import atexit

_CONNECTIONS = []

@atexit.register
def _shutdown():
    for conn in _CONNECTIONS:
        conn.stop()
```

**A tool exists but the model never calls it**
The description is the problem, not the code. Rewrite it as an instruction
about *when* to use the tool. Test the wording by asking the model directly:
"which tool would you use to X?"

**A tool errors and the agent gives up**
Read the error text the tool returned. If it does not tell the model how to
recover, rewrite it so it does.

---

## 8. Checklists

### New local tool
- [ ] Function has type hints on every parameter
- [ ] Docstring's first line says *when* to use it
- [ ] `Args:` block lists every parameter
- [ ] Returns a string
- [ ] Errors carry advice, not just a code
- [ ] Module imported in `agent.py`
- [ ] Tested in the MCP Inspector
- [ ] Added to `allowed_tools` if the agent uses a filtered list

### New MCP server
- [ ] Command runs standalone in a terminal
- [ ] Absolute paths in `mcp_servers.json`
- [ ] Needed environment variables in `"env"`
- [ ] JSON validates
- [ ] `[mcp]` line appears on startup
- [ ] Tool count checked against the prompt budget
- [ ] Trusted source — it runs with your permissions
