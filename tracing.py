"""Records what happened during one run, so you can read it back later."""

import json
import time
import uuid
from pathlib import Path

from config import DATA_DIR

TRACE_DIR = DATA_DIR / "traces"
RUNS_INDEX = DATA_DIR / "runs.jsonl"


class Trace:
    def __init__(self, user_input, model, guard_mode, tools_offered):
        self.id = uuid.uuid4().hex[:8]
        self.started_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._clock = time.perf_counter()
        self.user_input = user_input
        self.model = model
        self.guard_mode = guard_mode
        self.tools_offered = tools_offered
        self.steps = []
        self.answer = ""
        self.status = "running"
        self.error = ""

    # ---- recording ----

    def model_step(self, step, stats):
        self.steps.append({
            "kind": "model",
            "step": step,
            "at": round(time.perf_counter() - self._clock, 3),
            **stats,
        })

    def tool_step(self, step, name, args, outcome, seconds, result):
        self.steps.append({
            "kind": "tool",
            "step": step,
            "at": round(time.perf_counter() - self._clock, 3),
            "tool": name,
            "args": {k: str(v)[:300] for k, v in (args or {}).items()},
            "outcome": outcome,
            "seconds": round(seconds, 3),
            "result_chars": len(result),
            "failed": result.startswith(("ERROR", "BLOCKED")),
            "result_preview": result[:300],
        })

    def finish(self, answer="", status="ok", error=""):
        self.answer = answer
        self.status = status
        self.error = error
        self.total_seconds = round(time.perf_counter() - self._clock, 3)

    # ---- reading back ----

    def totals(self):
        model_steps = [s for s in self.steps if s["kind"] == "model"]
        tool_steps = [s for s in self.steps if s["kind"] == "tool"]
        return {
            "model_calls": len(model_steps),
            "tool_calls": len(tool_steps),
            "tool_failures": sum(1 for s in tool_steps if s["failed"]),
            "model_seconds": round(sum(s["seconds"] for s in model_steps), 2),
            "tool_seconds": round(sum(s["seconds"] for s in tool_steps), 2),
            "prompt_tokens": sum(s["prompt_tokens"] for s in model_steps),
            "reply_tokens": sum(s["reply_tokens"] for s in model_steps),
            "last_prompt_tokens": model_steps[-1]["prompt_tokens"] if model_steps else 0,
        }

    def summary_line(self):
        t = self.totals()
        return (f"[trace {self.id}] {t['model_calls']} model calls · "
                f"{t['tool_calls']} tools ({t['tool_failures']} failed) · "
                f"model {t['model_seconds']}s + tools {t['tool_seconds']}s · "
                f"{t['prompt_tokens']} in / {t['reply_tokens']} out tokens · "
                f"context now {t['last_prompt_tokens']}")

    def as_dict(self):
        return {
            "id": self.id,
            "started_at": self.started_at,
            "model": self.model,
            "guard_mode": self.guard_mode,
            "tools_offered": self.tools_offered,
            "user_input": self.user_input,
            "answer": self.answer,
            "status": self.status,
            "error": self.error,
            "total_seconds": getattr(self, "total_seconds", 0),
            "totals": self.totals(),
            "steps": self.steps,
        }

    def save(self):
        TRACE_DIR.mkdir(parents=True, exist_ok=True)
        data = self.as_dict()

        path = TRACE_DIR / f"{self.started_at.replace(':', '')}-{self.id}.json"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        index_row = {k: data[k] for k in
                     ("id", "started_at", "status", "total_seconds", "user_input")}
        index_row.update(data["totals"])
        with RUNS_INDEX.open("a", encoding="utf-8") as f:
            f.write(json.dumps(index_row) + "\n")
        return path