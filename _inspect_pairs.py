import json
from pathlib import Path

pairs = json.load(open("expanded/test_pairs.json"))["pairs"]
for p in pairs:
    tid = p["trigger_id"]
    mid = p["merchant_id"]
    cid = p["customer_id"]
    trig = json.load(open(f"expanded/triggers/{tid}.json"))
    merch = json.load(open(f"expanded/merchants/{mid}.json"))
    cust = json.load(open(f"expanded/customers/{cid}.json")) if cid else None
    cat_slug = merch.get("category_slug")
    ident = merch.get("identity", {})
    cust_name = cust.get("identity", {}).get("name") if cust else "None"
    print("=" * 80)
    print(f"[{p['test_id']}] kind={trig.get('kind')} scope={trig.get('scope')} cat={cat_slug}")
    print(f"  merchant={ident.get('name')} owner={ident.get('owner_first_name')} city={ident.get('city')} loc={ident.get('locality')}")
    print(f"  customer={cust_name}")
    print(f"  payload={json.dumps(trig.get('payload'), ensure_ascii=False)}")
    print(f"  urgency={trig.get('urgency')} suppression={trig.get('suppression_key')}")
    perf = merch.get("performance", {})
    print(f"  perf views={perf.get('views')} calls={perf.get('calls')} ctr={perf.get('ctr')} delta={perf.get('delta_7d')}")
    offers = merch.get("offers", [])
    print(f"  offers={[o.get('title') for o in offers]}")
    print(f"  signals={merch.get('signals')}")
    agg = merch.get("customer_aggregate", {})
    print(f"  aggregate={agg}")
    if cust:
        print(f"  cust_state={cust.get('state')} lang={cust.get('identity', {}).get('language_pref')} rel={cust.get('relationship')}")
        print(f"  prefs={cust.get('preferences')} consent={cust.get('consent')}")
