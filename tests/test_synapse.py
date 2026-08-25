import pytest
from app.solver import solve_task_optimization, calculate_priority_score
from app.entropy_engine import AdaptiveEntropyDiagnostic, evaluate_task_queue_entropy
from app.dag_engine import TaskDAGEngine
from app.agent_companion import AgenticBehavioralCompanion

def test_priority_score_math():
    task = {
        "id": "t1",
        "title": "Clean garage",
        "effort": 5.0,
        "required_energy": 5.0,
        "urgency_weight": 1.0,
        "decay_rate": 0.05,
        "deadline_hours": 24.0,
        "user_affinity": 1.0,
        "habit_factor": 0.8,
        "prerequisites": []
    }
    score = calculate_priority_score(task, user_energy=8.0, completed_task_ids=set())
    assert score > 0
    print(f"Calculated priority score: {score}")

def test_prerequisite_blocking():
    task_blocked = {
        "id": "t2",
        "title": "Move lawnmower",
        "effort": 5.0,
        "prerequisites": ["t1"]
    }
    score = calculate_priority_score(task_blocked, user_energy=8.0, completed_task_ids=set())
    assert score == 0.0, "Blocked task with uncompleted prerequisite must have priority score 0"

def test_ilp_solver():
    tasks = [
        {"id": "t1", "title": "Task 1", "effort": 3.0, "required_energy": 3.0, "urgency_weight": 1.0, "prerequisites": []},
        {"id": "t2", "title": "Task 2", "effort": 6.0, "required_energy": 6.0, "urgency_weight": 1.5, "prerequisites": []},
        {"id": "t3", "title": "Task 3", "effort": 4.0, "required_energy": 4.0, "urgency_weight": 0.8, "prerequisites": []}
    ]
    res = solve_task_optimization(tasks, user_energy_capacity=7.0, completed_task_ids=set())
    assert res["status"] == "Optimal"
    assert res["total_effort_used"] <= 7.0
    print(f"ILP Solve result: selected {len(res['selected_tasks'])} tasks in {res['solve_time_ms']}ms")

def test_dag_cycle_resolution():
    raw_text = "Clean garage after moving lawnmower\nMove lawnmower then clear doorway"
    parsed = TaskDAGEngine.parse_unstructured_input(raw_text)
    assert len(parsed) >= 2

def test_agent_nudge():
    companion = AgenticBehavioralCompanion(k_threshold=0.1)
    nudge = companion.generate_behavioral_nudge("Clean garage", user_receptivity=0.9, action_type="completion")
    assert nudge["delivered"] is True
    assert nudge["message"] is not None
