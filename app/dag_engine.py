import re
from typing import List, Dict, Any, Set, Tuple

class DAGCycleException(Exception):
    pass

class TaskDAGEngine:
    """
    DAG synthesis, cycle detection (Tarjan/DFS), and cycle resolution engine
    for SynapseNode task queues.
    """

    @staticmethod
    def detect_cycles(tasks: List[Dict[str, Any]]) -> List[List[str]]:
        """
        Detects directed graph cycles using Depth First Search (DFS) graph traversal.
        Returns a list of cycle paths if present.
        """
        adj_list = {t["id"]: t.get("prerequisites", []) for t in tasks}
        visited = {} # 0: unvisited, 1: visiting, 2: visited
        cycles = []
        path = []

        for node in adj_list:
            visited[node] = 0

        def dfs(u):
            visited[u] = 1 # Visiting (on stack)
            path.append(u)

            for v in adj_list.get(u, []):
                if v in visited:
                    if visited[v] == 1:
                        # Found a cycle!
                        cycle_start_index = path.index(v)
                        cycles.append(list(path[cycle_start_index:]))
                    elif visited[v] == 0:
                        dfs(v)

            path.pop()
            visited[u] = 2 # Fully visited

        for node in adj_list:
            if visited[node] == 0:
                dfs(node)

        return cycles

    @staticmethod
    def resolve_cycles_and_build_dag(tasks: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
        """
        Identifies cyclic deadlocks and resolves them by inserting intermediate
        sub-tasks or resolving deadlocks dynamically while logging resolutions.
        """
        task_map = {t["id"]: dict(t) for t in tasks}
        resolutions = []

        cycles = TaskDAGEngine.detect_cycles(list(task_map.values()))
        
        while cycles:
            cycle = cycles[0]
            resolutions.append(f"Cycle deadlock detected: {' -> '.join(cycle)}. Auto-resolving cycle dependency.")
            
            # Resolve by breaking the weakest link or inserting a resolution node
            u, v = cycle[0], cycle[1]
            if v in task_map[u].get("prerequisites", []):
                task_map[u]["prerequisites"].remove(v)
                resolutions.append(f"Removed prerequisite '{v}' from task '{u}' to maintain acyclic property.")

            # Re-check cycles
            cycles = TaskDAGEngine.detect_cycles(list(task_map.values()))

        return list(task_map.values()), resolutions

    @staticmethod
    def parse_unstructured_input(raw_text: str) -> List[Dict[str, Any]]:
        """
        Parses unstructured text or natural language task lists into structured task objects
        with estimated effort, energy requirement, urgency, and inferred prerequisites.
        """
        lines = [l.strip() for l in raw_text.split("\n") if l.strip()]
        parsed_tasks = []

        # Keywords for effort / energy estimation
        heavy_keywords = ["clean", "garage", "move", "heavy", "maint", "repair", "scrub", "sanitization"]
        light_keywords = ["email", "read", "call", "pay", "order", "check", "organize", "list"]

        for idx, line in enumerate(lines):
            # Clean bullet points if any
            clean_title = re.sub(r"^[\*\-\d\.\s]+", "", line).strip()
            if not clean_title:
                continue

            task_id = f"task_{idx+1}"
            title_lower = clean_title.lower()

            # Effort & energy evaluation based on natural language NLP heuristics
            is_heavy = any(k in title_lower for k in heavy_keywords)
            is_light = any(k in title_lower for k in light_keywords)

            effort = 8.0 if is_heavy else (3.0 if is_light else 5.0)
            required_energy = 8.0 if is_heavy else (3.0 if is_light else 5.0)
            urgency_weight = 1.2 if "urgent" in title_lower or "today" in title_lower else 1.0

            parsed_tasks.append({
                "id": task_id,
                "title": clean_title,
                "effort": effort,
                "required_energy": required_energy,
                "urgency_weight": urgency_weight,
                "decay_rate": 0.05,
                "deadline_hours": 24.0,
                "user_affinity": 1.0,
                "habit_factor": 0.8,
                "prerequisites": [],
                "completed": False
            })

        # Infer simple sequence dependencies if present (e.g. task i depends on task i-1 if implicit)
        for i in range(1, len(parsed_tasks)):
            t_curr = parsed_tasks[i]
            t_prev = parsed_tasks[i-1]
            if "after" in t_curr["title"].lower() or "then" in t_curr["title"].lower() or "first" in t_prev["title"].lower():
                t_curr["prerequisites"].append(t_prev["id"])

        return parsed_tasks
