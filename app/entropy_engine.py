import math
from typing import List, Dict, Any, Tuple

def calculate_shannon_entropy(probabilities: List[float]) -> float:
    """Calculates Shannon entropy H(X) = -sum(p_i * log2(p_i))"""
    entropy = 0.0
    for p in probabilities:
        if p > 0:
            entropy -= p * math.log2(p)
    return entropy

def evaluate_task_queue_entropy(tasks: List[Dict[str, Any]]) -> float:
    """
    Computes overall uncertainty/entropy in the task queue based on unknown or unassigned metadata
    (energy requirements, effort coefficients, deadlines, user affinity).
    """
    if not tasks:
        return 0.0

    missing_fields_count = 0
    total_fields_count = len(tasks) * 4 # 4 key diagnostic dimensions: energy, effort, urgency, affinity

    for task in tasks:
        if "required_energy" not in task or task["required_energy"] is None:
            missing_fields_count += 1
        if "effort" not in task or task["effort"] is None:
            missing_fields_count += 1
        if "urgency_weight" not in task or task["urgency_weight"] is None:
            missing_fields_count += 1
        if "user_affinity" not in task or task["user_affinity"] is None:
            missing_fields_count += 1

    p_missing = missing_fields_count / max(1, total_fields_count)
    p_present = 1.0 - p_missing

    if p_missing == 0 or p_present == 0:
        return 0.0
        
    return calculate_shannon_entropy([p_missing, p_present])

class AdaptiveEntropyDiagnostic:
    """
    Entropy-driven Questioning Engine that generates minimal diagnostic prompts
    to reduce system uncertainty below entropy threshold tau_e (e.g., 0.25).
    """
    ENTROPY_THRESHOLD = 0.25

    @staticmethod
    def get_next_diagnostic_question(tasks: List[Dict[str, Any]], answered_questions: List[str]) -> Tuple[Dict[str, Any], float]:
        """
        Determines the single most informative question to ask next by evaluating
        expected variance reduction (information gain) across candidate diagnostic questions.
        """
        current_entropy = evaluate_task_queue_entropy(tasks)
        if current_entropy <= AdaptiveEntropyDiagnostic.ENTROPY_THRESHOLD:
            return None, current_entropy

        # Candidate Questions mapped to entropy dimensions
        candidates = [
            {
                "id": "q_user_energy",
                "question": "What is your current physical & cognitive energy level right now?",
                "options": [
                    {"label": "⚡ High Energy (Focus & Physical Effort)", "value": 9},
                    {"label": "⚖️ Moderate Energy (Standard Routine)", "value": 5},
                    {"label": "🔋 Low Energy (Light / Low-Effort Tasks)", "value": 2}
                ],
                "dimension": "user_energy",
                "info_gain": 0.45
            },
            {
                "id": "q_task_affinity",
                "question": "Which type of task do you feel most receptive to starting first?",
                "options": [
                    {"label": "🧹 Physical Organization & Cleaning", "value": "physical"},
                    {"label": "💻 Quiet Administrative / Digital Tasks", "value": "admin"},
                    {"label": "🛠️ Repair & Maintenance", "value": "maintenance"}
                ],
                "dimension": "affinity",
                "info_gain": 0.38
            },
            {
                "id": "q_time_available",
                "question": "How much uninterrupted time do you have in your current session?",
                "options": [
                    {"label": "⏱️ Quick burst (Under 30 minutes)", "value": 0.5},
                    {"label": "🕒 Standard block (1 - 2 hours)", "value": 1.5},
                    {"label": "⏳ Open ended (Full afternoon)", "value": 4.0}
                ],
                "dimension": "time_block",
                "info_gain": 0.32
            }
        ]

        # Filter out already answered questions
        unanswered = [q for q in candidates if q["id"] not in answered_questions]
        if not unanswered:
            return None, current_entropy

        # Select question with highest information gain
        best_question = max(unanswered, key=lambda q: q["info_gain"])
        return best_question, current_entropy
