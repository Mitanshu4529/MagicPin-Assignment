"""Compose all 30 test pairs and print bodies. Also exercise reply heuristics."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from composer.engine import compose, compose_reply
from state.conversations import ConversationState, detect_auto_reply, detect_hostile_or_optout, detect_action_intent, detect_out_of_scope

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

pairs = json.load(open(ROOT / "expanded" / "test_pairs.json", encoding="utf-8"))["pairs"]
out_path = ROOT / "submission.jsonl"
lines = []

print("=" * 80)
print("COMPOSING 30 PAIRS")
print("=" * 80)
for p in pairs:
    tid, mid, cid = p["trigger_id"], p["merchant_id"], p["customer_id"]
    trig = json.load(open(ROOT / "expanded" / "triggers" / f"{tid}.json", encoding="utf-8"))
    merch = json.load(open(ROOT / "expanded" / "merchants" / f"{mid}.json", encoding="utf-8"))
    cust = json.load(open(ROOT / "expanded" / "customers" / f"{cid}.json", encoding="utf-8")) if cid else None
    cat = json.load(open(ROOT / "expanded" / "categories" / f"{merch['category_slug']}.json", encoding="utf-8"))
    action = compose(cat, merch, trig, cust)
    rec = {
        "test_id": p["test_id"],
        "body": action["body"],
        "cta": action["cta"],
        "send_as": action["send_as"],
        "suppression_key": action.get("suppression_key") or "",
        "rationale": action["rationale"],
    }
    lines.append(json.dumps(rec, ensure_ascii=False))
    body = action["body"]
    print(f"\n[{p['test_id']}] {trig['kind']} / {merch['category_slug']} / {merch['identity']['name']}")
    print(f"  send_as={action['send_as']} cta={action['cta']} chars={len(body)}")
    print("  " + body.replace("\n", "\n  ")[:600])

out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"\nWrote {out_path} ({len(lines)} lines)")

print("\n" + "=" * 80)
print("REPLY HEURISTICS")
print("=" * 80)
cases = [
    ("auto", "Thank you for contacting us! Our team will respond shortly."),
    ("hostile", "Stop messaging me. This is useless spam."),
    ("intent", "Ok lets do it. Whats next?"),
    ("gst", "Btw can you also help me with my GST filing this month?"),
]
# load one merchant for reply
merch = json.load(open(ROOT / "expanded" / "merchants" / "m_001_drmeera_dentist_delhi.json"))
cat = json.load(open(ROOT / "expanded" / "categories" / "dentists.json"))
trig = json.load(open(ROOT / "expanded" / "triggers" / "trg_022_cde_webinar_dentists.json"))

for label, msg in cases:
    conv = ConversationState("conv_test", merch["merchant_id"], trigger_id=trig["id"])
    r = compose_reply(msg, {}, merch, cat, trig, None, conv)
    print(f"  {label:8} action={r.get('action'):5} body={str(r.get('body') or r.get('rationale'))[:140]}")

# auto-reply ladder
print("\nAUTO-REPLY LADDER")
conv = ConversationState("conv_auto", merch["merchant_id"], trigger_id=trig["id"])
auto = "Thank you for contacting us! Our team will respond shortly."
for i in range(1, 5):
    r = compose_reply(auto, {}, merch, cat, trig, None, conv)
    if detect_auto_reply(auto, conv.last_user_message):
        conv.auto_reply_count += 1
    conv.last_user_message = auto
    print(f"  turn {i}: action={r.get('action')} wait={r.get('wait_seconds')} auto_count={conv.auto_reply_count}")
