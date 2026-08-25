import os
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("SynapseNode.Partner")

DEFAULT_MODEL = os.getenv("PARTNER_MODEL", os.getenv("GEMINI_MODEL", "gemini-3.5-flash"))
DEFAULT_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "global")
DEFAULT_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "gen-lang-client-0411709036")

# The Partner reasons about trade-offs, so unlike the one-line nudges in
# AgenticBehavioralCompanion its thinking budget is left on. That costs more per
# turn; the cap below is what bounds it.
MAX_OUTPUT_TOKENS = int(os.getenv("PARTNER_MAX_OUTPUT_TOKENS", "1024"))

SYSTEM_INSTRUCTION = """\
You are the Collaborative Partner in SynapseNode, a domestic task manager.

SynapseNode already contains a Task Master: an integer-programming solver that
picks an optimal task set on its own and hands down an answer. You are not that,
and you must never behave like it. The solver optimises throughput. You look
after the person doing the work.

How you work with someone:
- Decide WITH them, never FOR them. Offer two or three real options and ask
  which fits. A question is usually a better turn than an instruction.
- Treat rest, food, sleep, movement, and time with other people as first-class
  priorities that legitimately outrank chores. Protecting an evening is a valid
  outcome of a planning conversation.
- When the signals say someone is depleted, say so plainly and propose doing
  less. Recommending nothing at all is sometimes the correct answer, and you
  should be willing to give it.
- Be honest about trade-offs. If deferring something has a real cost, name it
  once, without pressure, and let them choose.
- Never use guilt, streak-shaming, urgency, or productivity moralising. No
  implication that their worth depends on output.

Before proposing anything concrete, call your tools to see the real task queue
and the person's current signals. Do not invent tasks or numbers.

Keep replies conversational and under 150 words unless asked for detail. Plain
sentences, no headers or bullet lists unless you are laying out options."""


class CollaborativePartner:
    """
    Conversational agent that plans WITH the user, weighing whole-being against
    throughput. Distinct from the Task Master solver, which optimises a queue
    without consulting anyone.

    Gemini runs through Vertex AI with automatic function calling, so the model
    reads real task and wellbeing state rather than guessing at it.
    """

    def __init__(self, firestore_service=None, entropy_score_fn=None,
                 model: str = None, project: str = None, location: str = None):
        self.db = firestore_service
        self.entropy_score_fn = entropy_score_fn
        self.model = model or DEFAULT_MODEL
        self.project = project or DEFAULT_PROJECT
        self.location = location or DEFAULT_LOCATION
        self.client = None
        self.using_gemini = False
        self._sessions: Dict[str, Any] = {}
        self._init_model_client()

    def _init_model_client(self):
        try:
            import google.auth
            google.auth.default()
        except Exception:
            logger.info("GCP credentials not found; Collaborative Partner is unavailable.")
            return
        try:
            from google import genai
            self.client = genai.Client(vertexai=True, project=self.project, location=self.location)
            self.using_gemini = True
            logger.info(f"Collaborative Partner ready (model={self.model}, location={self.location}).")
        except Exception as e:
            logger.warning(f"Partner init failed: {e}")

    # ---- tools exposed to the model -------------------------------------

    def _tool_list_open_tasks(self) -> List[Dict[str, Any]]:
        """Lists the tasks the user has not yet completed.

        Returns:
            A list of open tasks, each with its title, effort estimate in hours,
            and priority score.
        """
        if not self.db:
            return []
        out = []
        for t in self.db.get_all_tasks():
            if t.get("completed"):
                continue
            out.append({
                "title": t.get("title", "untitled"),
                "effort_hours": t.get("effort", t.get("effort_hours", 1)),
                "priority": t.get("priority_score", t.get("priority", 0)),
            })
        return out[:25]

    def _tool_get_wellbeing_signals(self) -> Dict[str, Any]:
        """Reads how depleted or receptive the user currently is.

        Returns:
            Current receptivity (0-1, lower means closer to overload), the energy
            capacity in hours they have left today, how many tasks are waiting,
            and the queue's entropy score if available.
        """
        state = self.db.get_user_state() if self.db else {}
        open_tasks = self._tool_list_open_tasks()
        signals = {
            "receptivity": state.get("receptivity", 0.8),
            "energy_capacity_hours": state.get("energy", state.get("energy_capacity", 6.0)),
            "open_task_count": len(open_tasks),
            "total_open_effort_hours": round(sum(t["effort_hours"] for t in open_tasks), 1),
        }
        if self.entropy_score_fn:
            try:
                signals["queue_entropy"] = self.entropy_score_fn(open_tasks)
            except Exception:
                pass
        return signals

    # ---- conversation ----------------------------------------------------

    def _new_chat(self):
        return self.client.chats.create(
            model=self.model,
            config={
                "system_instruction": SYSTEM_INSTRUCTION,
                "max_output_tokens": MAX_OUTPUT_TOKENS,
                "temperature": 0.7,
                "tools": [self._tool_list_open_tasks, self._tool_get_wellbeing_signals],
            },
        )

    def converse(self, message: str, session_id: str = "default") -> Dict[str, Any]:
        """
        Sends one turn to the Partner. Conversation state is held per session_id,
        so follow-up turns keep their context.
        """
        if not self.using_gemini:
            return {
                "available": False,
                "reason": ("The Collaborative Partner needs Vertex AI credentials. "
                           "Run `gcloud auth application-default login`, or set "
                           "GOOGLE_CLOUD_PROJECT on Cloud Run."),
                "reply": None,
            }

        chat = self._sessions.get(session_id)
        if chat is None:
            chat = self._new_chat()
            self._sessions[session_id] = chat

        try:
            response = chat.send_message(message)
        except Exception as e:
            logger.warning(f"Partner turn failed: {e}")
            return {"available": True, "reply": None, "error": str(e)[:300]}

        return {
            "available": True,
            "session_id": session_id,
            "reply": (response.text or "").strip(),
            "model": self.model,
        }

    def reset(self, session_id: str = "default") -> bool:
        """Drops a conversation so the next turn starts fresh."""
        return self._sessions.pop(session_id, None) is not None
