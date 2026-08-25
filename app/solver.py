import math
import time
from typing import List, Dict, Any
from pulp import LpProblem, LpMaximize, LpVariable, lpSum, PULP_CBC_CMD

def calculate_urgency(u0: float, lambda_param: float, delta_t_hours: float) -> float:
    """
    Time-decaying urgency function: U_i(t) = U_{0,i} * exp(lambda * delta_t)
    """
    # Clamp exponent to prevent numerical overflow
    exponent = max(-10.0, min(10.0, lambda_param * delta_t_hours))
    return u0 * math.exp(exponent)

def sigmoid(x: float) -> float:
    """Sigmoidal context-matching activation function"""
    try:
        return 1.0 / (1.0 + math.exp(-max(-15.0, min(15.0, x))))
    except OverflowError:
        return 0.0 if x < 0 else 1.0

def calculate_priority_score(
    task: Dict[str, Any],
    user_energy: float,
    completed_task_ids: set,
    current_time_hours: float = 0.0
) -> float:
    """
    Calculates dynamic priority score P_i(t) based on the exact mathematical formula in the blueprint:
    P_i(t) = [ U_i(t) * A_i * H_i(t) * sigma(S_user(t) - S_req,i) / (E_i + epsilon) ] * Product_{j in D_i} C_j(t)
    """
    epsilon = 0.001
    
    # 1. Topological Prerequisite Check
    prerequisites = task.get("prerequisites", [])
    for prereq_id in prerequisites:
        if prereq_id not in completed_task_ids:
            # Prerequisite C_j(t) is 0, making whole priority 0
            return 0.0

    # 2. Urgency
    u0 = float(task.get("urgency_weight", 1.0))
    lambda_param = float(task.get("decay_rate", 0.05))
    deadline_hours = float(task.get("deadline_hours", 24.0))
    delta_t = max(0.0, deadline_hours - current_time_hours)
    urgency = calculate_urgency(u0, lambda_param, delta_t)

    # 3. User Affinity & Habit Factor
    affinity = float(task.get("user_affinity", 1.0))
    habit_factor = float(task.get("habit_factor", 0.8))

    # 4. Energy Match Sigmoid
    req_energy = float(task.get("required_energy", 5.0)) # scale 1-10
    energy_diff = user_energy - req_energy
    energy_match = sigmoid(energy_diff)

    # 5. Effort Coefficient
    effort = float(task.get("effort", 5.0)) # scale 1-10

    # Final Priority Computation
    numerator = urgency * affinity * habit_factor * energy_match
    denominator = effort + epsilon
    
    return round(numerator / denominator, 4)

def solve_task_optimization(
    tasks: List[Dict[str, Any]],
    user_energy_capacity: float,
    completed_task_ids: set
) -> Dict[str, Any]:
    """
    Solves 0-1 Integer Linear Program (ILP) matrix:
    Maximize Sum(P_i * x_i)
    Subject to Sum(E_i * x_i) <= Energy_Capacity
    x_i in {0, 1}
    x_i <= C_j(t) for all prerequisites j in D_i
    """
    start_time = time.time()

    # Calculate Priority for all tasks
    scored_tasks = []
    for t in tasks:
        score = calculate_priority_score(t, user_energy_capacity, completed_task_ids)
        t_copy = dict(t)
        t_copy["priority_score"] = score
        scored_tasks.append(t_copy)

    # Filter candidates with priority > 0
    candidate_tasks = [t for t in scored_tasks if t["priority_score"] > 0]

    if not candidate_tasks:
        solve_time_ms = (time.time() - start_time) * 1000
        return {
            "selected_tasks": [],
            "total_priority": 0.0,
            "total_effort_used": 0.0,
            "energy_capacity": user_energy_capacity,
            "solve_time_ms": round(solve_time_ms, 2),
            "status": "No eligible tasks"
        }

    # Set up PuLP ILP Problem
    prob = LpProblem("SynapseNode_TaskMaster_ILP", LpMaximize)
    
    # Decision Variables x_i in {0, 1}
    var_dict = {}
    for t in candidate_tasks:
        var_dict[t["id"]] = LpVariable(f"x_{t['id']}", cat="Binary")

    # Objective Function: Maximize Sum(P_i * x_i)
    prob += lpSum([t["priority_score"] * var_dict[t["id"]] for t in candidate_tasks])

    # Constraint 1: Energy Capacity Constraint Sum(E_i * x_i) <= User_Energy_Capacity
    prob += lpSum([t.get("effort", 5.0) * var_dict[t["id"]] for t in candidate_tasks]) <= user_energy_capacity

    # Solve ILP
    prob.solve(PULP_CBC_CMD(msg=False))

    selected_tasks = []
    total_priority = 0.0
    total_effort = 0.0

    for t in candidate_tasks:
        v = var_dict[t["id"]]
        if v.varValue and v.varValue > 0.5:
            selected_tasks.append(t)
            total_priority += t["priority_score"]
            total_effort += t.get("effort", 5.0)

    # Sort selected tasks by priority descending
    selected_tasks.sort(key=lambda x: x["priority_score"], reverse=True)
    solve_time_ms = (time.time() - start_time) * 1000

    return {
        "selected_tasks": selected_tasks,
        "total_priority": round(total_priority, 4),
        "total_effort_used": round(total_effort, 2),
        "energy_capacity": user_energy_capacity,
        "solve_time_ms": round(solve_time_ms, 2),
        "status": "Optimal"
    }
