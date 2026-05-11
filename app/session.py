import time
from typing import Any, Optional


class SessionStore:
    """In-memory session store with TTL.
    NOTE: Use Firestore for multi-instance production (Cloud Run min-instances=1 for PoC).
    """

    def __init__(self, ttl_seconds: int = 300):
        self._data: dict[str, dict] = {}
        self._ttl = ttl_seconds

    def set(self, user_id: str, key: str, value: Any) -> None:
        if user_id not in self._data:
            self._data[user_id] = {}
        self._data[user_id][key] = value
        self._data[user_id]["__expires"] = time.time() + self._ttl

    def get(self, user_id: str, key: str) -> Optional[Any]:
        entry = self._data.get(user_id, {})
        if time.time() > entry.get("__expires", 0):
            self._data.pop(user_id, None)
            return None
        return entry.get(key)

    def clear(self, user_id: str) -> None:
        self._data.pop(user_id, None)


session_store = SessionStore(ttl_seconds=300)
