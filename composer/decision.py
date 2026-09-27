"""
Decision layer: should we send, wait, or skip — and with what strategy.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from composer import grounding as g


def parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        raw = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def is_expired(trigger: Dict, now_iso: Optional[str]) -> bool:
    exp = trigger.get("expires_at")
    exp_dt = parse_iso(exp)
    now_dt = parse_iso(now_iso) or datetime.now(timezone.utc)
    if exp_dt is None:
        return False
    return now_dt >= exp_dt


def should_act(
    trigger: Dict,
    merchant: Optional[Dict],
    customer: Optional[Dict],
    now_iso: Optional[str],
    is_suppressed: bool,
) -> Tuple[bool, str]:
    """
    Returns (act, reason). Restraint is rewarded; we skip expired, suppressed,
    missing-merchant, and customer-scope-without-customer cases.
    """
    if is_suppressed:
        return False, "suppressed"
    if is_expired(trigger, now_iso):
        return False, "expired"
    if not merchant:
        return False, "missing_merchant"
    scope = g.trigger_scope(trigger)
    if scope == "customer" and not customer:
        return False, "missing_customer"
    # Consent: if customer-scoped and reminder_opt_in is explicitly False, skip
    if customer:
        prefs = customer.get("preferences") or {}
        if prefs.get("reminder_opt_in") is False or prefs.get("opt_in") is False:
            return False, "opted_out"
        consent = customer.get("consent") or {}
        if consent.get("status") in ("opted_out", "revoked", "inactive") or consent.get("opted_in") is False:
            return False, "opted_out"
    return True, "ok"


def _urgency_key(t: Dict):
    urg = t.get("urgency") or 0
    try:
        urg = int(urg)
    except (TypeError, ValueError):
        urg = 0
    scope_boost = 1 if t.get("scope") == "merchant" else 0
    return (-urg, -scope_boost, t.get("id") or "")


def rank_triggers(triggers: List[Dict]) -> List[Dict]:
    """Highest urgency first; merchant-scope slightly preferred over customer for ties."""
    return sorted(triggers, key=_urgency_key)


def rank_triggers_pairs(pairs):
    """pairs: List[(trigger, merchant, customer)]"""
    return sorted(pairs, key=lambda item: _urgency_key(item[0]))


def send_as_for(trigger: Dict) -> str:
    return "merchant_on_behalf" if g.trigger_scope(trigger) == "customer" else "vera"


def cta_for(kind: str, scope: str) -> str:
    mapping = {
        "appointment_tomorrow": "binary_yes_no",
        "recall_due": "multi_choice_slot",
        "chronic_refill_due": "binary_confirm_cancel",
        "customer_lapsed_hard": "binary_yes_no",
        "customer_lapsed_soft": "binary_yes_no",
        "active_planning_intent": "open_ended",
        "curious_ask_due": "open_ended",
        "festival_upcoming": "binary_yes_no",
        "ipl_match_today": "binary_yes_no",
        "competitor_opened": "binary_yes_no",
        "perf_dip": "binary_yes_no",
        "perf_spike": "binary_yes_no",
        "milestone_reached": "binary_yes_no",
        "dormant_with_vera": "open_ended",
        "gbp_unverified": "binary_yes_no",
        "cde_opportunity": "binary_yes_no",
        "regulation_change": "binary_yes_no",
        "category_seasonal": "binary_yes_no",
        "research_digest": "open_ended",
        "renewal_due": "binary_yes_no",
        "review_theme_emerged": "binary_yes_no",
        "trial_followup": "binary_yes_no",
        "wedding_package_followup": "binary_yes_no",
        "winback_eligible": "binary_yes_no",
        "supply_alert": "binary_yes_no",
        "seasonal_perf_dip": "binary_yes_no",
        "bridal_followup": "binary_yes_no",
    }
    return mapping.get(kind, "open_ended" if scope == "merchant" else "binary_yes_no")


def template_name_for(kind: str, scope: str) -> str:
    prefix = "merchant" if scope == "customer" else "vera"
    return f"{prefix}_{kind}_v1"
