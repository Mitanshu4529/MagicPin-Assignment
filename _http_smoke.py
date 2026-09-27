"""HTTP smoke: context push (incl 409), tick, reply ladder, teardown."""
import json
import sys
from pathlib import Path
from urllib import request as urlrequest, error as urlerror

ROOT = Path(__file__).parent
BASE = "http://localhost:8080"


def req(method, path, body=None, timeout=15):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urlrequest.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        resp = urlrequest.urlopen(r, timeout=timeout)
        return resp.status, json.loads(resp.read().decode("utf-8"))
    except urlerror.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {"raw": raw}
        return e.code, parsed


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def load(kind, stem):
    return json.load(open(ROOT / "expanded" / kind / f"{stem}.json", encoding="utf-8"))


print("teardown", req("POST", "/v1/teardown", {}))

cat = load("categories", "dentists")
status, data = req("POST", "/v1/context", {
    "scope": "category", "context_id": "dentists", "version": 2, "payload": cat,
    "delivered_at": "2026-04-26T09:45:00Z",
})
print("push cat v2 (accepted?):", status, data.get("accepted"))

status, data = req("POST", "/v1/context", {
    "scope": "category", "context_id": "dentists", "version": 2, "payload": cat,
})
print("same-version v2 (idempotent 200?):", status, data.get("accepted"))

status, data = req("POST", "/v1/context", {
    "scope": "category", "context_id": "dentists", "version": 1, "payload": cat,
})
print("lower-version v1 (stale 409?):", status, data.get("accepted"), data.get("reason"))

merch = load("merchants", "m_001_drmeera_dentist_delhi")
status, data = req("POST", "/v1/context", {
    "scope": "merchant", "context_id": merch["merchant_id"], "version": 1, "payload": merch,
})
print("push merch", status, data.get("accepted"))

trig = load("triggers", "trg_022_cde_webinar_dentists")
status, data = req("POST", "/v1/context", {
    "scope": "trigger", "context_id": trig["id"], "version": 1, "payload": trig,
})
print("push trig", status, data.get("accepted"))

status, data = req("POST", "/v1/tick", {
    "now": "2026-04-26T10:35:00Z",
    "available_triggers": [trig["id"]],
})
print("tick status", status)
actions = data.get("actions") or []
print("n_actions", len(actions))
if actions:
    a = actions[0]
    print("body:", a.get("body", "")[:240])
    print("send_as", a.get("send_as"), "cta", a.get("cta"), "conv", a.get("conversation_id"))
    conv = a["conversation_id"]
    mid = a["merchant_id"]
else:
    conv, mid = "conv_x", merch["merchant_id"]

# auto-reply ladder on a FRESH conversation (judge uses conv_auto_1..)
print("\n--- auto-reply on new conv ---")
auto = "Thank you for contacting us! Our team will respond shortly."
for i in range(1, 5):
    status, data = req("POST", "/v1/reply", {
        "conversation_id": f"conv_auto_{i}",
        "merchant_id": mid,
        "customer_id": None,
        "from_role": "merchant",
        "message": auto,
        "received_at": "2026-04-26T10:42:00Z",
        "turn_number": i + 1,
    })
    print(f"  auto {i}: {status} action={data.get('action')} wait={data.get('wait_seconds')}")

print("\n--- auto-reply SAME conv (true ladder) ---")
for i in range(1, 5):
    status, data = req("POST", "/v1/reply", {
        "conversation_id": "conv_auto_ladder",
        "merchant_id": mid,
        "from_role": "merchant",
        "message": auto,
        "turn_number": i + 1,
    })
    print(f"  ladder {i}: action={data.get('action')} wait={data.get('wait_seconds')}")

print("\n--- intent ---")
status, data = req("POST", "/v1/reply", {
    "conversation_id": "conv_intent_1",
    "merchant_id": mid,
    "from_role": "merchant",
    "message": "Ok lets do it. Whats next?",
    "turn_number": 2,
})
print("  intent", data.get("action"), (data.get("body") or "")[:180])

print("\n--- hostile ---")
status, data = req("POST", "/v1/reply", {
    "conversation_id": "conv_hostile",
    "merchant_id": mid,
    "from_role": "merchant",
    "message": "Stop messaging me. This is useless spam.",
    "turn_number": 2,
})
print("  hostile", data.get("action"), data.get("rationale", "")[:120])

print("\nhealthz", req("GET", "/v1/healthz")[1])
