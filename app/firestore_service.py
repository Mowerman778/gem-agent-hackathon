import os
import re
import json
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger("SynapseNode.Firestore")

DEFAULT_PROFILE = "default"
DEFAULT_STATE = {"energy": 8.0, "receptivity": 0.8}


def normalise_profile(name: Optional[str]) -> str:
    """
    Profile names arrive from a request header, so they are untrusted and end up
    in a Firestore document path. Keep them to a safe, predictable slug.
    """
    slug = re.sub(r"[^a-z0-9_-]+", "-", (name or "").strip().lower()).strip("-")
    return slug[:40] or DEFAULT_PROFILE


class FirestoreService:
    """
    GCP Cloud Firestore client manager.

    Everything is stored per profile, so several people sharing one computer each
    keep their own tasks, settings and history. Native layout is
    profiles/{profile}/{tasks|user_state|agent_nudges}; the local fallback mirrors
    that shape under a "profiles" key.
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
            import google.auth
            google.auth.default()
            self.client = firestore.Client(project=self.project_id)
            self.using_gcp_native = True
            logger.info("Connected to GCP Cloud Firestore natively.")
        except Exception as e:
            logger.info(f"Firestore native unavailable ({type(e).__name__}); using local store.")
            self.using_gcp_native = False

        if not os.path.exists(self.local_storage_file):
            self._write_all({"profiles": {}})

    # ---- local fallback plumbing ----------------------------------------

    def _read_all(self) -> Dict[str, Any]:
        try:
            with open(self.local_storage_file, "r") as f:
                data = json.load(f)
        except Exception:
            data = {}
        data.setdefault("profiles", {})
        return data

    def _write_all(self, data: Dict[str, Any]):
        with open(self.local_storage_file, "w") as f:
            json.dump(data, f, indent=2)

    def _bucket(self, data: Dict[str, Any], profile: str) -> Dict[str, Any]:
        return data["profiles"].setdefault(
            profile, {"tasks": {}, "user_state": dict(DEFAULT_STATE), "agent_history": [], "preferences": {}}
        )

    def _doc(self, profile: str):
        return self.client.collection("profiles").document(profile)

    # ---- profiles --------------------------------------------------------

    def list_profiles(self) -> List[str]:
        if self.using_gcp_native and self.client:
            try:
                return sorted(d.id for d in self.client.collection("profiles").stream())
            except Exception as e:
                logger.warning(f"Could not list profiles: {e}")
                return []
        return sorted(self._read_all()["profiles"].keys())

    def create_profile(self, name: str) -> str:
        profile = normalise_profile(name)
        if self.using_gcp_native and self.client:
            self._doc(profile).set({"display_name": (name or profile).strip()}, merge=True)
            return profile
        data = self._read_all()
        self._bucket(data, profile)["display_name"] = (name or profile).strip()
        self._write_all(data)
        return profile

    # ---- tasks -----------------------------------------------------------

    def save_task(self, task: Dict[str, Any], profile: str = DEFAULT_PROFILE) -> str:
        profile = normalise_profile(profile)
        task_id = task.get("id")
        if self.using_gcp_native and self.client:
            self._doc(profile).collection("tasks").document(task_id).set(task, merge=True)
            return task_id
        data = self._read_all()
        self._bucket(data, profile)["tasks"][task_id] = task
        self._write_all(data)
        return task_id

    def get_all_tasks(self, profile: str = DEFAULT_PROFILE) -> List[Dict[str, Any]]:
        profile = normalise_profile(profile)
        if self.using_gcp_native and self.client:
            return [d.to_dict() for d in self._doc(profile).collection("tasks").stream()]
        data = self._read_all()
        return list(self._bucket(data, profile)["tasks"].values())

    def update_task_status(self, task_id: str, completed: bool, profile: str = DEFAULT_PROFILE) -> bool:
        profile = normalise_profile(profile)
        if self.using_gcp_native and self.client:
            self._doc(profile).collection("tasks").document(task_id).update({"completed": completed})
            return True
        data = self._read_all()
        tasks = self._bucket(data, profile)["tasks"]
        if task_id in tasks:
            tasks[task_id]["completed"] = completed
            self._write_all(data)
            return True
        return False

    def clear_tasks(self, profile: str = DEFAULT_PROFILE):
        profile = normalise_profile(profile)
        if self.using_gcp_native and self.client:
            for d in self._doc(profile).collection("tasks").stream():
                d.reference.delete()
            return
        data = self._read_all()
        self._bucket(data, profile)["tasks"] = {}
        self._write_all(data)

    # ---- state and preferences -------------------------------------------

    def save_user_state(self, user_state: Dict[str, Any], profile: str = DEFAULT_PROFILE):
        profile = normalise_profile(profile)
        if self.using_gcp_native and self.client:
            self._doc(profile).set({"user_state": user_state}, merge=True)
            return
        data = self._read_all()
        self._bucket(data, profile)["user_state"] = user_state
        self._write_all(data)

    def get_user_state(self, profile: str = DEFAULT_PROFILE) -> Dict[str, Any]:
        profile = normalise_profile(profile)
        if self.using_gcp_native and self.client:
            snap = self._doc(profile).get()
            return (snap.to_dict() or {}).get("user_state", dict(DEFAULT_STATE)) if snap.exists else dict(DEFAULT_STATE)
        data = self._read_all()
        return self._bucket(data, profile).get("user_state", dict(DEFAULT_STATE))

    def get_preferences(self, profile: str = DEFAULT_PROFILE) -> Dict[str, Any]:
        """What the helper has learned about this person."""
        profile = normalise_profile(profile)
        if self.using_gcp_native and self.client:
            snap = self._doc(profile).get()
            return (snap.to_dict() or {}).get("preferences", {}) if snap.exists else {}
        data = self._read_all()
        return self._bucket(data, profile).get("preferences", {})

    def save_preferences(self, preferences: Dict[str, Any], profile: str = DEFAULT_PROFILE):
        profile = normalise_profile(profile)
        if self.using_gcp_native and self.client:
            self._doc(profile).set({"preferences": preferences}, merge=True)
            return
        data = self._read_all()
        self._bucket(data, profile)["preferences"] = preferences
        self._write_all(data)

    def log_agent_nudge(self, nudge_data: Dict[str, Any], profile: str = DEFAULT_PROFILE):
        profile = normalise_profile(profile)
        if self.using_gcp_native and self.client:
            self._doc(profile).collection("agent_nudges").add(nudge_data)
            return
        data = self._read_all()
        self._bucket(data, profile)["agent_history"].append(nudge_data)
        self._write_all(data)

    def get_agent_history(self, profile: str = DEFAULT_PROFILE, limit: int = 10) -> List[Dict[str, Any]]:
        profile = normalise_profile(profile)
        if self.using_gcp_native and self.client:
            docs = list(self._doc(profile).collection("agent_nudges").stream())
            return [d.to_dict() for d in docs][-limit:]
        data = self._read_all()
        return self._bucket(data, profile)["agent_history"][-limit:]

    # kept so existing callers of the old private helper keep working
    def _read_local_store(self, profile: str = DEFAULT_PROFILE) -> Dict[str, Any]:
        return self._bucket(self._read_all(), normalise_profile(profile))
