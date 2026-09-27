"""
Vera message engine — FastAPI surface for the magicpin AI Challenge.

Endpoints:
  GET  /v1/healthz
  GET  /v1/metadata
  POST /v1/context
  POST /v1/tick
  POST /v1/reply
  POST /v1/teardown   (optional; clears in-memory state)

Also exposes compose() and respond() for offline / unit use.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from state.store import global_store
from state.conversations import (
    global_conv_manager,
    detect_auto_reply,
    detect_hostile_or_optout,
)
from composer.engine import compose as compose_fn, respond as respond_fn, compose_action, compose_reply
from composer import decision
from composer.grounding import trigger_kind

APP_VERSION = "1.0.0"
TEAM_NAME = os.getenv("VERA_TEAM_NAME", "Vera Engine")
TEAM_MEMBERS = [m.strip() for m in os.getenv("VERA_TEAM_MEMBERS", "Candidate").split(",") if m.strip()]
CONTACT_EMAIL = os.getenv("VERA_CONTACT_EMAIL", "team@example.com")
MODEL_LABEL = os.getenv("LLM_MODEL") or os.getenv("LLM_PROVIDER") or "deterministic-grounded-composer"

app = FastAPI(title="Vera Message Engine", version=APP_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class ContextPush(BaseModel):
    scope: str
    context_id: str
    version: int
    payload: Dict[str, Any]
    delivered_at: Optional[str] = None


class TickRequest(BaseModel):
    now: Optional[str] = None
    available_triggers: List[str] = Field(default_factory=list)


class ReplyRequest(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: Optional[str] = "merchant"
    message: str = ""
    received_at: Optional[str] = None
    turn_number: Optional[int] = None


# ---------------------------------------------------------------------------
# Public functional API (challenge contract)
# ---------------------------------------------------------------------------

def compose(category, merchant, trigger, customer=None):
    return compose_fn(category, merchant, trigger, customer)


def respond(state, merchant_message):
    return respond_fn(state, merchant_message)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_category(merchant: Optional[Dict]) -> Dict:
    if not merchant:
        return {}
    slug = merchant.get("category_slug")
    if slug:
        cat = global_store.get_category(slug)
        if cat:
            return cat
    # last resort: only one category loaded
    cats = global_store.get_all_categories()
    if len(cats) == 1:
        return next(iter(cats.values()))
    return {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/v1/healthz")
def healthz():
    return {
        "status": "ok",
        "uptime_seconds": global_store.uptime_seconds,
        "contexts_loaded": global_store.get_counts(),
    }


@app.get("/v1/metadata")
def metadata():
    return {
        "team_name": TEAM_NAME,
        "team_members": TEAM_MEMBERS,
        "model": MODEL_LABEL,
        "approach": (
            "4-context deterministic composer with kind-dispatch, strict grounding "
            "(no invented numbers/dates/offers), suppression + expiry, and a "
            "conversation state machine (auto-reply ladder, intent-to-action, "
            "hostile opt-out, out-of-scope deflection). Optional LLM polish via env."
        ),
        "contact_email": CONTACT_EMAIL,
        "version": APP_VERSION,
        "submitted_at": "2026-04-26T08:00:00Z",
    }


@app.post("/v1/context")
def push_context(body: ContextPush):
    accepted, ack_or_reason, stored_at, current_ver = global_store.push_context(
        scope=body.scope,
        context_id=body.context_id,
        version=body.version,
        payload=body.payload,
        delivered_at=body.delivered_at,
    )
    if accepted:
        return {"accepted": True, "ack_id": ack_or_reason, "stored_at": stored_at}
    if ack_or_reason == "stale_version":
        raise HTTPException(
            status_code=409,
            detail={"accepted": False, "reason": "stale_version", "current_version": current_ver},
        )
    raise HTTPException(
        status_code=400,
        detail={"accepted": False, "reason": ack_or_reason or "invalid_scope"},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):
    from fastapi.responses import JSONResponse
    detail = exc.detail
    if isinstance(detail, dict):
        return JSONResponse(status_code=exc.status_code, content=detail)
    return JSONResponse(status_code=exc.status_code, content={"detail": detail})


@app.post("/v1/tick")
def tick(body: TickRequest):
    now = body.now or _now_iso()
    actions: List[Dict[str, Any]] = []
    seen_suppression = set()
    candidates = []

    for tid in body.available_triggers or []:
        trig = global_store.get_trigger(tid)
        if not trig:
            continue
        mid = trig.get("merchant_id")
        merchant = global_store.get_merchant(mid) if mid else None
        cid = trig.get("customer_id")
        customer = global_store.get_customer(cid) if cid else None
        key = trig.get("suppression_key")
        suppressed = global_conv_manager.is_suppressed(key, now)
        act, reason = decision.should_act(trig, merchant, customer, now, suppressed)
        if not act:
            continue
        candidates.append((trig, merchant, customer))

    for trig, merchant, customer in decision.rank_triggers_pairs(candidates):
        if len(actions) >= 20:
            break
        key = trig.get("suppression_key")
        if key and key in seen_suppression:
            continue
        category = _resolve_category(merchant)
        action = compose_action(category, merchant or {}, trig, customer)
        actions.append(action)
        if key:
            seen_suppression.add(key)
            global_conv_manager.suppress(key, trig.get("expires_at"))
        # seed conversation so /v1/reply can continue
        conv_id = action.get("conversation_id")
        if conv_id:
            conv = global_conv_manager.get_or_create(
                conversation_id=conv_id,
                merchant_id=(merchant or {}).get("merchant_id"),
                customer_id=(customer or {}).get("customer_id") if customer else None,
                trigger_id=trig.get("id"),
                suppression_key=key,
            )
            conv.add_turn("vera", action.get("body") or "", action="send",
                          cta=action.get("cta"), rationale=action.get("rationale"))
            # stash ids for reply
            conv.trigger_id = trig.get("id")
            conv.merchant_id = (merchant or {}).get("merchant_id")
            if customer:
                conv.customer_id = customer.get("customer_id")

    return {"actions": actions}


@app.post("/v1/reply")
def reply(body: ReplyRequest):
    conv = global_conv_manager.get_or_create(
        conversation_id=body.conversation_id,
        merchant_id=body.merchant_id or "unknown",
        customer_id=body.customer_id,
    )
    merchant = global_store.get_merchant(body.merchant_id or conv.merchant_id) or {}
    customer = None
    cid = body.customer_id or conv.customer_id
    if cid:
        customer = global_store.get_customer(cid)
    trigger = global_store.get_trigger(conv.trigger_id) if conv.trigger_id else None
    category = _resolve_category(merchant)

    result = compose_reply(
        merchant_message=body.message,
        state={"conversation": conv},
        merchant=merchant,
        category=category,
        trigger=trigger,
        customer=customer,
        conv=conv,
    )

    is_auto = detect_auto_reply(body.message, conv.last_user_message)
    if is_auto:
        conv.auto_reply_count += 1
    else:
        conv.auto_reply_count = 0

    conv.last_user_message = body.message
    conv.add_turn(body.from_role or "merchant", body.message)

    mid = body.merchant_id or conv.merchant_id
    if mid and mid != "unknown":
        global_conv_manager.record_merchant_message(mid, body.message, is_auto)

    action = result.get("action")
    if action == "end":
        conv.status = "ended"
        if conv.suppression_key:
            global_conv_manager.suppress(conv.suppression_key)
        # also suppress a merchant-level hostile key
        if detect_hostile_or_optout(body.message) and conv.merchant_id:
            global_conv_manager.suppress(f"hostile:{conv.merchant_id}")
    elif action == "wait":
        conv.status = "waiting"
        conv.wait_seconds = result.get("wait_seconds")
    else:
        conv.status = "active"
        conv.add_turn("vera", result.get("body") or "", action="send",
                      cta=result.get("cta"), rationale=result.get("rationale"))

    return result


@app.post("/v1/teardown")
def teardown():
    global_store.clear()
    global_conv_manager.clear()
    return {"ok": True, "cleared_at": _now_iso()}


# Patch rank helper onto decision if missing
if not hasattr(decision, "rank_triggers_pairs"):
    def rank_triggers_pairs(pairs):
        def key(item):
            t = item[0]
            urg = t.get("urgency") or 0
            try:
                urg = int(urg)
            except (TypeError, ValueError):
                urg = 0
            scope_boost = 1 if t.get("scope") == "merchant" else 0
            return (-urg, -scope_boost, t.get("id") or "")
        return sorted(pairs, key=key)
    decision.rank_triggers_pairs = rank_triggers_pairs


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("bot:app", host="0.0.0.0", port=port, reload=False)
