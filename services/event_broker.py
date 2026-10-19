import json
import queue
import threading
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class SSEBroker:
    """
    Thread-safe Server-Sent Events (SSE) broker.
    Enables real-time push notifications from server to admin dashboards
    when files are uploaded, accessed, or migrated.
    """
    def __init__(self):
        self._listeners = set()
        self._lock = threading.Lock()

    def subscribe(self):
        """Register a new client listener queue."""
        q = queue.Queue(maxsize=150)
        with self._lock:
            self._listeners.add(q)
        return q

    def unsubscribe(self, q):
        """Unregister a client listener queue."""
        with self._lock:
            self._listeners.discard(q)

    def broadcast(self, event_type, data):
        """Broadcast an event payload to all connected subscribers."""
        if not isinstance(data, dict):
            data = {"message": str(data)}
        
        # Add timestamp if not present
        if "timestamp" not in data:
            data["timestamp"] = datetime.now().isoformat()
        data["event_type"] = event_type

        payload = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
        
        with self._lock:
            dead_queues = []
            for q in list(self._listeners):
                try:
                    q.put_nowait(payload)
                except queue.Full:
                    dead_queues.append(q)
            for q in dead_queues:
                self._listeners.discard(q)

    @property
    def client_count(self):
        with self._lock:
            return len(self._listeners)


# Global singleton instance
broker = SSEBroker()
