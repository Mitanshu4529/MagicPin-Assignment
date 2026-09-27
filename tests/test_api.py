"""
Test all 5 HTTP API endpoints using FastAPI TestClient:
- GET /v1/healthz
- GET /v1/metadata
- POST /v1/context (including 200, 409 stale, 400 invalid)
- POST /v1/tick
- POST /v1/reply
- POST /v1/teardown
"""
from fastapi.testclient import TestClient
from bot import app


def get_test_client():
    c = TestClient(app)
    c.post("/v1/teardown", json={})
    return c


def test_healthz_and_metadata(client=None):
    client = client or get_test_client()
    r = client.get("/v1/healthz")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "contexts_loaded" in data

    r = client.get("/v1/metadata")
    assert r.status_code == 200
    data = r.json()
    assert "team_name" in data
    assert "version" in data


def test_context_and_stale_rejection(client=None):
    client = client or get_test_client()
    cat_payload = {"slug": "dentists", "voice": {"tone": "peer_clinical"}}
    
    # Version 2 push -> 200 accepted
    r = client.post("/v1/context", json={
        "scope": "category",
        "context_id": "dentists",
        "version": 2,
        "payload": cat_payload,
    })
    assert r.status_code == 200
    assert r.json()["accepted"] is True

    # Same version 2 push -> 200 idempotent no-op
    r = client.post("/v1/context", json={
        "scope": "category",
        "context_id": "dentists",
        "version": 2,
        "payload": cat_payload,
    })
    assert r.status_code == 200
    assert r.json()["accepted"] is True

    # Stale version 1 push -> 409 conflict
    r = client.post("/v1/context", json={
        "scope": "category",
        "context_id": "dentists",
        "version": 1,
        "payload": cat_payload,
    })
    assert r.status_code == 409
    assert r.json()["accepted"] is False
    assert r.json()["reason"] == "stale_version"
    assert r.json()["current_version"] == 2


def test_tick_and_reply_flow(client=None):
    client = client or get_test_client()
    # Setup context
    client.post("/v1/context", json={
        "scope": "category",
        "context_id": "salons",
        "version": 1,
        "payload": {"slug": "salons", "voice": {"tone": "warm_practical"}},
    })
    client.post("/v1/context", json={
        "scope": "merchant",
        "context_id": "m_test_salon",
        "version": 1,
        "payload": {
            "merchant_id": "m_test_salon",
            "category_slug": "salons",
            "identity": {"name": "Style Studio", "owner_first_name": "Riya", "locality": "Indiranagar"},
            "offers": [{"id": "o_1", "title": "Haircut @ ₹99", "status": "active"}],
        },
    })
    client.post("/v1/context", json={
        "scope": "trigger",
        "context_id": "trg_test_fest",
        "version": 1,
        "payload": {
            "id": "trg_test_fest",
            "scope": "merchant",
            "kind": "festival_upcoming",
            "merchant_id": "m_test_salon",
            "payload": {"festival": "Diwali", "date": "2026-10-31", "days_until": 20},
            "urgency": 3,
            "suppression_key": "fest:diwali:2026",
        },
    })

    # Call /v1/tick
    r = client.post("/v1/tick", json={
        "now": "2026-04-26T10:00:00Z",
        "available_triggers": ["trg_test_fest"],
    })
    assert r.status_code == 200
    actions = r.json()["actions"]
    assert len(actions) == 1
    action = actions[0]
    assert action["merchant_id"] == "m_test_salon"
    assert action["send_as"] == "vera"
    assert "Diwali" in action["body"]
    assert "₹99" in action["body"]

    # Call /v1/reply with intent transition
    r = client.post("/v1/reply", json={
        "conversation_id": action["conversation_id"],
        "merchant_id": "m_test_salon",
        "from_role": "merchant",
        "message": "Ok lets do it. Whats next?",
        "turn_number": 2,
    })
    assert r.status_code == 200
    reply_data = r.json()
    assert reply_data["action"] == "send"
    assert any(w in reply_data["body"].lower() for w in ["draft", "done", "confirm", "next"])


def test_tick_action_limit_cap(client=None):
    client = client or get_test_client()
    client.post("/v1/context", json={
        "scope": "category", "context_id": "gyms", "version": 1,
        "payload": {"slug": "gyms", "voice": {"tone": "motivational"}},
    })
    client.post("/v1/context", json={
        "scope": "merchant", "context_id": "m_gym", "version": 1,
        "payload": {
            "merchant_id": "m_gym", "category_slug": "gyms",
            "identity": {"name": "Power Gym", "owner_first_name": "Rohan", "locality": "Koramangala"},
        },
    })
    trig_ids = []
    for i in range(25):
        tid = f"trg_gym_{i}"
        trig_ids.append(tid)
        client.post("/v1/context", json={
            "scope": "trigger", "context_id": tid, "version": 1,
            "payload": {
                "id": tid, "scope": "merchant", "kind": "curious_ask_due",
                "merchant_id": "m_gym", "payload": {}, "urgency": 3,
                "suppression_key": f"supp_gym_{i}",
            },
        })

    r = client.post("/v1/tick", json={
        "now": "2026-04-26T10:00:00Z",
        "available_triggers": trig_ids,
    })
    assert r.status_code == 200
    actions = r.json()["actions"]
    assert len(actions) <= 20  # Never exceed official 20 actions limit


def test_invalid_scope_rejection(client=None):
    client = client or get_test_client()
    r = client.post("/v1/context", json={
        "scope": "invalid_scope_foo",
        "context_id": "xyz",
        "version": 1,
        "payload": {},
    })
    assert r.status_code == 400
    assert r.json()["accepted"] is False
