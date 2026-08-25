import os
import json
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger("SynapseNode.Firestore")

class FirestoreService:
    """
    GCP Cloud Firestore client manager.
    Connects to Google Cloud Firestore using google-cloud-firestore SDK.
    Includes a local fallback store for seamless offline execution.
    """
    def __init__(self, project_id: str = "gen-lang-client-0411709036"):
        self.project_id = project_id
        self.using_gcp_native = False
        self.client = None
        self.local_storage_file = os.path.join(os.path.dirname(__file__), "local_firestore_db.json")
        self._init_client()

    def _init_client(self):
        try:
            from google.cloud import firestore
            if os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or os.getenv("FIRESTORE_EMULATOR_HOST"):
                self.client = firestore.Client(project=self.project_id)
                self.using_gcp_native = True
                logger.info("Connected to GCP Cloud Firestore natively.")
            else:
                logger.info("GCP credentials not found; running with local simulated Firestore document store.")
                self.using_gcp_native = False
        except Exception as e:
            logger.warning(f"Firestore native client init notice: {e}. Defaulting to local persistence store.")
            self.using_gcp_native = False

        if not os.path.exists(self.local_storage_file):
            self._write_local_store({"tasks": {}, "user_state": {}, "agent_history": []})

    def _read_local_store(self) -> Dict[str, Any]:
        try:
            with open(self.local_storage_file, "r") as f:
                return json.load(f)
        except Exception:
            return {"tasks": {}, "user_state": {}, "agent_history": []}

    def _write_local_store(self, data: Dict[str, Any]):
        with open(self.local_storage_file, "w") as f:
            json.dump(data, f, indent=2)

    def save_task(self, task: Dict[str, Any]) -> str:
        task_id = task.get("id")
        if self.using_gcp_native and self.client:
            doc_ref = self.client.collection("tasks").document(task_id)
            doc_ref.set(task, merge=True)
            return task_id

        # Local fallback
        store = self._read_local_store()
        store["tasks"][task_id] = task
        self._write_local_store(store)
        return task_id

    def get_all_tasks(self) -> List[Dict[str, Any]]:
        if self.using_gcp_native and self.client:
            docs = self.client.collection("tasks").stream()
            return [doc.to_dict() for doc in docs]

        store = self._read_local_store()
        return list(store.get("tasks", {}).values())

    def update_task_status(self, task_id: str, completed: bool) -> bool:
        if self.using_gcp_native and self.client:
            doc_ref = self.client.collection("tasks").document(task_id)
            doc_ref.update({"completed": completed})
            return True

        store = self._read_local_store()
        if task_id in store.get("tasks", {}):
            store["tasks"][task_id]["completed"] = completed
            self._write_local_store(store)
            return True
        return False

    def save_user_state(self, user_state: Dict[str, Any]):
        if self.using_gcp_native and self.client:
            self.client.collection("user_state").document("current").set(user_state, merge=True)
            return

        store = self._read_local_store()
        store["user_state"] = user_state
        self._write_local_store(store)

    def get_user_state(self) -> Dict[str, Any]:
        if self.using_gcp_native and self.client:
            doc = self.client.collection("user_state").document("current").get()
            return doc.to_dict() if doc.exists else {"energy": 8.0, "receptivity": 0.8}

        store = self._read_local_store()
        return store.get("user_state", {"energy": 8.0, "receptivity": 0.8})

    def log_agent_nudge(self, nudge_data: Dict[str, Any]):
        if self.using_gcp_native and self.client:
            self.client.collection("agent_nudges").add(nudge_data)
            return

        store = self._read_local_store()
        if "agent_history" not in store:
            store["agent_history"] = []
        store["agent_history"].append(nudge_data)
        self._write_local_store(store)
