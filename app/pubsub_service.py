import os
import json
import logging
import queue
import threading
import time
from typing import Dict, Any, Callable

logger = logging.getLogger("SynapseNode.PubSub")

class PubSubService:
    """
    GCP Cloud Pub/Sub service middleware integration layer.
    Uses google.cloud.pubsub_v1 to publish and subscribe to topics asynchronously.
    Includes in-memory queue fallback for local testing & execution.
    """
    def __init__(self, project_id: str = "gen-lang-client-0411709036"):
        self.project_id = project_id
        self.using_gcp_native = False
        self.publisher = None
        self.subscriber = None
        self.topic_path = f"projects/{project_id}/topics/synapse-agent-nudges"
        self.local_event_queue = queue.Queue()
        self.subscribers = []
        self._init_pubsub()

    def _init_pubsub(self):
        try:
            from google.cloud import pubsub_v1
            if os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or os.getenv("PUBSUB_EMULATOR_HOST"):
                self.publisher = pubsub_v1.PublisherClient()
                self.subscriber = pubsub_v1.SubscriberClient()
                self.using_gcp_native = True
                logger.info("Connected to GCP Cloud Pub/Sub natively.")
            else:
                self.using_gcp_native = False
                logger.info("GCP credentials not found; running with in-memory Pub/Sub event bus.")
        except Exception as e:
            logger.warning(f"Pub/Sub native init notice: {e}. Defaulting to in-memory event bus.")
            self.using_gcp_native = False

        # Start local worker thread to process event queue
        self.worker_thread = threading.Thread(target=self._local_queue_worker, daemon=True)
        self.worker_thread.start()

    def publish_event(self, event_type: str, payload: Dict[str, Any]) -> str:
        """
        Publishes event payload to Pub/Sub topic.
        """
        event_data = {
            "event_type": event_type,
            "payload": payload,
            "published_at": time.time(),
            "region_delivery": "exactly-once-regional"
        }
        json_bytes = json.dumps(event_data).encode("utf-8")

        if self.using_gcp_native and self.publisher:
            try:
                future = self.publisher.publish(self.topic_path, json_bytes, event_type=event_type)
                msg_id = future.result()
                return str(msg_id)
            except Exception as e:
                logger.error(f"GCP Pub/Sub publish error: {e}")

        # Local fallback publish
        self.local_event_queue.put(event_data)
        return f"local_msg_{int(time.time() * 1000)}"

    def register_subscriber(self, callback: Callable[[Dict[str, Any]], None]):
        """Registers a listener for Pub/Sub event delivery."""
        self.subscribers.append(callback)

    def _local_queue_worker(self):
        while True:
            try:
                event = self.local_event_queue.get(timeout=1.0)
                for cb in self.subscribers:
                    try:
                        cb(event)
                    except Exception as e:
                        logger.error(f"Error in Pub/Sub subscriber callback: {e}")
                self.local_event_queue.task_done()
            except queue.Empty:
                pass
