import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent import Agent, DEFAULT_TOOLS, load_mcp_servers  # noqa: E402
from guardrails import Guard  # noqa: E402

CASES = [
    ("what is 800+750", "1550"),
    ("how many customers are in the database?", "4"),
    ("what files are in the workspace?", "notes.md"),
]

load_mcp_servers()
passed = 0
for question, expected in CASES:
    agent = Agent(allowed_tools=DEFAULT_TOOLS, verbose=False,
                  guard=Guard(mode="auto", approver=lambda *a: False))
    answer = agent.run(question)
    ok = expected.lower() in answer.lower()
    passed += ok
    print(f"{'PASS' if ok else 'FAIL'}  {question}\n      {answer[:120]}")
    print(f"      {agent.last_trace.summary_line()}\n")

print(f"{passed}/{len(CASES)} passed")