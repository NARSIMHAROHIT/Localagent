"""HTTP API for the agent.

    uvicorn api:app --reload

Then open http://127.0.0.1:8000/docs
"""

import json
import queue
import threading
import time
import uuid

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import config
from agent import DEFAULT_TOOLS, Agent, load_mcp_servers
from guardrails import Guard, make_policy_approver, risk_of
from llm import LLMError
from tools.registry import tool_specs

app = FastAPI(
    title="Localagent",
    description="A local AI agent with tools, graph RAG, MCP and guardrails.",
    version="1.0.0",
)

# Lets web/index.html (opened from a file:// URL) call this API.
# Tighten allow_origins before putting this anywhere public.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------- sessions --

class Session:
    def __init__(self, agent):
        self.agent = agent
        self.created = time.time()
        self.last_used = time.time()
        self.lock = threading.Lock()      # one request at a time per session


SESSIONS: dict[str, Session] = {}
SESSIONS_LOCK = threading.Lock()


def _prune():
    """Drop conversations nobody has touched for a while, so memory does not grow."""
    cutoff = time.time() - config.SESSION_TTL_MINUTES * 60
    with SESSIONS_LOCK:
        for sid in [s for s, v in SESSIONS.items() if v.last_used < cutoff]:
            del SESSIONS[sid]


def get_session(session_id, allow_levels):
    _prune()
    with SESSIONS_LOCK:
        if session_id and session_id in SESSIONS:
            session = SESSIONS[session_id]
            session.last_used = time.time()
            return session_id, session

        new_id = session_id or uuid.uuid4().hex[:12]
        agent = Agent(
            allowed_tools=DEFAULT_TOOLS,
            verbose=False,
            # Nobody is at a terminal, so approvals come from what the caller
            # pre-authorised in the request instead of from input().
            guard=Guard(mode="ask", approver=make_policy_approver(allow_levels)),
        )
        SESSIONS[new_id] = Session(agent)
        return new_id, SESSIONS[new_id]


# -------------------------------------------------------------------- auth --

def require_key(x_api_key: str = Header(default="")):
    if not config.API_KEY:
        return                              # dev mode: no key configured
    if x_api_key != config.API_KEY:
        raise HTTPException(status_code=401, detail="bad or missing X-API-Key header")


# ------------------------------------------------------------------ shapes --

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    session_id: str | None = Field(
        default=None, description="Continue an existing conversation."
    )
    allow: list[str] = Field(
        default_factory=list,
        description="Risk levels this caller pre-approves: 'write', 'danger'. "
                    "Anything not listed is refused automatically.",
    )


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    trace_id: str
    seconds: float
    model_calls: int
    tool_calls: int
    tool_failures: int
    prompt_tokens: int
    reply_tokens: int


# --------------------------------------------------------------- endpoints --

@app.on_event("startup")
def startup():
    load_mcp_servers()
    print(f"[api] {len(tool_specs())} tools registered, "
          f"{len(tool_specs(DEFAULT_TOOLS))} offered to the model")
    print(f"[api] workspace: {config.WORKSPACE_DIR}")
    if not config.API_KEY:
        print("[api] WARNING: AGENT_API_KEY is not set — this API is unauthenticated")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": config.CHAT_MODEL,
        "tools": len(tool_specs()),
        "sessions": len(SESSIONS),
    }


@app.get("/tools", dependencies=[Depends(require_key)])
def list_tools():
    return [
        {
            "name": spec["function"]["name"],
            "risk": risk_of(spec["function"]["name"]),
            "description": spec["function"]["description"],
            "offered_by_default": spec["function"]["name"] in DEFAULT_TOOLS,
        }
        for spec in tool_specs()
    ]


# NOTE: plain `def`, not `async def`. agent.run() blocks for tens of seconds.
# FastAPI runs sync endpoints in a thread pool, so one slow request does not
# freeze the whole server. An `async def` here would stall the event loop.
@app.post("/chat", response_model=ChatResponse, dependencies=[Depends(require_key)])
def chat_endpoint(req: ChatRequest):
    session_id, session = get_session(req.session_id, req.allow)

    if not session.lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="this session is already busy")
    try:
        answer = session.agent.run(req.message)
    except LLMError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")
    finally:
        session.lock.release()

    trace = session.agent.last_trace
    totals = trace.totals()
    return ChatResponse(
        session_id=session_id,
        answer=answer,
        trace_id=trace.id,
        seconds=trace.total_seconds,
        **{k: totals[k] for k in ("model_calls", "tool_calls", "tool_failures",
                                  "prompt_tokens", "reply_tokens")},
    )


@app.post("/chat/stream", dependencies=[Depends(require_key)])
def chat_stream(req: ChatRequest):
    """Same as /chat, but sends progress events as they happen (SSE)."""
    session_id, session = get_session(req.session_id, req.allow)

    if not session.lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="this session is already busy")

    events: queue.Queue = queue.Queue()

    def worker():
        try:
            answer = session.agent.run(req.message, on_event=events.put)
            events.put({"type": "answer", "answer": answer,
                        "trace_id": session.agent.last_trace.id})
        except Exception as e:
            events.put({"type": "error", "error": f"{type(e).__name__}: {e}"})
        finally:
            events.put(None)
            session.lock.release()

    threading.Thread(target=worker, daemon=True).start()

    def stream():
        yield f"data: {json.dumps({'type': 'session', 'session_id': session_id})}\n\n"
        while True:
            item = events.get()
            if item is None:
                break
            yield f"data: {json.dumps(item, default=str)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/sessions", dependencies=[Depends(require_key)])
def list_sessions():
    return [
        {"session_id": sid, "created": s.created, "last_used": s.last_used,
         "messages": len(s.agent.messages)}
        for sid, s in SESSIONS.items()
    ]


@app.get("/sessions/{session_id}", dependencies=[Depends(require_key)])
def get_history(session_id: str):
    session = SESSIONS.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="no such session")
    return {
        "session_id": session_id,
        "created": session.created,
        "messages": [
            {"role": m.get("role"),
             "content": (m.get("content") or "")[:2000],
             "tool": m.get("tool_name")}
            for m in session.agent.messages
        ],
    }


@app.delete("/sessions/{session_id}", dependencies=[Depends(require_key)])
def delete_session(session_id: str):
    with SESSIONS_LOCK:
        if SESSIONS.pop(session_id, None) is None:
            raise HTTPException(status_code=404, detail="no such session")
    return {"deleted": session_id}


@app.get("/traces", dependencies=[Depends(require_key)])
def list_traces(limit: int = 20):
    path = config.DATA_DIR / "runs.jsonl"
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return rows[-limit:]


@app.get("/traces/{trace_id}", dependencies=[Depends(require_key)])
def get_trace(trace_id: str):
    matches = sorted((config.DATA_DIR / "traces").glob(f"*-{trace_id}*.json"))
    if not matches:
        raise HTTPException(status_code=404, detail="no such trace")
    return json.loads(matches[-1].read_text(encoding="utf-8"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host=config.API_HOST, port=config.API_PORT, reload=True)
