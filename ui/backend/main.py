# SPDX-License-Identifier: Apache-2.0
"""
Backend server for the agent chat UI.

Uses FastAPI — lightweight, async, and faster than Flask/Django for
API-only backends. Serves the frontend static files and handles
chat message submissions.

Run:
    cd ui/backend
    uvicorn main:app --reload --port 8000

Then open http://localhost:8000 in your browser.
"""

import sys
import asyncio
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pathlib import Path
import datetime
import json

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent.cluster_deployment_agent import ClusterDeploymentAgent
from agent.structs.goal import Goal, GoalStatus
from state.agent_state import AgentState
from registry.tool_registry import ToolRegistry
from reasoning.ollama_reasoner import OllamaReasoner
from reasoning.debug_reasoner import DebugReasoner
from client.ollama_client import OllamaClient
from client.debug_client import DebugClient
from tools.deployment.check_bmc_inventory import BmcInventoryTool
from tools.deployment.check_bmc_connectivity import BmcInventoryConnectivityCheckTool

app = FastAPI(title="Deployment")

# Serve frontend static files
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

# ---------------------------------------------------------------------------
# Agent configuration
# ---------------------------------------------------------------------------

OLLAMA_MODEL = "qwen2.5:7b"
OLLAMA_HOST = "http://localhost:11434"

# Singleton debug client so pending decisions persist across requests
_debug_client = DebugClient()


def _build_registry() -> ToolRegistry:
    """Create a ToolRegistry with all deployment tools registered."""
    registry = ToolRegistry()
    registry.register(BmcInventoryTool())
    registry.register(BmcInventoryConnectivityCheckTool())
    return registry


def _build_reasoner(debug_mode: bool = False):
    """Create a reasoner — Ollama or Debug depending on mode."""
    if debug_mode:
        return DebugReasoner(client=_debug_client)
    client = OllamaClient(model=OLLAMA_MODEL, host=OLLAMA_HOST)
    return OllamaReasoner(client=client)


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    """Incoming chat message from the frontend."""
    message: str
    conversation_id: str | None = None
    debug_mode: bool = False


class ChatResponse(BaseModel):
    """Response sent back to the frontend."""
    reply: str
    conversation_id: str
    timestamp: str


class DebugDecisionResponse(BaseModel):
    """A pending decision waiting for human input."""
    id: str
    prompt: str


class DebugSubmitRequest(BaseModel):
    """Human-submitted decision."""
    decision_id: str
    tool: str
    reason: str
    parameters: dict = {}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/api/chat", response_model=ChatResponse)
async def chat(msg: ChatMessage):
    """
    Receive a chat message, create an agent instance,
    run the agent loop, and return the result.
    """
    timestamp = datetime.datetime.now().isoformat()
    conversation_id = msg.conversation_id or f"conv-{int(datetime.datetime.now().timestamp())}"

    print(f"->[{timestamp}] [{conversation_id}] User: {msg.message} (debug={msg.debug_mode})")

    # Build agent components
    registry = _build_registry()
    print(f"->[chat] registry = {registry.tool_definitions()}\n\n\n")
    reasoner = _build_reasoner(debug_mode=msg.debug_mode)

    goal = Goal(
        name="deploy_cluster",
        description=msg.message,
        initial_tool="bmc_inventory_discovery_tool",
        initial_tool_parameters={"path": "C:\\Users\\ssharma3\\Documents\\WorkSpace\\learning\\agentic\\inventory\\rvmc.yaml"
},
        success_criteria="Cluster deployed successfully",
    )

    state = AgentState()

    agent = ClusterDeploymentAgent(
        goal=goal,
        registry=registry,
        state=state,
        correlation_id=conversation_id,
        reasoner=reasoner,
    )

    # Run the agent loop in a thread so the event loop stays free
    # for debug polling requests
    try:
        loop = asyncio.get_event_loop()
        final_status = await loop.run_in_executor(None, agent.run)
        reply = _format_agent_reply(final_status, state)
    except Exception as exc:
        reply = f"Agent error: {exc}"

    return ChatResponse(
        reply=reply,
        conversation_id=conversation_id,
        timestamp=timestamp,
    )


@app.get("/api/debug/pending", response_model=list[DebugDecisionResponse])
async def get_pending_decisions():
    """Return all pending decisions waiting for human input."""
    return [
        DebugDecisionResponse(id=p["id"], prompt=p["prompt"])
        for p in _debug_client.get_pending()
    ]


@app.post("/api/debug/respond")
async def submit_debug_decision(req: DebugSubmitRequest):
    """Submit a human decision for a pending debug request."""
    response_json = json.dumps({
        "tool": req.tool,
        "reason": req.reason,
        "parameters": req.parameters,
    })

    success = _debug_client.submit_response(req.decision_id, response_json)

    if not success:
        return {"status": "error", "message": "Decision not found or already resolved"}

    return {"status": "ok", "message": "Decision submitted"}


def _format_agent_reply(status: GoalStatus, state: AgentState) -> str:
    """Summarize the agent execution into a human-readable reply."""
    lines = [f"Agent finished with status: {status.value}"]

    if state.execution_history:
        last = state.execution_history[-1]
        lines.append(f"Last action: {last.decision.tool}")
        lines.append(f"Reason: {last.decision.reason}")
        if last.result.stdout:
            lines.append(f"Output: {last.result.stdout}")
        if last.result.stderr:
            lines.append(f"Error: {last.result.stderr}")

    return "\n".join(lines)


@app.get("/")
async def serve_index():
    """Serve the main HTML page."""
    return FileResponse(FRONTEND_DIR / "index.html")


# Mount static assets (CSS, JS) after the explicit routes
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
