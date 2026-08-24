from mcp.server.fastmcp import FastMCP

from tools.registry import REGISTRY

# Importing these registers the tools, exactly like in agent.py
import tools.basic
import tools.files
import tools.database
import tools.web
import tools.documents
import tools.knowledge
import tools.graph

server = FastMCP("ollama-agent-tools")

for name, entry in REGISTRY.items():
    server.add_tool(
        entry["fn"],
        name=name,
        description=entry["spec"]["function"]["description"],
    )

if __name__ == "__main__":
    server.run()          # talks over stdin/stdout