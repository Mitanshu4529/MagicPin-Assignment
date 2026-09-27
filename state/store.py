"""
Version-aware, thread-safe in-memory context store for the 4-context framework:
CategoryContext, MerchantContext, CustomerContext, and TriggerContext.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple


class ContextStore:
    def __init__(self):
        self._lock = threading.RLock()
        self._categories: Dict[str, Dict[str, Any]] = {}
        self._merchants: Dict[str, Dict[str, Any]] = {}
        self._customers: Dict[str, Dict[str, Any]] = {}
        self._triggers: Dict[str, Dict[str, Any]] = {}
        self._versions: Dict[str, int] = {}
        self._created_at = datetime.now(timezone.utc)

    def push_context(
        self,
        scope: str,
        context_id: str,
        version: int,
        payload: Dict[str, Any],
        delivered_at: Optional[str] = None
    ) -> Tuple[bool, Optional[str], Optional[str], Optional[int]]:
        """
        Stores context atomically with version conflict detection.
        Returns (accepted, ack_id_or_reason, stored_at, current_version).
        """
        with self._lock:
            valid_scopes = {"category", "merchant", "customer", "trigger"}
            if scope not in valid_scopes:
                return False, f"invalid_scope: {scope}", None, None

            key = f"{scope}:{context_id}"
            current_ver = self._versions.get(key, 0)

            # Idempotency / version conflict check
            if current_ver > 0:
                if version < current_ver:
                    return False, "stale_version", None, current_ver
                elif version == current_ver:
                    ack_id = f"ack_{context_id}_v{version}"
                    now_iso = datetime.now(timezone.utc).isoformat()
                    return True, ack_id, now_iso, version

            # Store payload
            now_iso = datetime.now(timezone.utc).isoformat()
            record = {
                "scope": scope,
                "context_id": context_id,
                "version": version,
                "payload": payload,
                "delivered_at": delivered_at,
                "stored_at": now_iso,
            }

            if scope == "category":
                slug = payload.get("slug") or context_id
                self._categories[slug] = payload
                self._categories[context_id] = payload
            elif scope == "merchant":
                mid = payload.get("merchant_id") or context_id
                self._merchants[mid] = payload
                self._merchants[context_id] = payload
            elif scope == "customer":
                cid = payload.get("customer_id") or context_id
                self._customers[cid] = payload
                self._customers[context_id] = payload
            elif scope == "trigger":
                tid = payload.get("id") or context_id
                self._triggers[tid] = payload
                self._triggers[context_id] = payload

            self._versions[key] = version
            ack_id = f"ack_{context_id}_v{version}"
            return True, ack_id, now_iso, version

    def get_category(self, slug: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._categories.get(slug)

    def get_merchant(self, merchant_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._merchants.get(merchant_id)

    def get_customer(self, customer_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._customers.get(customer_id)

    def get_trigger(self, trigger_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._triggers.get(trigger_id)

    def get_all_categories(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return dict(self._categories)

    def get_all_merchants(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return dict(self._merchants)

    def get_all_customers(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return dict(self._customers)

    def get_all_triggers(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return dict(self._triggers)

    def get_counts(self) -> Dict[str, int]:
        with self._lock:
            counts = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
            for k in self._versions.keys():
                sc = k.split(":")[0]
                if sc in counts:
                    counts[sc] += 1
            return counts

    def clear(self) -> None:
        with self._lock:
            self._categories.clear()
            self._merchants.clear()
            self._customers.clear()
            self._triggers.clear()
            self._versions.clear()

    @property
    def uptime_seconds(self) -> int:
        return int((datetime.now(timezone.utc) - self._created_at).total_seconds())


# Global singleton store instance
global_store = ContextStore()
