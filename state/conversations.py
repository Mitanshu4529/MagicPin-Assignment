"""
Conversation state machine, suppression tracker, and multi-turn message analyzer for Vera.
"""

from __future__ import annotations

import re
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


class ConversationState:
    def __init__(
        self,
        conversation_id: str,
        merchant_id: str,
        customer_id: Optional[str] = None,
        trigger_id: Optional[str] = None,
        suppression_key: Optional[str] = None,
    ):
        self.conversation_id = conversation_id
        self.merchant_id = merchant_id
        self.customer_id = customer_id
        self.trigger_id = trigger_id
        self.suppression_key = suppression_key
        self.turns: List[Dict[str, Any]] = []
        self.status: str = "active"  # "active", "waiting", "ended", "suppressed"
        self.wait_seconds: Optional[int] = None
        self.wait_until: Optional[str] = None
        self.auto_reply_count: int = 0
        self.last_user_message: Optional[str] = None
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.updated_at = self.created_at

    def add_turn(self, role: str, message: str, action: str = "send", cta: Optional[str] = None, rationale: Optional[str] = None):
        self.turns.append({
            "turn_number": len(self.turns) + 1,
            "role": role,
            "message": message,
            "action": action,
            "cta": cta,
            "rationale": rationale,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        self.updated_at = datetime.now(timezone.utc).isoformat()


class ConversationManager:
    def __init__(self):
        self._lock = threading.RLock()
        self._conversations: Dict[str, ConversationState] = {}
        self._suppressions: Dict[str, Optional[str]] = {}  # key -> expires_at_iso
        self._merchant_auto_replies: Dict[str, int] = {}
        self._merchant_last_messages: Dict[str, str] = {}

    def get_or_create(
        self,
        conversation_id: str,
        merchant_id: str,
        customer_id: Optional[str] = None,
        trigger_id: Optional[str] = None,
        suppression_key: Optional[str] = None,
    ) -> ConversationState:
        with self._lock:
            if conversation_id not in self._conversations:
                self._conversations[conversation_id] = ConversationState(
                    conversation_id=conversation_id,
                    merchant_id=merchant_id,
                    customer_id=customer_id,
                    trigger_id=trigger_id,
                    suppression_key=suppression_key,
                )
            return self._conversations[conversation_id]

    def get_merchant_auto_reply_count(self, merchant_id: str) -> int:
        with self._lock:
            return self._merchant_auto_replies.get(merchant_id, 0)

    def record_merchant_message(self, merchant_id: str, message: str, is_auto: bool):
        with self._lock:
            if is_auto:
                self._merchant_auto_replies[merchant_id] = self._merchant_auto_replies.get(merchant_id, 0) + 1
            else:
                self._merchant_auto_replies[merchant_id] = 0
            self._merchant_last_messages[merchant_id] = message

    def get_merchant_last_message(self, merchant_id: str) -> Optional[str]:
        with self._lock:
            return self._merchant_last_messages.get(merchant_id)

    def get(self, conversation_id: str) -> Optional[ConversationState]:
        with self._lock:
            return self._conversations.get(conversation_id)

    def suppress(self, key: str, expires_at: Optional[str] = None):
        if not key:
            return
        with self._lock:
            self._suppressions[key] = expires_at

    def is_suppressed(self, key: str, now_iso: Optional[str] = None) -> bool:
        if not key:
            return False
        with self._lock:
            if key not in self._suppressions:
                return False
            exp = self._suppressions[key]
            if not exp:
                return True
            try:
                now_dt = datetime.fromisoformat(now_iso.replace("Z", "+00:00")) if now_iso else datetime.now(timezone.utc)
                exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
                if now_dt >= exp_dt:
                    del self._suppressions[key]
                    return False
                return True
            except Exception:
                return True

    def clear(self):
        with self._lock:
            self._conversations.clear()
            self._suppressions.clear()
            self._merchant_auto_replies.clear()
            self._merchant_last_messages.clear()


# Analysis functions for replies

AUTO_REPLY_PATTERNS = [
    r"thank\s+you\s+for\s+contacting",
    r"our\s+team\s+will\s+respond\s+shortly",
    r"we\s+will\s+get\s+back\s+to\s+you",
    r"auto-reply",
    r"automated\s+response",
    r"automated\s+message",
    r"currently\s+unavailable",
    r"away\s+from\s+the\s+phone",
    r"out\s+of\s+office",
    r"please\s+leave\s+a\s+message",
    r"we\s+are\s+closed\s+right\s+now",
    r"thanks\s+for\s+reaching\s+out.*respond\s+as\s+soon\s+as\s+possible",
]

HOSTILE_PATTERNS = [
    r"\bstop\b",
    r"stop\s+messaging",
    r"unsubscribe",
    r"leave\s+me\s+alone",
    r"spam",
    r"useless\s+spam",
    r"don't\s+message",
    r"do\s+not\s+message",
    r"not\s+interested",
    r"remove\s+me",
    r"take\s+me\s+off",
    r"shut\s+up",
    r"harassment",
    r"fuck",
    r"fraud",
]

INTENT_ACTION_PATTERNS = [
    r"let['’]?s\s+do\s+it",
    r"\bproceed\b",
    r"yes\s+please",
    r"\bdo\s+it\b",
    r"send\s+it",
    r"\bconfirm\b",
    r"sounds\s+good",
    r"go\s+ahead",
    r"what['’]?s\s+next",
    r"whats\s+next",
    r"\bi['’]?m\s+ready\b",
    r"schedule\s+it",
    r"push\s+it",
    r"please\s+send",
    r"send\s+the\s+abstract",
    r"draft\s+the\s+patient",
    r"yes\s+send",
    r"send\s+me\s+the",
]

OUT_OF_SCOPE_PATTERNS = [
    r"\bgst\b",
    r"tax\s+filing",
    r"file\s+my\s+gst",
    r"income\s+tax",
    r"file\s+tax",
    r"bank\s+loan",
    r"personal\s+loan",
    r"accounting\s+software",
    r"weather\s+in",
    r"cricket\s+score",
    r"ipl\s+score",
    r"cook\s+recipe",
]


def detect_auto_reply(message: str, previous_user_message: Optional[str] = None) -> bool:
    """Checks if message matches canned auto-responder signatures or is an identical duplicate."""
    msg_clean = message.strip().lower()
    if previous_user_message and msg_clean == previous_user_message.strip().lower():
        return True
    for pattern in AUTO_REPLY_PATTERNS:
        if re.search(pattern, msg_clean, re.IGNORECASE):
            return True
    return False


def detect_hostile_or_optout(message: str) -> bool:
    """Checks if message contains opt-out requests, hostility, or complaints."""
    msg_clean = message.strip().lower()
    for pattern in HOSTILE_PATTERNS:
        if re.search(pattern, msg_clean, re.IGNORECASE):
            return True
    return False


def detect_action_intent(message: str) -> bool:
    """Checks if merchant has given explicit consent/instruction to proceed."""
    msg_clean = message.strip().lower()
    for pattern in INTENT_ACTION_PATTERNS:
        if re.search(pattern, msg_clean, re.IGNORECASE):
            return True
    return False


def detect_out_of_scope(message: str) -> bool:
    """Checks if message asks for services outside Vera's operational scope (e.g., GST filing)."""
    msg_clean = message.strip().lower()
    for pattern in OUT_OF_SCOPE_PATTERNS:
        if re.search(pattern, msg_clean, re.IGNORECASE):
            return True
    return False


global_conv_manager = ConversationManager()
