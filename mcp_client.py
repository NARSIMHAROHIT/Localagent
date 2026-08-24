import asyncio
import threading
from contextlib import AsyncExitStack
import atexit
_CONNECTIONS = []
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from tools.registry import REGISTRY


class MCPConnection:
    """Keeps one MCP server running in the background and lets normal
    (non-async) code call its tools."""

    def __init__(self, label, command, args, env=None):
        self.label = label
        self.params = StdioServerParameters(command=command, args=args, env=env)
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.session = None
        self.stack = None
        self.tools = []

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    async def _connect(self):
        self.stack = AsyncExitStack()
        read, write = await self.stack.enter_async_context(stdio_client(self.params))
        self.session = await self.stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()
        self.tools = (await self.session.list_tools()).tools

    def start(self, timeout=60):
        self.thread.start()
        asyncio.run_coroutine_threadsafe(self._connect(), self.loop).result(timeout)
        return self.tools

    def call(self, remote_name, arguments, timeout=180):
        if self.session is None:
            return f"ERROR: not connected to '{self.label}'."
        try:
            result = asyncio.run_coroutine_threadsafe(
                self.session.call_tool(remote_name, arguments or {}), self.loop
            ).result(timeout)
        except Exception as e:
            return f"ERROR calling {self.label}.{remote_name}: {e}"

        parts = [getattr(c, "text", "") for c in result.content]
        text = "\n".join(p for p in parts if p) or "(no output)"
        if getattr(result, "isError", False):
            return f"ERROR from {self.label}: {text}"
        return text
    def stop(self):
        if self.stack is not None:
            try:
                asyncio.run_coroutine_threadsafe(self.stack.aclose(), self.loop).result(10)
            except Exception:
                pass
        self.loop.call_soon_threadsafe(self.loop.stop)

def _make_caller(conn, remote_name):
    def caller(**kwargs):
        return conn.call(remote_name, kwargs)
    return caller


def register_mcp_server(label, command, args, env=None):
    """Connect to an MCP server and add all of its tools to our registry."""
    conn = MCPConnection(label, command, args, env)
    tools = conn.start()
    _CONNECTIONS.append(conn)
    added = []
    for t in tools:
        local_name = f"{label}_{t.name}"
        REGISTRY[local_name] = {
            "fn": _make_caller(conn, t.name),
            "spec": {
                "type": "function",
                "function": {
                    "name": local_name,
                    "description": t.description or f"{t.name} from {label}",
                    "parameters": t.inputSchema or {"type": "object", "properties": {}},
                },
            },
        }
        added.append(local_name)
    return added
@atexit.register
def _shutdown():
    for conn in _CONNECTIONS:
        conn.stop()