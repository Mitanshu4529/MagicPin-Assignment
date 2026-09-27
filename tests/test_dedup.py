"""
Test suppression, deduplication, and expiration.
"""
from datetime import datetime, timezone, timedelta
from state.conversations import ConversationManager
from composer.decision import is_expired, should_act


def test_suppression_and_expiry():
    cm = ConversationManager()
    key = "research:dentists:2026-W17"
    exp_iso = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()

    assert cm.is_suppressed(key) is False
    cm.suppress(key, exp_iso)
    assert cm.is_suppressed(key) is True

    # Test checking after expiration
    past_now = (datetime.now(timezone.utc) + timedelta(days=8)).isoformat()
    assert cm.is_suppressed(key, past_now) is False


def test_trigger_is_expired():
    future_trig = {"expires_at": "2099-01-01T00:00:00Z"}
    past_trig = {"expires_at": "2020-01-01T00:00:00Z"}
    no_exp_trig = {}

    assert is_expired(future_trig, "2026-04-26T10:00:00Z") is False
    assert is_expired(past_trig, "2026-04-26T10:00:00Z") is True
    assert is_expired(no_exp_trig, "2026-04-26T10:00:00Z") is False


def test_should_act_decision():
    trig = {"id": "trg_1", "scope": "merchant", "expires_at": "2099-01-01T00:00:00Z"}
    merch = {"merchant_id": "m_1"}
    cust = {"customer_id": "c_1", "preferences": {"reminder_opt_in": True}}

    # Active merchant trigger
    act, reason = should_act(trig, merch, None, None, is_suppressed=False)
    assert act is True
    assert reason == "ok"

    # Suppressed
    act, reason = should_act(trig, merch, None, None, is_suppressed=True)
    assert act is False
    assert reason == "suppressed"

    # Expired
    expired_trig = {"id": "trg_2", "scope": "merchant", "expires_at": "2020-01-01T00:00:00Z"}
    act, reason = should_act(expired_trig, merch, None, "2026-04-26T10:00:00Z", is_suppressed=False)
    assert act is False
    assert reason == "expired"

    # Customer opt-out consent
    opt_out_cust = {"customer_id": "c_2", "preferences": {"reminder_opt_in": False}}
    cust_trig = {"id": "trg_3", "scope": "customer"}
    act, reason = should_act(cust_trig, merch, opt_out_cust, None, is_suppressed=False)
    assert act is False
    assert reason == "opted_out"
