import os
import sys
import time
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from app.solver import solve_task_optimization, calculate_priority_score
from app.entropy_engine import AdaptiveEntropyDiagnostic, evaluate_task_queue_entropy
from app.dag_engine import TaskDAGEngine
from app.agent_companion import AgenticBehavioralCompanion
from app.firestore_service import FirestoreService
from app.pubsub_service import PubSubService
from app.collaborative_partner import CollaborativePartner

app = FastAPI(
    title="SynapseNode — your task and priority helper",
    description="Helps you sort out what to do and when, taking your energy into account",
    version="1.0.0"
)

# Initialize Services
firestore_db = FirestoreService()
pubsub_bus = PubSubService()
agent_companion = AgenticBehavioralCompanion()

# Plans WITH the user, weighing rest and health against throughput. Distinct from
# the ILP solver, which optimises the queue without consulting anyone.
collaborative_partner = CollaborativePartner(
    firestore_service=firestore_db,
    entropy_score_fn=evaluate_task_queue_entropy,
)

# In-memory session state for instant UI updates
session_answered_questions = []

# Pub/Sub background listener for agent nudges
def pubsub_nudge_handler(event: Dict[str, Any]):
    event_type = event.get("event_type")
    payload = event.get("payload", {})
    if event_type == "task_completed":
        task_title = payload.get("title", "task")
        user_state = firestore_db.get_user_state()
        receptivity = user_state.get("receptivity", 0.8)
        nudge = agent_companion.generate_behavioral_nudge(task_name=task_title, user_receptivity=receptivity, action_type="completion")
        if nudge.get("delivered"):
            firestore_db.log_agent_nudge(nudge)

pubsub_bus.register_subscriber(pubsub_nudge_handler)

# Request Data Models
class RawTaskIngestRequest(BaseModel):
    raw_text: str

class TaskCompleteRequest(BaseModel):
    task_id: str

class UserStateUpdateRequest(BaseModel):
    energy: float
    receptivity: float

class DiagnosticAnswerRequest(BaseModel):
    question_id: str
    value: Any

class PartnerChatRequest(BaseModel):
    message: str
    session_id: str = "default"

# Serve static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir, exist_ok=True)

app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/", response_class=HTMLResponse)
def index_page():
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        with open(index_file, "r") as f:
            return f.read()
    return "<h1>SynapseNode API Running on Cloud Run container engine</h1>"

@app.get("/api/status")
def get_system_status():
    user_state = firestore_db.get_user_state()
    tasks = firestore_db.get_all_tasks()
    queue_entropy = evaluate_task_queue_entropy(tasks)

    return {
        "services": {
            "cloud_run": {
                "name": "Google Cloud Run",
                "type": "Serverless Container Compute",
                "status": "ACTIVE",
                "function": "REST APIs & Sub-150ms ILP Task Solver",
                "scale_model": "0 to 1,000 instances auto-scaling"
            },
            "cloud_firestore": {
                "name": "Google Cloud Firestore",
                "type": "Serverless NoSQL Document DB",
                "status": "ACTIVE (Native / Synced)",
                "function": "Primary state & behavioral pattern persistence",
                "native_gcp": firestore_db.using_gcp_native
            },
            "cloud_pubsub": {
                "name": "Google Cloud Pub/Sub",
                "type": "Asynchronous Event Middleware",
                "status": "ACTIVE (Regional Exactly-Once Delivery)",
                "function": "Asynchronous event bus for agent behavioral nudges",
                "native_gcp": pubsub_bus.using_gcp_native
            }
        },
        "system_metrics": {
            "total_tasks": len(tasks),
            "completed_tasks": len([t for t in tasks if t.get("completed")]),
            "current_user_energy": user_state.get("energy", 8.0),
            "user_receptivity": user_state.get("receptivity", 0.8),
            "queue_entropy": round(queue_entropy, 3),
            "entropy_status": "Low (Optimized)" if queue_entropy <= 0.25 else "High (Diagnostic Required)"
        }
    }

@app.post("/api/ingest")
def ingest_unstructured_tasks(req: RawTaskIngestRequest):
    """
    Ingests unstructured natural language text, synthesizes topological DAG,
    detects/resolves cyclic deadlocks, and saves tasks into Firestore.
    """
    parsed_tasks = TaskDAGEngine.parse_unstructured_input(req.raw_text)
    resolved_tasks, resolutions = TaskDAGEngine.resolve_cycles_and_build_dag(parsed_tasks)

    for t in resolved_tasks:
        firestore_db.save_task(t)

    # Publish Pub/Sub event for task queue update
    msg_id = pubsub_bus.publish_event("tasks_ingested", {"task_count": len(resolved_tasks)})

    return {
        "status": "success",
        "ingested_count": len(resolved_tasks),
        "resolutions": resolutions,
        "tasks": resolved_tasks,
        "pubsub_message_id": msg_id
    }

@app.get("/api/tasks")
def list_tasks():
    tasks = firestore_db.get_all_tasks()
    user_state = firestore_db.get_user_state()
    user_energy = user_state.get("energy", 8.0)
    completed_ids = {t["id"] for t in tasks if t.get("completed")}

    # Calculate live priority scores
    for t in tasks:
        t["priority_score"] = calculate_priority_score(t, user_energy, completed_ids)

    return {"tasks": tasks}

@app.post("/api/solve")
def solve_optimization_schedule():
    """
    Executes 0-1 Integer Linear Program (ILP) solver on current task queue
    given user's current energy capacity envelope.
    """
    tasks = firestore_db.get_all_tasks()
    user_state = firestore_db.get_user_state()
    user_energy = user_state.get("energy", 8.0)
    completed_ids = {t["id"] for t in tasks if t.get("completed")}

    uncompleted_tasks = [t for t in tasks if not t.get("completed")]
    result = solve_task_optimization(uncompleted_tasks, user_energy, completed_ids)

    # Publish Pub/Sub optimization recalibration event
    pubsub_bus.publish_event("optimization_recalibrated", {
        "selected_count": len(result["selected_tasks"]),
        "solve_time_ms": result["solve_time_ms"]
    })

    return result

@app.post("/api/complete-task")
def complete_task(req: TaskCompleteRequest):
    tasks = firestore_db.get_all_tasks()
    task_map = {t["id"]: t for t in tasks}
    
    if req.task_id not in task_map:
        raise HTTPException(status_code=404, detail="Task not found")

    task = task_map[req.task_id]
    firestore_db.update_task_status(req.task_id, True)

    # Publish Pub/Sub event to trigger agent nudge worker asynchronously
    msg_id = pubsub_bus.publish_event("task_completed", {
        "id": req.task_id,
        "title": task.get("title")
    })

    return {
        "status": "success",
        "task_id": req.task_id,
        "completed": True,
        "pubsub_message_id": msg_id
    }

@app.post("/api/user-state")
def update_user_state(req: UserStateUpdateRequest):
    state = {"energy": req.energy, "receptivity": req.receptivity}
    firestore_db.save_user_state(state)
    return {"status": "success", "user_state": state}

@app.get("/api/diagnostic")
def get_diagnostic_question():
    tasks = firestore_db.get_all_tasks()
    uncompleted = [t for t in tasks if not t.get("completed")]
    question, current_entropy = AdaptiveEntropyDiagnostic.get_next_diagnostic_question(uncompleted, session_answered_questions)

    return {
        "entropy": round(current_entropy, 3),
        "requires_diagnostic": question is not None,
        "question": question
    }

@app.post("/api/diagnostic/answer")
def submit_diagnostic_answer(req: DiagnosticAnswerRequest):
    global session_answered_questions
    session_answered_questions.append(req.question_id)

    if req.question_id == "q_user_energy":
        user_state = firestore_db.get_user_state()
        user_state["energy"] = float(req.value)
        firestore_db.save_user_state(user_state)

    return {"status": "success", "answered": req.question_id}

@app.get("/api/nudges")
def get_agent_nudges():
    # Generate proactive prompt if empty
    user_state = firestore_db.get_user_state()
    nudge = agent_companion.generate_behavioral_nudge(
        task_name="Domestic Priority Task",
        user_receptivity=user_state.get("receptivity", 0.8),
        action_type="nudge"
    )
    if nudge.get("delivered"):
        firestore_db.log_agent_nudge(nudge)

    store = firestore_db._read_local_store()
    return {"nudges": store.get("agent_history", [])[-10:]}


@app.post("/api/partner/chat")
def partner_chat(req: PartnerChatRequest):
    """
    One turn with the Collaborative Partner. It reads the live task queue and
    wellbeing signals through its own tools before it answers, and may well
    suggest doing less.
    """
    result = collaborative_partner.converse(req.message, session_id=req.session_id)
    if result.get("available") is False:
        raise HTTPException(status_code=503, detail=result.get("reason"))
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    return result


@app.post("/api/partner/reset")
def partner_reset(session_id: str = "default"):
    """Starts the conversation over."""
    return {"reset": collaborative_partner.reset(session_id), "session_id": session_id}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
