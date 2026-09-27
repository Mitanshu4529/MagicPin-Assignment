"""
Test conversation state machine: auto-reply detection ladder, explicit intent transition to action, hostile/opt-out handling, and out-of-scope deflection.
"""
from composer.engine import compose_reply
from state.conversations import (
    ConversationState,
    detect_auto_reply,
    detect_hostile_or_optout,
    detect_action_intent,
    detect_out_of_scope,
)


def test_auto_reply_detection_and_ladder():
    auto_msg = "Thank you for contacting us! Our team will respond shortly."
    assert detect_auto_reply(auto_msg) is True
    assert detect_auto_reply("Hello, I have a question about haircuts") is False

    merch = {"merchant_id": "m_1", "identity": {"name": "Test Clinic", "owner_first_name": "Doc"}}
    cat = {"slug": "dentists"}
    trig = {"id": "trg_1", "kind": "research_digest"}

    # Turn 1 of auto-reply: prompts owner with YES/pause
    conv = ConversationState("conv_1", "m_1", trigger_id="trg_1")
    r1 = compose_reply(auto_msg, {}, merch, cat, trig, None, conv)
    assert r1["action"] == "send"
    conv.auto_reply_count = 1
    conv.last_user_message = auto_msg

    # Turn 2: same auto-reply -> wait 24h
    r2 = compose_reply(auto_msg, {}, merch, cat, trig, None, conv)
    assert r2["action"] == "wait"
    assert r2["wait_seconds"] == 86400
    conv.auto_reply_count = 2

    # Turn 3: same auto-reply -> end
    r3 = compose_reply(auto_msg, {}, merch, cat, trig, None, conv)
    assert r3["action"] == "end"


def test_intent_transition_to_action_mode():
    commitment_msgs = [
        "Ok lets do it. Whats next?",
        "Yes, proceed please",
        "Send it",
        "Let's do it",
        "Confirm",
    ]
    for msg in commitment_msgs:
        assert detect_action_intent(msg) is True

    merch = {"merchant_id": "m_1", "identity": {"name": "Test Salon", "owner_first_name": "Riya"}}
    cat = {"slug": "salons"}
    trig = {"id": "trg_fest", "kind": "festival_upcoming"}
    conv = ConversationState("conv_intent", "m_1", trigger_id="trg_fest")

    reply = compose_reply("Ok lets do it. Whats next?", {}, merch, cat, trig, None, conv)
    assert reply["action"] == "send"
    # Must switch to action / confirmation, not re-qualify with 'would you like to'
    body_lower = reply["body"].lower()
    assert any(w in body_lower for w in ["draft", "done", "confirm", "sending", "next"])
    assert "would you like" not in body_lower


def test_hostile_or_optout_ends_gracefully():
    hostile_msgs = [
        "Stop messaging me. This is useless spam.",
        "Unsubscribe",
        "Don't message me again",
        "Please remove me",
    ]
    for msg in hostile_msgs:
        assert detect_hostile_or_optout(msg) is True
        reply = compose_reply(msg, {}, {"identity": {}}, {}, None, None, None)
        assert reply["action"] == "end"


def test_out_of_scope_deflection():
    msg = "Can you also help me with my GST filing this month?"
    assert detect_out_of_scope(msg) is True

    merch = {"merchant_id": "m_1", "identity": {"name": "Test Cafe", "owner_first_name": "Chef"}}
    cat = {"slug": "restaurants"}
    trig = {"id": "trg_ipl", "kind": "ipl_match_today"}
    conv = ConversationState("conv_gst", "m_1", trigger_id="trg_ipl")

    reply = compose_reply(msg, {}, merch, cat, trig, None, conv)
    assert reply["action"] == "send"
    assert "CA" in reply["body"] or "specialist" in reply["body"]
    assert "ipl match today" in reply["body"].lower() or "draft" in reply["body"].lower()
