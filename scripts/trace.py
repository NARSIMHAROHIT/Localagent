"""Read back what the agent did.

    python scripts/trace.py            list recent runs
    python scripts/trace.py 3f2a1b9c   show one run in detail
    python scripts/trace.py stats      totals across all runs
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import DATA_DIR  # noqa: E402

TRACE_DIR = DATA_DIR / "traces"
RUNS_INDEX = DATA_DIR / "runs.jsonl"


def load_index():
    if not RUNS_INDEX.exists():
        return []
    rows = []
    for line in RUNS_INDEX.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return rows


def list_runs(limit=20):
    rows = load_index()[-limit:]
    if not rows:
        print("No runs recorded yet.")
        return
    print(f"{'id':10} {'when':20} {'status':10} {'secs':>7} {'calls':>6} {'fail':>5}  question")
    print("-" * 100)
    for r in rows:
        print(f"{r['id']:10} {r['started_at']:20} {r['status']:10} "
              f"{r['total_seconds']:>7} {r['tool_calls']:>6} {r['tool_failures']:>5}  "
              f"{r['user_input'][:40]}")


def show_run(run_id):
    matches = sorted(TRACE_DIR.glob(f"*-{run_id}*.json"))
    if not matches:
        print(f"No trace found for '{run_id}'.")
        return
    data = json.loads(matches[-1].read_text(encoding="utf-8"))

    print(f"run {data['id']}   {data['started_at']}   {data['status']}")
    print(f"model {data['model']}   guard {data['guard_mode']}   "
          f"{data['tools_offered']} tools offered")
    print(f"\nQ: {data['user_input']}\n")

    for s in data["steps"]:
        if s["kind"] == "model":
            print(f"  {s['at']:>7.2f}s  MODEL step {s['step']}  "
                  f"{s['seconds']}s  in={s['prompt_tokens']} out={s['reply_tokens']}"
                  + (f"  [cut off: {s['done_reason']}]" if s.get("done_reason") == "length" else ""))
        else:
            mark = "x" if s["failed"] else "."
            print(f"  {s['at']:>7.2f}s  TOOL  {mark} {s['tool']}({json.dumps(s['args'])[:70]}) "
                  f"{s['seconds']}s -> {s['result_chars']} chars")
            if s["failed"]:
                print(f"            {s['result_preview'][:150]}")

    t = data["totals"]
    print(f"\nA: {data['answer'][:600]}")
    print(f"\ntotal {data['total_seconds']}s  "
          f"(model {t['model_seconds']}s, tools {t['tool_seconds']}s)")
    print(f"tokens {t['prompt_tokens']} in / {t['reply_tokens']} out   "
          f"final context {t['last_prompt_tokens']}")
    if data["error"]:
        print(f"error: {data['error']}")


def stats():
    rows = load_index()
    if not rows:
        print("No runs recorded yet.")
        return
    n = len(rows)
    ok = sum(1 for r in rows if r["status"] == "ok")
    print(f"runs                 {n}")
    print(f"finished cleanly     {ok} ({100 * ok // n}%)")
    print(f"avg seconds per run  {sum(r['total_seconds'] for r in rows) / n:.1f}")
    print(f"avg model calls      {sum(r['model_calls'] for r in rows) / n:.1f}")
    print(f"avg tool calls       {sum(r['tool_calls'] for r in rows) / n:.1f}")
    total_tools = sum(r["tool_calls"] for r in rows)
    total_fails = sum(r["tool_failures"] for r in rows)
    if total_tools:
        print(f"tool failure rate    {100 * total_fails / total_tools:.1f}%")
    print(f"largest context      {max(r['last_prompt_tokens'] for r in rows)} tokens")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if not arg:
        list_runs()
    elif arg == "stats":
        stats()
    else:
        show_run(arg)