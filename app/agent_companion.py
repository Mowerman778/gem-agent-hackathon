import os
import time
import random
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("SynapseNode.AgentCompanion")

# Gemini is reached through Vertex AI deliberately: hackathon promotional credits
# apply to Vertex model usage, while standalone AI Studio API keys bill separately.
DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
DEFAULT_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
DEFAULT_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "synapse-node-hackathon")

# Nudges are one sentence; capping output is the main per-call cost lever.
MAX_OUTPUT_TOKENS = int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "120"))

SYSTEM_INSTRUCTION = (
    "You are the behavioural companion inside SynapseNode, a domestic task manager. "
    "Write a single short nudge to the user: at most 25 words, warm and specific, "
    "never nagging or guilt-inducing. Open with one relevant emoji. "
    "Return only the nudge text, with no quotes and no preamble."
)

ACTION_BRIEFS = {
    "completion": "They just finished the task. Acknowledge it and point at the momentum it frees up.",
    "nudge": "They have not started the task. Lower the activation energy - suggest a small first step.",
    "recalibration": "Their schedule was just re-planned around their energy. Reassure them; no action needed.",
}

FALLBACK_MESSAGES = {
    "completion": [
        "🌟 Outstanding effort completing '{task}'! Taking a quick 2-minute breath will lock in that focus momentum.",
        "💪 Great step forward! Completing '{task}' frees up your mental stack for the next milestone.",
        "✨ Excellent habit streak! Your consistent progress on domestic tasks is building real momentum.",
    ],
    "nudge": [
        "🌿 Gentle reminder: Your energy aligns well right now. Starting small on '{task}' will feel seamless.",
        "☕ Remember to stay hydrated! When you're ready, '{task}' is primed as your next low-friction task.",
        "🎯 Mindful pace: You've got this! Focus on just the first 5 minutes of '{task}'.",
    ],
    "recalibration": [
        "🔄 Dynamic schedule recalibrated seamlessly to match your updated energy flow. Zero stress!",
        "🛡️ Shifted tasks to protect your focus window. Take your time!",
    ],
}


class AgenticBehavioralCompanion:
    """
    Autonomous Agentic Companion that tracks user habits, energy fluctuations,
    and governs communication density using cognitive load boundary function:
    B(t) = theta( R_user(t) - K_th * (1 + rho_density) )

    Nudge copy is written by Gemini through Vertex AI. The boundary function gates
    the call, so throttled nudges cost nothing. Falls back to local templates when
    Vertex is unavailable, so offline runs and tests stay deterministic.
    """
    def __init__(
        self,
        k_threshold: float = 0.5,
        model: str = None,
        project: str = None,
        location: str = None,
    ):
        self.k_threshold = k_threshold
        self.recent_nudge_timestamps: List[float] = []
        self.nudge_window_seconds = 300.0 # 5 minute sliding window for density evaluation

        self.model = model or DEFAULT_MODEL
        self.project = project or DEFAULT_PROJECT
        self.location = location or DEFAULT_LOCATION
        self.client = None
        self.using_gemini = False
        self._init_model_client()

    def _init_model_client(self):
        # Mirrors FirestoreService: only reach for the cloud when credentials exist,
        # otherwise local runs would stall on ADC lookups that cannot succeed.
        if not (os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or os.getenv("GOOGLE_CLOUD_PROJECT")):
            logger.info("GCP credentials not found; behavioural nudges will use local templates.")
            return
        try:
            from google import genai
            self.client = genai.Client(vertexai=True, project=self.project, location=self.location)
            self.using_gemini = True
            logger.info(f"Vertex AI Gemini client ready (model={self.model}, location={self.location}).")
        except Exception as e:
            logger.warning(f"Vertex AI init notice: {e}. Defaulting to local nudge templates.")

    def calculate_feedback_density(self) -> float:
        """Calculates rho_density (nudges per minute in window)"""
        now = time.time()
        self.recent_nudge_timestamps = [
            ts for ts in self.recent_nudge_timestamps if (now - ts) <= self.nudge_window_seconds
        ]
        return len(self.recent_nudge_timestamps) / (self.nudge_window_seconds / 60.0)

    def should_deliver_nudge(self, user_receptivity: float) -> bool:
        """
        Evaluates cognitive load boundary function B(t).
        Returns True if receptive capacity R_user exceeds threshold adjusted by feedback density.
        """
        rho_density = self.calculate_feedback_density()
        effective_threshold = self.k_threshold * (1.0 + rho_density)

        # Step function theta(diff) > 0
        return user_receptivity > effective_threshold

    def _build_prompt(self, task_name: str, action_type: str, user_receptivity: float) -> str:
        brief = ACTION_BRIEFS.get(action_type, ACTION_BRIEFS["nudge"])
        task = task_name or "their next task"
        return (
            f"Task: {task}\n"
            f"Situation: {brief}\n"
            f"User receptivity right now: {user_receptivity:.2f} on a 0-1 scale "
            f"(lower means they are closer to overload - be briefer and gentler)."
        )

    def _generate_with_gemini(self, task_name: str, action_type: str, user_receptivity: float) -> Optional[str]:
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=self._build_prompt(task_name, action_type, user_receptivity),
                config={
                    "system_instruction": SYSTEM_INSTRUCTION,
                    "max_output_tokens": MAX_OUTPUT_TOKENS,
                    "temperature": 0.9,
                },
            )
            message = (response.text or "").strip()
            return message or None
        except Exception as e:
            logger.warning(f"Gemini nudge generation failed: {e}. Falling back to template.")
            return None

    def _fallback_message(self, task_name: str, action_type: str) -> str:
        messages = FALLBACK_MESSAGES.get(action_type, FALLBACK_MESSAGES["nudge"])
        return random.choice(messages).format(task=task_name or "your next task")

    def generate_behavioral_nudge(
        self,
        task_name: str = None,
        user_receptivity: float = 0.8,
        action_type: str = "completion"
    ) -> Dict[str, Any]:
        """
        Generates an uplifting, empathetic micro-reinforcement or non-intrusive caring prompt.
        """
        if not self.should_deliver_nudge(user_receptivity):
            return {
                "delivered": False,
                "reason": "Throttled by cognitive load boundary B(t) to prevent notification fatigue.",
                "message": None
            }

        message = None
        source = "template"
        if self.using_gemini:
            message = self._generate_with_gemini(task_name, action_type, user_receptivity)
            if message:
                source = "gemini"

        if not message:
            message = self._fallback_message(task_name, action_type)

        # Record timestamp to update rho_density
        self.recent_nudge_timestamps.append(time.time())

        return {
            "delivered": True,
            "action_type": action_type,
            "message": message,
            "source": source,
            "model": self.model if source == "gemini" else None,
            "timestamp": time.strftime("%H:%M:%S"),
            "feedback_density": round(self.calculate_feedback_density(), 2)
        }
