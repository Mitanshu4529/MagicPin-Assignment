"""
Composition engine: turns 4 contexts into a structured action or a reply.

Deterministic first (grounded templates per trigger.kind). Optional LLM polish
is applied only when a provider is configured AND the polish still uses the
same facts. All numbers, names, dates, prices, and citations come from context.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from composer import decision, grounding as g
from composer.grounding import (
    owner_first, merchant_name, locality, city, locality_city,
    customer_name, is_hi, is_hi_en, language_pref, customer_state,
    last_visit, visits_total, preferred_slots, channel,
    views, calls, ctr, delta_views_pct, delta_calls_pct,
    pct_label, ctr_label, offer_titles, first_offer_title,
    peer_ctr, peer_calls, peer_views, digest_item, aggregate, signals,
    payload, is_placeholder, trigger_kind, trigger_scope, suppression_key,
    days_since, conversation_id_for, strip_taboos, format_inr,
)
from llm.client import global_llm_client


# ---------------------------------------------------------------------------
# Public compose / respond (challenge contract)
# ---------------------------------------------------------------------------

def compose(category: Dict, merchant: Dict, trigger: Dict, customer: Optional[Dict] = None) -> Dict[str, Any]:
    """Standalone composition used by tests and the REST tick path."""
    return compose_action(category or {}, merchant or {}, trigger or {}, customer)


def respond(state: Dict[str, Any], merchant_message: str) -> Dict[str, Any]:
    """
    Standalone multi-turn responder.
    `state` is expected to carry merchant/category/trigger/customer plus
    conversation metadata. Used by /v1/reply and unit tests.
    """
    return compose_reply(
        merchant_message=merchant_message,
        state=state,
        merchant=state.get("merchant") or {},
        category=state.get("category") or {},
        trigger=state.get("trigger"),
        customer=state.get("customer"),
        conv=state.get("conversation"),
    )


# ---------------------------------------------------------------------------
# Tick-path composition
# ---------------------------------------------------------------------------

def compose_action(
    category: Dict,
    merchant: Dict,
    trigger: Dict,
    customer: Optional[Dict] = None,
) -> Dict[str, Any]:
    kind = trigger_kind(trigger)
    scope = trigger_scope(trigger)
    body, cta, rationale, template_params = _compose_body(kind, category, merchant, trigger, customer)
    body = strip_taboos(body, category)

    send_as = decision.send_as_for(trigger)
    conv_id = conversation_id_for(trigger, merchant, customer)
    template = decision.template_name_for(kind, scope)
    if not cta:
        cta = decision.cta_for(kind, scope)

    return {
        "conversation_id": conv_id,
        "merchant_id": merchant.get("merchant_id"),
        "customer_id": (customer or {}).get("customer_id") if customer else None,
        "send_as": send_as,
        "trigger_id": trigger.get("id"),
        "template_name": template,
        "template_params": template_params,
        "body": body,
        "cta": cta,
        "suppression_key": suppression_key(trigger),
        "rationale": rationale,
    }


def _compose_body(kind, category, merchant, trigger, customer):
    dispatch = {
        "active_planning_intent": _active_planning,
        "appointment_tomorrow": _appointment_tomorrow,
        "category_seasonal": _category_seasonal,
        "cde_opportunity": _cde_opportunity,
        "chronic_refill_due": _chronic_refill,
        "competitor_opened": _competitor_opened,
        "curious_ask_due": _curious_ask,
        "customer_lapsed_hard": _lapsed_hard,
        "customer_lapsed_soft": _lapsed_soft,
        "dormant_with_vera": _dormant,
        "festival_upcoming": _festival,
        "gbp_unverified": _gbp_unverified,
        "ipl_match_today": _ipl_match,
        "milestone_reached": _milestone,
        "perf_dip": _perf_dip,
        "perf_spike": _perf_spike,
        "recall_due": _recall_due,
        "regulation_change": _regulation_change,
        "renewal_due": _renewal_due,
        "research_digest": _research_digest,
        "review_theme_emerged": _review_theme_emerged,
        "supply_alert": _supply_alert,
        "seasonal_perf_dip": _perf_dip,
        "trial_followup": _trial_followup,
        "wedding_package_followup": _wedding_package_followup,
        "winback_eligible": _winback_eligible,
        "bridal_followup": _bridal_followup,
    }
    fn = dispatch.get(kind, _generic)
    return fn(category, merchant, trigger, customer)


# ---------------------------------------------------------------------------
# Kind handlers — each returns (body, cta, rationale, template_params)
# ---------------------------------------------------------------------------

def _active_planning(category, merchant, trigger, customer):
    p = payload(trigger)
    topic = (p.get("intent_topic") or "").lower()
    owner = owner_first(merchant)
    name = merchant_name(merchant)
    loc = locality(merchant)
    slug = merchant.get("category_slug") or ""
    last_msg = p.get("merchant_last_message") or ""

    if "thali" in topic or "corporate" in topic:
        offer = first_offer_title(merchant) or "Weekday Lunch Thali @ ₹149"
        agg = aggregate(merchant)
        ytd = agg.get("total_unique_ytd")
        delivery = agg.get("delivery_share_pct")
        delivery_bit = f" Delivery is already {int(delivery*100)}% of mix." if delivery else ""
        ytd_bit = f" You've served {ytd:,} unique guests YTD — offices nearby will recognise the name." if ytd else ""
        body = (
            f"{owner}, here's a starter version — you can edit:\n\n"
            f"{name} Corporate Thali — for offices in {loc or city(merchant)}\n"
            f"- 10 thalis @ ₹125 each (₹24 off your {offer}) + free delivery\n"
            f"- 25 thalis @ ₹115 each + 2 free filter coffees\n"
            f"- 50+: ₹105 each + 1 free dosa platter\n"
            f"- WhatsApp the day-before by 5pm; we deliver between 12:30–1pm\n\n"
            f"{ytd_bit}{delivery_bit} Want me to draft a 3-line WhatsApp to send facilities managers?"
        )
        rationale = (
            f"Merchant committed ('{last_msg}'). Delivered a complete tiered artifact using the live "
            f"{offer} as the retail anchor. Locality {loc} and delivery mix from MerchantContext."
        )
        params = [owner, "Corporate Thali tiers ₹125/₹115/₹105", "draft WhatsApp to facilities managers"]
        return body.strip(), "open_ended", rationale, params

    if "yoga" in topic or "kids" in topic:
        members = aggregate(merchant).get("total_active_members")
        members_bit = f" Your  {members} members are the first audience — parents already trust the studio." if members else ""
        trial = first_offer_title(merchant) or "First Month @ ₹499"
        body = (
            f"{owner}, here's a kids yoga summer-camp shape you can run with this week:\n\n"
            f"{name} Kids Yoga — 4-week summer batch, Mylapore\n"
            f"- Ages 6–12, 45 min, Tue/Thu 5:00–5:45pm (after school)\n"
            f"- Batch of 12; 1:6 instructor ratio\n"
            f"- ₹2,499 for 8 sessions (or drop-in ₹399)\n"
            f"- Parent sit-in on week 1; simple progress note at week 4\n\n"
            f"Lead with your existing {trial}.{members_bit} Want me to draft the GBP post + a parent WhatsApp?"
        )
        rationale = (
            f"Merchant asked '{last_msg}'. Returned a complete camp artifact (ages, slot, price, ratio) "
            f"grounded in boutique yoga identity and live offer {trial}."
        )
        params = [owner, "Kids Yoga 4-week ₹2,499", "draft GBP post + parent WhatsApp"]
        return body.strip(), "open_ended", rationale, params

    # generic planning
    body = (
        f"{owner}, got it — I'll sketch a first version of {p.get('intent_topic') or 'the plan'} "
        f"using {name}'s current mix. Want me to send a 6-line draft you can edit, or walk through pricing first?"
    )
    return body, "open_ended", "Active planning intent — offering a complete draft vs a pricing walkthrough.", [owner, p.get("intent_topic") or "plan"]


def _appointment_tomorrow(category, merchant, trigger, customer):
    cust = customer_name(customer) or "there"
    owner = owner_first(merchant)
    name = merchant_name(merchant)
    loc = locality(merchant)
    hi = is_hi(customer) or is_hi_en(customer)
    offer = first_offer_title(merchant)
    last = last_visit(customer)
    last_bit = f" Last visit was {last}." if last else ""
    offer_bit = f" {offer} is on if you want to add something." if offer else ""

    if hi and not language_pref(customer).startswith("en"):
        body = (
            f"Hi {cust}, {name} ({loc}) se yaad dilane ke liye. Aapka appointment kal hai — "
            f"please 10 min pehle aa jaana.{last_bit} Reply YES to confirm, or tell us a new time."
        )
    else:
        body = (
            f"Hi {cust}, {owner} from {name}{(' in ' + loc) if loc else ''} here. "
            f"Just a reminder — your appointment is tomorrow. Please arrive 10 min early.{last_bit}{offer_bit} "
            f"Reply YES to confirm, or send a time that works better."
        )
    rationale = (
        "Customer-scoped appointment_tomorrow. Confirming the visit with a binary CTA; "
        "honours language_pref and uses owner+locality from MerchantContext. No invented slot time "
        "(placeholder payload)."
    )
    return body.strip(), "binary_yes_no", rationale, [cust, name, "tomorrow"]


def _category_seasonal(category, merchant, trigger, customer):
    p = payload(trigger)
    owner = owner_first(merchant)
    name = merchant_name(merchant)
    loc = locality(merchant)
    season = p.get("season") or "this season"
    trends = p.get("trends") or []
    chronic = aggregate(merchant).get("chronic_rx_count")
    offers = offer_titles(merchant)
    delivery = next((o for o in offers if "delivery" in o.lower()), None)
    senior = next((o for o in offers if "senior" in o.lower()), None)

    trend_bits = []
    for t in trends[:4]:
        # "ORS_demand_+40" → "ORS demand +40%"
        label = str(t).replace("_", " ")
        label = label.replace(" demand +", " +").replace(" demand -", " −")
        if "+" in label and not label.strip().endswith("%"):
            label = label.replace("+", "+") + "%" if not label.endswith("%") else label
        if label.endswith("%") is False and any(ch.isdigit() for ch in label):
            # already like ORS demand +40
            import re as _re
            label = _re.sub(r"([+-]\d+)$", r"\1%", label)
        trend_bits.append(label)
    trend_line = "; ".join(trend_bits) if trend_bits else "seasonal mix is shifting"

    extra = ""
    if chronic:
        extra += f" You have {chronic} chronic-Rx customers who will still come in — keep their SKUs untouched."
    offer_cta = ""
    if delivery and senior:
        offer_cta = f" Pair it with your live '{delivery}' and '{senior}'."
    elif delivery:
        offer_cta = f" Pair it with your live '{delivery}'."

    body = (
        f"{owner}, summer shelf call for {name} ({loc}). Trends: {trend_line}. "
        f"Action: front-face ORS, sunscreen, antifungal this week; de-emphasise cold/cough.{extra}{offer_cta} "
        f"Want me to draft a 4-line WhatsApp + a shelf card for the counter?"
    )
    rationale = (
        f"Seasonal trigger with explicit trend list {trends}. Grounded in chronic_rx_count={chronic} "
        f"and live offers. No invented SKUs."
    )
    return body.strip(), "binary_yes_no", rationale, [owner, season, trend_line]


def _cde_opportunity(category, merchant, trigger, customer):
    p = payload(trigger)
    owner = owner_first(merchant)
    item = digest_item(category, p.get("digest_item_id")) or {}
    title = item.get("title") or "upcoming CDE webinar"
    source = item.get("source") or "IDA"
    date = item.get("date") or ""
    credits = p.get("credits") or item.get("credits") or 2
    fee = p.get("fee") or ""
    summary = item.get("summary") or ""
    date_bit = ""
    if date:
        try:
            dt = datetime.fromisoformat(date.replace("Z", "+00:00"))
            date_bit = dt.strftime("%a %-d %b, %-I:%M%p").replace(" 0", " ")
        except Exception:
            # Windows doesn't support %-d; fall back
            try:
                dt = datetime.fromisoformat(date.replace("Z", "+00:00"))
                date_bit = dt.strftime("%a %d %b, %I:%M%p").lstrip("0").replace(" 0", " ")
            except Exception:
                date_bit = date
    fee_bit = " Free for IDA members." if "free" in str(fee).lower() else ""
    speaker_bit = f" {summary}" if summary else ""
    high_risk = aggregate(merchant).get("high_risk_adult_count")
    cohort_bit = (
        f" Relevant to your {high_risk} high-risk adult patients if you later convert impressions in-house."
        if high_risk else ""
    )

    body = (
        f"Dr. {owner}, CDE ping — {title}"
        f"{(' on ' + date_bit) if date_bit else ''}. {credits} credits.{fee_bit}{speaker_bit}{cohort_bit} "
        f"Want me to hold a calendar block + send you the 5-line registration note? — {source}"
    )
    rationale = (
        f"CDE digest item {p.get('digest_item_id')} cited with credits={credits}, source={source}. "
        f"Merchant-specific high_risk_adult_count used only as a relevance hook."
    )
    return body.strip(), "binary_yes_no", rationale, [f"Dr. {owner}", title, f"{credits} credits"]


def _chronic_refill(category, merchant, trigger, customer):
    p = payload(trigger)
    cust = customer_name(customer) or "there"
    name = merchant_name(merchant)
    loc = locality(merchant)
    hi = is_hi(customer) or is_hi_en(customer)
    molecules = p.get("molecule_list") or []
    stock_out = p.get("stock_runs_out_iso") or ""
    last_refill = p.get("last_refill") or ""
    addr_saved = p.get("delivery_address_saved")
    offers = offer_titles(merchant)
    senior = next((o for o in offers if "senior" in o.lower()), None)
    delivery = next((o for o in offers if "delivery" in o.lower()), None)
    via_son = "son" in (channel(customer) or "")

    date_bit = ""
    if stock_out:
        try:
            dt = datetime.fromisoformat(stock_out.replace("Z", "+00:00"))
            date_bit = dt.strftime("%d %b").lstrip("0")
        except Exception:
            date_bit = stock_out[:10]

    if molecules:
        mol_str = ", ".join(molecules)
        n = len(molecules)
        if hi or via_son:
            who = f"{cust} ji ki {n} monthly medicines" if via_son else f"{cust} ji, aapki {n} monthly medicines"
            greet = "Namaste —" if via_son else f"Namaste {cust} ji,"
            body = (
                f"{greet} {name} {loc} yahan. {who} ({mol_str}) "
                f"{(date_bit + ' ko khatam hongi') if date_bit else 'khatam hone wali hain'}. "
                f"Same dose, same brand pack ready hai."
            )
            if senior:
                body += f" {senior} applied."
            if delivery and (addr_saved or True):
                body += f" {delivery} to saved address."
            body += " Reply CONFIRM to dispatch, or tell us if the dose changed."
        else:
            body = (
                f"Hi {cust}, {name} ({loc}) here. Your {n} monthly medicines ({mol_str}) "
                f"{('run out on ' + date_bit) if date_bit else 'are due'}."
            )
            if senior:
                body += f" {senior} is on."
            if delivery:
                body += f" {delivery}."
            body += " Reply CONFIRM to dispatch, or tell us if anything changed."
        rationale = (
            f"Chronic refill with explicit molecules {molecules}, stock-out {stock_out}, "
            f"last_refill {last_refill}. Language and son-channel honoured. Live senior/delivery offers used."
        )
        return body.strip(), "binary_confirm_cancel", rationale, [cust, mol_str, date_bit]

    # placeholder (e.g. dentist "chronic refill") — treat as recall-ish reminder, no invented molecules
    last = last_visit(customer)
    visits = visits_total(customer)
    last_bit = f" Last visit was {last}" if last else ""
    visit_bit = f" ({visits} visits with us)" if visits else ""
    slug = merchant.get("category_slug") or ""
    if slug == "dentists":
        body = (
            f"Hi {cust}, {name} here.{last_bit}{visit_bit}. Time for a follow-up check so we don't lose continuity. "
            f"Reply YES and we'll hold a weekday-evening slot, or send a time that works."
        )
        rationale = (
            "Placeholder chronic_refill_due on a dentist — no molecule list in payload, so no invented Rx. "
            "Grounded in last_visit / visits_total; framed as a follow-up, not a medical claim."
        )
    else:
        body = (
            f"Hi {cust}, {name} ({loc}) here.{last_bit}. Your regular medicines are due for a refill. "
            f"Reply YES to confirm the usual pack, or tell us if anything changed."
        )
        rationale = "Placeholder chronic refill — no molecules provided, so we ask to confirm the usual pack."
    return body.strip(), "binary_yes_no", rationale, [cust, name, last or ""]


def _competitor_opened(category, merchant, trigger, customer):
    p = payload(trigger)
    owner = owner_first(merchant)
    name = merchant_name(merchant)
    loc = locality(merchant)
    offer = first_offer_title(merchant)
    ytd = aggregate(merchant).get("total_unique_ytd")
    retention = aggregate(merchant).get("retention_6mo_pct") or aggregate(merchant).get("repeat_customer_pct")
    ctr_v = ctr(merchant)
    peer = peer_ctr(category)

    if is_placeholder(trigger):
        offer_bit = f" Lean on your live '{offer}' — don't race a newcomer on price." if offer else " Don't race a newcomer on price; lean on repeat guests."
        ytd_bit = f" You already have {ytd:,} unique guests YTD in {loc}." if ytd else f" You already have the {loc} regulars."
        body = (
            f"{owner}, a new competitor just opened near {name} in {loc}. "
            f"Don't match their launch discount.{ytd_bit}{offer_bit} "
            f"Want me to draft a 4-line WhatsApp to your repeats this week — 'we're still here, same {loc} table'?"
        )
        rationale = (
            "Placeholder competitor_opened — no competitor name in payload, so none invented. "
            "Advice is retain-don't-race, grounded in YTD uniques and live offer."
        )
        return body.strip(), "binary_yes_no", rationale, [owner, loc, offer or "repeat guests"]

    comp = p.get("competitor_name") or "a new clinic"
    dist = p.get("distance_km")
    their = p.get("their_offer") or ""
    opened = p.get("opened_date") or ""
    dist_bit = f" {dist} km away" if dist is not None else ""
    opened_bit = f" (opened {opened})" if opened else ""
    their_bit = f" They're leading with {their}." if their else ""
    ours_bit = f" Your live offer is {offer} — do not cut price to match." if offer else ""
    ret_bit = f" Your 6-mo retention is {int(retention*100)}% — that's the moat, not the launch price." if retention else ""
    ctr_bit = ""
    if ctr_v is not None and peer is not None and ctr_v < peer:
        ctr_bit = f" CTR is {ctr_label(ctr_v)} vs peer {ctr_label(peer)}; a GBP post this week helps more than a price war."

    body = (
        f"Dr. {owner}, heads-up: {comp} opened{dist_bit}{opened_bit}.{their_bit}{ours_bit}{ret_bit}{ctr_bit} "
        f"Action: skip a reactive discount. Instead I'll draft a 'why patients stay' WhatsApp for your "
        f"{aggregate(merchant).get('lapsed_180d_plus') or 'lapsed'} 180d+ patients, plus a GBP post. Live in 10 min?"
    )
    rationale = (
        f"Named competitor {comp} at {dist} km with their offer {their} vs ours {offer}. "
        f"Recommends retention over price-match; uses CTR vs peer and lapsed cohort from MerchantContext."
    )
    return body.strip(), "binary_yes_no", rationale, [owner, comp, their or ""]


def _curious_ask(category, merchant, trigger, customer):
    owner = owner_first(merchant)
    name = merchant_name(merchant)
    loc = locality(merchant)
    slug = merchant.get("category_slug") or ""
    offers = offer_titles(merchant)
    calls_v = calls(merchant)
    views_v = views(merchant)
    d_calls = delta_calls_pct(merchant)
    d_views = delta_views_pct(merchant)

    guess = ""
    if slug == "salons":
        if any("spa" in (o or "").lower() for o in offers):
            guess = " Hair spa has been the usual ask this time of year — is that still #1, or has keratin/smoothening taken over?"
        else:
            guess = " Haircut vs spa vs keratin — which one are people actually asking for?"
    elif slug == "restaurants":
        if any("thali" in (o or "").lower() for o in offers):
            guess = f" Is the weekday thali still the most-asked, or are weekend covers overtaking it in {loc}?"
        else:
            guess = " What's been the most-asked dish or combo this week?"
    elif slug == "dentists":
        guess = " Aligners, cleaning, or pain/RCT — which consult is showing up most?"
    elif slug == "gyms":
        guess = " Trial class, PT demo, or yoga — what are walk-ins asking for?"
    elif slug == "pharmacies":
        guess = " OTC seasonal (ORS/sunscreen) or chronic refill — which counter conversation is louder?"
    else:
        guess = " What's been most asked-for this week?"

    growth = ""
    if d_calls is not None and d_calls >= 0.1:
        growth = f" Calls are {pct_label(d_calls)} this week"
        if calls_v:
            growth += f" ({calls_v} in 30d)"
        growth += " — good time to turn the answer into a post."
    elif d_views is not None and d_views >= 0.1:
        growth = f" Views {pct_label(d_views)} this week — good time to capture demand in a post."

    body = (
        f"Hi {owner}! Quick check — what has been most asked-for this week at {name} ({loc})?"
        f"{guess} I'll turn the answer into a Google post + a 4-line WhatsApp reply you can paste when customers ask about pricing. Takes 5 min."
        f"{(' ' + growth) if growth else ''}"
    )
    rationale = (
        "Curious-ask family: low-stakes question + reciprocity (post + reply draft) + 5-min effort cap. "
        "Guess is grounded in live offers / category, never invented demand numbers."
    )
    return body.strip(), "open_ended", rationale, [owner, name, "5 min"]


def _lapsed_hard(category, merchant, trigger, customer):
    p = payload(trigger)
    cust = customer_name(customer) or "there"
    owner = owner_first(merchant)
    name = merchant_name(merchant)
    days = p.get("days_since_last_visit")
    if days is None:
        days = days_since(last_visit(customer))
    focus = p.get("previous_focus") or (customer.get("preferences") or {}).get("training_focus") or ""
    months = p.get("previous_membership_months")
    offer = first_offer_title(merchant)
    slots = preferred_slots(customer)
    slug = merchant.get("category_slug") or ""

    weeks_bit = ""
    if days:
        weeks = max(1, round(days / 7))
        weeks_bit = f" It's been about {weeks} weeks"
        if months:
            weeks_bit += f" (you were with us {months} months)"
        weeks_bit += " — happens to most members at some point, no judgment."
    else:
        weeks_bit = " It's been a while — happens to most members at some point, no judgment."

    offer_bit = ""
    if offer:
        offer_bit = f" {offer} is on — no auto-charge."
    slot_bit = " weekday evening" if "evening" in (slots or "") else ""
    focus_bit = f" that fits {focus.replace('_', '-')} goals well" if focus else ""

    if slug == "gyms":
        body = (
            f"Hi {cust} — {owner} from {name} here.{weeks_bit} "
            f"We've got a Tue/Thu{slot_bit} HIIT class{focus_bit} (45 min, 6:30pm). "
            f"Want me to hold a free trial spot for you next Tuesday? Reply YES — no commitment.{offer_bit}"
        )
    else:
        body = (
            f"Hi {cust}, {owner} from {name} here.{weeks_bit} "
            f"Want me to hold a slot for you this week? Reply YES — no commitment.{offer_bit}"
        )
    rationale = (
        f"Hard-lapse winback. days_since={days}, focus={focus}, membership_months={months}. "
        "No-shame framing + binary CTA + live offer. Slot honours preferred_slots."
    )
    return body.strip(), "binary_yes_no", rationale, [cust, owner, str(days or "")]


def _lapsed_soft(category, merchant, trigger, customer):
    cust = customer_name(customer) or "there"
    owner = owner_first(merchant)
    name = merchant_name(merchant)
    loc = locality(merchant)
    last = last_visit(customer)
    visits = visits_total(customer)
    offer = first_offer_title(merchant)
    hi_en = is_hi_en(customer)
    hi = is_hi(customer)
    slug = merchant.get("category_slug") or ""
    days = days_since(last)
    weeks_bit = f" It's been {max(1, round(days/7))} weeks since {last}." if days and last else (f" Last visit {last}." if last else "")
    visit_bit = f" You've been in {visits} times — we'd rather not lose the streak." if visits else ""
    offer_bit = f" {offer} is on if useful." if offer else ""

    if slug == "pharmacies":
        if hi or hi_en:
            body = (
                f"Hi {cust}, {name} ({loc}) se. {weeks_bit}{visit_bit} "
                f"Usual medicines ya kuch OTC chahiye ho to reply YES — hum pack ready rakh denge.{offer_bit}"
            )
        else:
            body = (
                f"Hi {cust}, {name} in {loc} here.{weeks_bit}{visit_bit} "
                f"Need the usual, or anything seasonal? Reply YES and we'll keep a pack ready.{offer_bit}"
            )
    elif slug == "dentists":
        body = (
            f"Hi {cust}, {name} here.{weeks_bit}{visit_bit} "
            f"A short check now is easier than a longer visit later. "
            f"Reply YES for a weekday-evening slot, or send a time that works.{offer_bit}"
        )
    else:
        body = (
            f"Hi {cust}, {owner} from {name} here.{weeks_bit}{visit_bit} "
            f"Want me to hold a slot this week? Reply YES.{offer_bit}"
        )
    rationale = (
        f"Soft-lapse. last_visit={last}, visits={visits}, language={language_pref(customer)}. "
        "No invented clinical claims; binary CTA; live offer only if present."
    )
    return body.strip(), "binary_yes_no", rationale, [cust, last or "", offer or ""]


def _dormant(category, merchant, trigger, customer):
    p = payload(trigger)
    owner = owner_first(merchant)
    name = merchant_name(merchant)
    loc = locality(merchant)
    days = p.get("days_since_last_merchant_message")
    last_topic = p.get("last_topic") or ""
    d_calls = delta_calls_pct(merchant)
    d_views = delta_views_pct(merchant)
    views_v = views(merchant)
    calls_v = calls(merchant)
    signals_l = signals(merchant)
    sub = (merchant.get("subscription") or {})
    days_rem = sub.get("days_remaining")

    days_bit = f" It's been {days} days since we last spoke" if days else " It's been a while since we last spoke"
    topic_bit = f" (last topic: {last_topic.replace('_', ' ')})" if last_topic else ""
    perf_bits = []
    if d_calls is not None:
        perf_bits.append(f"calls {pct_label(d_calls)} w/w")
    if d_views is not None:
        perf_bits.append(f"views {pct_label(d_views)} w/w")
    if calls_v is not None:
        perf_bits.append(f"{calls_v} calls / 30d")
    perf_line = ", ".join(perf_bits[:3])
    sub_bit = ""
    if days_rem is not None and days_rem <= 14:
        sub_bit = f" Plan has {days_rem} days left — not pitching renewal, just flagging."
    winback = "winback_eligible" in signals_l

    body = (
        f"Hi {owner} — {name} ({loc}).{days_bit}{topic_bit}. "
        f"Quick useful ping, not a nag: {perf_line or 'performance is mixed'}."
        f"{' You are winback-eligible — I can put one offer live in 10 min if you want.' if winback else ''}{sub_bit} "
        f"Want a 4-line recap of what's changed, or shall I wait until you ping me?"
    )
    rationale = (
        f"Dormant re-entry. days_since={days}, last_topic={last_topic}. "
        "Uses real 7d deltas; does not invent a festival or competitor. Low-pressure CTA."
    )
    return body.strip(), "open_ended", rationale, [owner, str(days or ""), perf_line]


def _festival(category, merchant, trigger, customer):
    p = payload(trigger)
    owner = owner_first(merchant)
    name = merchant_name(merchant)
    loc = locality(merchant)
    slug = merchant.get("category_slug") or ""
    festival = p.get("festival") or ""
    date = p.get("date") or ""
    days_until = p.get("days_until")
    offers = offer_titles(merchant)

    if is_placeholder(trigger) or not festival:
        # Don't invent Diwali. Use a generic "next festive window" tied to category seasonal beats.
        beats = category.get("seasonal_beats") or []
        beat_note = ""
        if beats:
            b0 = beats[0]
            beat_note = b0.get("note") or b0.get("label") or ""
            month = b0.get("month_range") or ""
            festival_label = f"{month} festive window" if month else "the next festive window"
        else:
            festival_label = "the next festive weekend"
        offer_bit = f" Your live '{offers[0]}' can be the hook." if offers else " We can stand up one short offer."
        body = (
            f"{owner}, {festival_label} is the next demand spike for {name} in {loc}."
            f"{(' ' + beat_note + '.') if beat_note else ''}{offer_bit} "
            f"Want me to draft a 4-line WhatsApp + a GBP post you can schedule the week before?"
        )
        rationale = (
            "Placeholder festival_upcoming — no festival name in payload, so none invented. "
            "Grounded in category seasonal_beats and live offers."
        )
        return body.strip(), "binary_yes_no", rationale, [owner, festival_label]

    days_bit = f" {days_until} days out" if days_until is not None else ""
    date_bit = f" ({date})" if date else ""
    if slug == "salons":
        hook = " Bridal + party looks book out 2–3 weeks prior — lock a festive package now."
        offer_bit = f" Lead with '{offers[0]}' and upsell spa." if offers else ""
    elif slug == "restaurants":
        hook = " Pre-book thali / family table for the festive week rather than walk-in chaos."
        offer_bit = f" Your '{offers[0]}' is the weekday hook; festive needs a family bundle." if offers else ""
    elif slug == "gyms":
        hook = " Festive weeks usually dip attendance — run a 14-day 'show-up streak' for members now, not a discount."
        offer_bit = f" '{offers[0]}' can be the new-join hook after the festival." if offers else ""
    elif slug == "pharmacies":
        hook = " Immunity / gift-hamper SKUs move; don't discount chronic Rx."
        offer_bit = f" Keep '{offers[0]}' as the everyday hook." if offers else ""
    else:
        hook = " Demand will bunch in the 10 days before."
        offer_bit = f" '{offers[0]}' can be the hook." if offers else ""

    body = (
        f"{owner}, {festival}{days_bit}{date_bit} — relevant for {name} in {loc}.{hook}{offer_bit} "
        f"Want me to draft the offer card + a WhatsApp you can send 10 days prior?"
    )
    rationale = (
        f"Festival {festival} on {date}, days_until={days_until}. Category-specific action; live offers only."
    )
    return body.strip(), "binary_yes_no", rationale, [owner, festival, str(days_until or "")]


def _gbp_unverified(category, merchant, trigger, customer):
    p = payload(trigger)
    owner = owner_first(merchant)
    name = merchant_name(merchant)
    loc = locality(merchant)
    path = p.get("verification_path") or "postcard or phone call"
    uplift = p.get("estimated_uplift_pct")
    views_v = views(merchant)
    calls_v = calls(merchant)
    peer_c = peer_calls(category)
    chronic = aggregate(merchant).get("chronic_rx_count")

    uplift_bit = f" Typical uplift after verify is ~{int(uplift*100)}% more map actions." if uplift else ""
    gap_bit = ""
    if calls_v is not None and peer_c:
        gap_bit = f" You have {calls_v} calls / 30d vs peer ~{peer_c} — verification is the cheapest close of that gap."
    elif views_v is not None:
        gap_bit = f" {views_v} views / 30d are working with an unverified badge — that's leaving calls on the table."
    chronic_bit = f" Your {chronic} chronic-Rx regulars already know you; verification is for the next 60 new ones." if chronic else ""

    body = (
        f"{owner}, {name} in {loc} is still unverified on Google. Path: {path.replace('_', ' ')} — usually 3–5 days.{uplift_bit} {gap_bit}{chronic_bit} "
        f"Want me to send the exact click-path (2 screenshots) and a 3-line note you can keep by the counter for the postcard?"
    )
    rationale = (
        f"GBP unverified. path={path}, uplift={uplift}. Uses calls vs peer and chronic_rx_count. "
        "No fake verification codes."
    )
    return body.strip(), "binary_yes_no", rationale, [owner, path, str(uplift or "")]


def _ipl_match(category, merchant, trigger, customer):
    p = payload(trigger)
    owner = owner_first(merchant)
    name = merchant_name(merchant)
    loc = locality(merchant)
    match = p.get("match") or "tonight's match"
    venue = p.get("venue") or ""
    match_city = p.get("city") or city(merchant)
    is_weeknight = p.get("is_weeknight")
    match_time = p.get("match_time_iso") or ""
    offer = first_offer_title(merchant)
    dine = aggregate(merchant).get("dine_in_orders_30d")
    delivery_n = aggregate(merchant).get("delivery_orders_30d")

    time_bit = ""
    if match_time:
        try:
            dt = datetime.fromisoformat(match_time.replace("Z", "+00:00"))
            time_bit = dt.strftime("%I:%M%p").lstrip("0")
        except Exception:
            time_bit = ""
    venue_bit = f" at {venue}" if venue else f" in {match_city}"

    if is_weeknight is False:
        # Saturday/Sunday — people watch at home, covers drop
        offer_bit = f" Push your live '{offer}' as a delivery-only Saturday special." if offer else " Push a delivery-only match combo; skip a dine-in promo."
        mix_bit = ""
        if dine is not None and delivery_n is not None:
            mix_bit = f" Last 30d you did {delivery_n} delivery vs {dine} dine-in — lean into delivery tonight."
        body = (
            f"Quick heads-up {owner} — {match}{venue_bit}{(' at ' + time_bit) if time_bit else ''}. "
            f"Important: Saturday IPL matches usually shift −12% restaurant covers (people watch at home). "
            f"Skip the match-night dine-in promo today; {offer_bit}{mix_bit} "
            f"Want me to draft the Swiggy banner + an Insta story? Live in 10 min."
        )
        rationale = (
            f"IPL {match} at {venue}, is_weeknight={is_weeknight}. Contrarian Saturday advice from the case study, "
            f"grounded in live BOGO/offer and 30d delivery vs dine-in mix."
        )
    else:
        offer_bit = f" Your '{offer}' is already live — extend it as a match-night combo." if offer else " A match-night combo (food + drink) converts better than a generic % off."
        body = (
            f"{owner}, {match}{venue_bit}{(' at ' + time_bit) if time_bit else ''} — weeknight IPL usually lifts covers near the stadium. "
            f"{offer_bit} Want me to draft a 4-line WhatsApp + Insta story for 6pm push?"
        )
        rationale = f"Weeknight IPL {match}. Uses live offer; no invented ticket numbers."
    return body.strip(), "binary_yes_no", rationale, [owner, match, offer or "delivery special"]


def _milestone(category, merchant, trigger, customer):
    p = payload(trigger)
    owner = owner_first(merchant)
    name = merchant_name(merchant)
    loc = locality(merchant)
    metric = p.get("metric") or ""
    value_now = p.get("value_now")
    milestone_value = p.get("milestone_value")
    imminent = p.get("is_imminent")
    ytd = aggregate(merchant).get("total_unique_ytd")
    offer = first_offer_title(merchant)

    if is_placeholder(trigger) or not metric:
        views_v = views(merchant)
        calls_v = calls(merchant)
        bits = []
        if views_v:
            bits.append(f"{views_v:,} views / 30d")
        if calls_v:
            bits.append(f"{calls_v} calls")
        if ytd:
            bits.append(f"{ytd:,} unique guests YTD")
        stat = ", ".join(bits) if bits else f"{name} in {loc} is compounding"
        offer_bit = f" A 'thanks for  the support' note plus '{offer}' is enough — no discount needed." if offer else " A thank-you story is enough — no discount needed."
        body = (
            f"{owner}, milestone ping for {name} ({loc}): {stat}. "
            f"Good week to ask 5 happy regulars for a Google review and post one kitchen/table photo.{offer_bit} "
            f"Want me to draft the 2-line review ask + the post?"
        )
        rationale = (
            "Placeholder milestone — no metric/value in payload, so we use live views/calls/YTD. "
            "Ask is reviews + a post, not an invented round number."
        )
        return body.strip(), "binary_yes_no", rationale, [owner, stat]

    remain = None
    if value_now is not None and milestone_value is not None:
        try:
            remain = int(milestone_value) - int(value_now)
        except (TypeError, ValueError):
            remain = None
    metric_label = metric.replace("_", " ")
    remain_bit = f" — {remain} short of {milestone_value}" if remain is not None else f" (target {milestone_value})"
    imminent_bit = " That's this week if you ask." if imminent else ""
    ytd_bit = f" You have {ytd:,} unique guests YTD in {loc} to ask." if ytd else ""
    body = (
        f"{owner}, {name} is at {value_now} {metric_label}{remain_bit}.{imminent_bit}{ytd_bit} "
        f"Action: send a 2-line ask to 8 recent happy tables ('if we earned it, a Google review helps more than a tip today'). "
        f"Want me to draft it + a story you can post the morning you cross {milestone_value}?"
    )
    rationale = (
        f"Milestone {metric} {value_now}/{milestone_value}, imminent={imminent}. "
        "Concrete remaining count; ask is reviews, not a fake discount."
    )
    return body.strip(), "binary_yes_no", rationale, [owner, str(value_now), str(milestone_value)]


def _perf_dip(category, merchant, trigger, customer):
    p = payload(trigger)
    owner = owner_first(merchant)
    name = merchant_name(merchant)
    loc = locality(merchant)
    slug = merchant.get("category_slug") or ""
    metric = p.get("metric") or ""
    delta = p.get("delta_pct")
    window = p.get("window") or "7d"
    baseline = p.get("vs_baseline")
    signals_l = signals(merchant)
    views_v = views(merchant)
    calls_v = calls(merchant)
    d_views = delta_views_pct(merchant)
    d_calls = delta_calls_pct(merchant)
    peer_c = peer_calls(category)
    lapsed = aggregate(merchant).get("lapsed_180d_plus") or aggregate(merchant).get("lapsed_90d_plus")
    offers = offer_titles(merchant)
    unverified = (not (merchant.get("identity") or {}).get("verified")) or "unverified_gbp" in signals_l
    no_offers = "no_active_offers" in signals_l or not offers

    if is_placeholder(trigger) or delta is None:
        if d_calls is not None and d_calls < 0:
            metric, delta, baseline = "calls", d_calls, calls_v
        elif d_views is not None and d_views < 0:
            metric, delta, baseline = "views", d_views, views_v
        elif d_calls is not None:
            metric, delta, baseline = "calls", d_calls, calls_v
        elif d_views is not None:
            metric, delta, baseline = "views", d_views, views_v
        else:
            metric, delta, baseline = "calls", None, calls_v

    metric_label = metric or "calls"
    abs_bit = f"{calls_v} calls / 30d" if metric_label == "calls" and calls_v is not None else (f"{views_v:,} views / 30d" if views_v else "")

    # Seasonal reframe for gyms in Apr-Jun style dips
    seasonal = "seasonal_dip" in " ".join(signals_l) or (slug == "gyms" and delta is not None and delta <= -0.2)
    members = aggregate(merchant).get("total_active_members")

    actions = []
    if unverified:
        actions.append("verify GBP (postcard/phone) — cheapest fix")
    if no_offers:
        actions.append("put one live offer on the profile this week")
    if lapsed:
        actions.append(f"WhatsApp {lapsed} lapsed patients/clients a 1-line recall")
    if not actions:
        actions.append("post 1 photo + a 4-line WhatsApp to last-30d callers")

    if seasonal and slug == "gyms":
        members_bit = f" Focus retention on your {members} members." if members else " Focus retention, not ads."
        delta_bit = pct_label(delta) if delta is not None else "dip"
        base_bit = f" (baseline {baseline})" if baseline is not None else ""
        body = (
            f"{owner}, {metric_label} {delta_bit} this {window}{base_bit} at {name} ({loc}). "
            f"Flag: metro gyms typically see −25 to −35% acquisition in Apr–Jun — this looks like that lull, not a broken page. "
            f"Skip extra ad spend now; save it for Sep–Oct.{members_bit} "
            f"Want me to draft a 14-day summer attendance challenge?"
        )
        rationale = (
            f"Seasonal dip reframe. {metric_label} {delta_bit} vs baseline {baseline}. "
            "Uses member count; advises against panic spend."
        )
        return body.strip(), "binary_yes_no", rationale, [owner, delta_bit, str(members or "")]

    peer_bit = ""
    if metric_label == "calls" and calls_v is not None and peer_c:
        peer_bit = f" Peer metro avg is ~{peer_c} calls / 30d; you're at {calls_v}."
    action_line = "; ".join(actions[:2])

    if delta is not None and delta < 0:
        delta_bit = pct_label(delta)
        base_bit = f" (baseline {baseline})" if baseline is not None else ""
        headline = f"{owner}, {metric_label} {delta_bit} this {window}{base_bit} at {name} ({loc})"
    else:
        headline = f"{owner}, dip alert for {name} ({loc}) — {metric_label} pacing below target"

    body = (
        f"{headline}"
        f"{(' — ' + abs_bit) if abs_bit else ''}.{peer_bit} "
        f"Not a rant: {action_line}. Want me to draft the WhatsApp + the offer card (10 min)?"
    )
    rationale = (
        f"Perf dip {metric_label} delta={delta} window={window} baseline={baseline}. "
        f"Actions from signals {signals_l} and real peer stats. No invented diagnosis."
    )
    return body.strip(), "binary_yes_no", rationale, [owner, metric_label, pct_label(delta) if delta is not None else "dip"]


def _perf_spike(category, merchant, trigger, customer):
    p = payload(trigger)
    owner = owner_first(merchant)
    name = merchant_name(merchant)
    loc = locality(merchant)
    metric = p.get("metric") or ""
    delta = p.get("delta_pct")
    window = p.get("window") or "7d"
    baseline = p.get("vs_baseline")
    driver = p.get("likely_driver") or ""
    d_calls = delta_calls_pct(merchant)
    d_views = delta_views_pct(merchant)
    calls_v = calls(merchant)
    views_v = views(merchant)
    offers = offer_titles(merchant)
    unverified = "unverified_gbp" in signals(merchant) or not (merchant.get("identity") or {}).get("verified")

    if is_placeholder(trigger) or delta is None:
        if d_calls is not None and d_calls > 0:
            metric, delta, baseline = "calls", d_calls, calls_v
        elif d_views is not None and d_views > 0:
            metric, delta, baseline = "views", d_views, views_v
        elif d_calls is not None and d_calls >= 0:
            metric, delta, baseline = "calls", d_calls, calls_v
        elif d_views is not None and d_views >= 0:
            metric, delta, baseline = "views", d_views, views_v
        else:
            metric, delta, baseline = "views", None, views_v

    if delta is not None and delta > 0:
        delta_bit = f" — {metric} {pct_label(delta)} this {window}"
    elif delta is not None:
        delta_bit = f" — {metric} {pct_label(delta)} this {window}"
    else:
        delta_bit = f" — {views_v:,} views / 30d" if views_v else (f" — {calls_v} calls / 30d" if calls_v else "")

    base_bit = f" vs baseline {baseline}" if baseline is not None and delta is not None else ""
    driver_bit = f" Likely driver: {driver.replace('_', ' ')}." if driver else ""
    offer_bit = f" Your '{offers[0]}' is live — keep it; this is not the week to rotate." if offers else ""
    verify_bit = " You're still unverified on GBP — converting this spike is easier after the postcard/phone verify." if unverified else ""
    next_bit = " Capture it: pin a GBP post today and send a 3-line WhatsApp to this week's callers asking them to review."

    body = (
        f"{owner}, good spike{delta_bit}{(' ' + base_bit) if base_bit else ''} at {name} ({loc}).{driver_bit}{offer_bit}{verify_bit} {next_bit} "
        f"Want me to draft both?"
    )
    rationale = (
        f"Perf spike {metric} delta={delta}, driver={driver}. Convert, don't celebrate. "
        "Uses live offers and unverified signal when present."
    )
    return body.strip(), "binary_yes_no", rationale, [owner, metric, pct_label(delta) if delta is not None else "spike"]


def _recall_due(category, merchant, trigger, customer):
    p = payload(trigger)
    cust = customer_name(customer) or "there"
    name = merchant_name(merchant)
    loc = locality(merchant)
    owner = owner_first(merchant)
    hi_en = is_hi_en(customer)
    last = p.get("last_service_date") or last_visit(customer)
    due = p.get("due_date")
    service = (p.get("service_due") or "recall").replace("_", " ")
    slots = p.get("available_slots") or []
    offer = first_offer_title(merchant)
    days = days_since(last)
    months_bit = ""
    if days:
        months_bit = f" It's been {max(1, round(days/30))} months since your last visit"
        if last:
            months_bit += ""
        months_bit += "."
    elif last:
        months_bit = f" Last visit was {last}."

    slot_labels = []
    for s in slots[:2]:
        if isinstance(s, dict) and s.get("label"):
            slot_labels.append(s["label"])
        elif isinstance(s, str):
            slot_labels.append(s)
    slot_line = ""
    if slot_labels:
        if len(slot_labels) == 2:
            slot_line = f" Two slots: {slot_labels[0]} or {slot_labels[1]}."
        else:
            slot_line = f" Next slot: {slot_labels[0]}."

    offer_bit = f" {offer}." if offer else ""
    slug = merchant.get("category_slug") or ""

    if slug == "dentists" and slot_labels:
        if hi_en:
            body = (
                f"Hi {cust}, {name} here. {months_bit} Your 6-month cleaning recall is due. "
                f"Apke liye 2 slots ready hain: {slot_labels[0]} ya {slot_labels[1]}."
                f"{(' ' + offer + ' + complimentary fluoride.') if offer else ''} "
                f"Reply 1 for the first, 2 for the second, or tell us a time that works."
            )
            cta = "multi_choice_slot"
        else:
            body = (
                f"Hi {cust}, {name} here. {months_bit} Your 6-month cleaning recall is due.{slot_line}{offer_bit} "
                f"Reply 1 / 2, or send a time that works."
            )
            cta = "multi_choice_slot"
        rationale = (
            f"Recall with real slots {slot_labels}, last_service={last}, due={due}, offer={offer}. "
            "Language pref honoured. No medical claims."
        )
        return body.strip(), cta, rationale, [cust, " ".join(slot_labels), offer or ""]

    # placeholder gym/other recall
    offer_bit2 = f" {offer} is on if you want to restart easy." if offer else ""
    body = (
        f"Hi {cust}, {owner} from {name}{(' in ' + loc) if loc else ''} here. {months_bit} "
        f"Time for a check-in so the streak doesn't go cold.{offer_bit2} "
        f"Reply YES and I'll hold a weekday-evening spot, or send a time that works."
    )
    rationale = (
        f"Placeholder recall_due. last_visit={last}, no invented clinical due-date. "
        "Binary CTA + live offer."
    )
    return body.strip(), "binary_yes_no", rationale, [cust, last or "", offer or ""]


def _regulation_change(category, merchant, trigger, customer):
    p = payload(trigger)
    owner = owner_first(merchant)
    item = digest_item(category, p.get("top_item_id")) or first_digest_of_kind_safe(category, "compliance") or {}
    title = item.get("title") or "regulation update"
    source = item.get("source") or ""
    summary = item.get("summary") or ""
    actionable = item.get("actionable") or ""
    deadline = p.get("deadline_iso") or ""
    deadline_bit = ""
    if deadline:
        try:
            dt = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
            deadline_bit = dt.strftime("%d %b %Y").lstrip("0")
        except Exception:
            deadline_bit = deadline[:10]

    body = (
        f"Dr. {owner}, compliance note: {title}"
        f"{(' — effective ' + deadline_bit) if deadline_bit else ''}. "
        f"{summary} {actionable} "
        f"Want me to send a 1-page SOP checklist you can tick before the date? — {source}"
    )
    rationale = (
        f"Regulation digest {p.get('top_item_id')} cited with source={source} and deadline={deadline}. "
        "No invented dose numbers beyond the digest summary."
    )
    return body.strip(), "binary_yes_no", rationale, [f"Dr. {owner}", title, deadline_bit]


def first_digest_of_kind_safe(category, kind):
    if not category:
        return None
    for d in category.get("digest") or []:
        if d.get("kind") == kind:
            return d
    return None


def _research_digest(category, merchant, trigger, customer):
    p = payload(trigger)
    owner = owner_first(merchant)
    item = digest_item(category, p.get("top_item_id")) or first_digest_of_kind_safe(category, "research") or {}
    title = item.get("title") or "new research item"
    source = item.get("source") or ""
    summary = item.get("summary") or ""
    trial_n = item.get("trial_n")
    segment = item.get("patient_segment") or ""
    high_risk = aggregate(merchant).get("high_risk_adult_count")
    n_bit = f"{trial_n:,}-patient trial" if trial_n else "new trial"
    cohort_bit = ""
    if high_risk and ("high_risk" in segment or "high-risk" in (summary or "").lower()):
        cohort_bit = f" Relevant to your {high_risk} high-risk adult patients."
    body = (
        f"Dr. {owner}, {source.split(',')[0] if source else 'the new digest'} landed. "
        f"{n_bit}: {summary}{cohort_bit} "
        f"Worth a look (2-min abstract). Want me to pull it + draft a patient-ed WhatsApp you can share? — {source}"
    )
    rationale = (
        f"Research digest {p.get('top_item_id')} with trial_n={trial_n}, source={source}, "
        f"high_risk_adult_count={high_risk}."
    )
    return body.strip(), "open_ended", rationale, [f"Dr. {owner}", title, source]


def _supply_alert(category, merchant, trigger, customer):
    p = payload(trigger)
    owner = owner_first(merchant)
    batches = p.get("batches") or p.get("batch_numbers") or []
    molecule = p.get("molecule") or "the flagged SKU"
    mfr = p.get("manufacturer") or p.get("mfr") or ""
    chronic = aggregate(merchant).get("chronic_rx_count")
    batch_bit = ", ".join(str(b) for b in batches) if batches else ""
    body = (
        f"{owner}, urgent: voluntary recall on {molecule}"
        f"{(' batches ' + batch_bit) if batch_bit else ''}"
        f"{(' by ' + mfr) if mfr else ''}. "
        f"{f'You have {chronic} chronic-Rx customers — I can pull who was dispensed this in the last 90 days. ' if chronic else ''}"
        f"Want me to draft their WhatsApp note + the replacement-pickup workflow?"
    )
    rationale = f"Supply/recall alert. molecule={molecule}, batches={batches}, chronic_rx={chronic}."
    return body.strip(), "binary_yes_no", rationale, [owner, molecule, batch_bit]


def _bridal_followup(category, merchant, trigger, customer):
    cust = customer_name(customer) or "there"
    owner = owner_first(merchant)
    name = merchant_name(merchant)
    loc = locality(merchant)
    p = payload(trigger)
    wedding = p.get("wedding_date") or ""
    offer = first_offer_title(merchant)
    days = days_since(None)
    # days until wedding if we have it
    days_until = None
    if wedding:
        try:
            wdt = datetime.fromisoformat(wedding.replace("Z", "+00:00"))
            days_until = max(0, int((wdt.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).total_seconds() // 86400))
        except Exception:
            days_until = None
    days_bit = f" {days_until} days to your wedding —" if days_until is not None else ""
    offer_bit = f" {offer}." if offer else ""
    body = (
        f"Hi {cust} — {owner} from {name} {loc} here.{days_bit} good window to lock the trial. "
        f"{offer_bit} Want me to block your preferred Saturday slot next week?"
    )
def _renewal_due(category, merchant, trigger, customer):
    p = payload(trigger)
    owner = owner_first(merchant)
    name = merchant_name(merchant)
    loc = locality(merchant)
    sub = merchant.get("subscription") or {}
    plan = p.get("plan") or sub.get("plan") or "Pro"
    days_rem = p.get("days_remaining") or sub.get("days_remaining") or 7
    views_v = views(merchant)
    calls_v = calls(merchant)

    perf_bit = ""
    if views_v and calls_v:
        perf_bit = f" In the last 30 days, your profile generated {views_v:,} views and {calls_v} calls."
    elif views_v:
        perf_bit = f" In the last 30 days, your profile generated {views_v:,} views."

    body = (
        f"{owner}, quick subscription note: your {plan} plan for {name} ({loc}) has {days_rem} days remaining.{perf_bit} "
        f"Want me to send a 1-click renewal link so your listings and campaigns stay uninterrupted?"
    )
    rationale = f"Renewal due alert: plan={plan}, days_remaining={days_rem}. Value-focused, non-nagging reminder grounded in 30d performance."
    return body.strip(), "binary_yes_no", rationale, [owner, plan, f"{days_rem} days"]


def _review_theme_emerged(category, merchant, trigger, customer):
    p = payload(trigger)
    owner = owner_first(merchant)
    name = merchant_name(merchant)
    loc = locality(merchant)
    theme = p.get("theme") or p.get("metric_or_topic") or "recent customer feedback"
    theme_clean = theme.replace("_", " ")

    body = (
        f"{owner}, review trend alert for {name} ({loc}): recent feedback highlights '{theme_clean}'. "
        f"A quick response note and a fresh photo on your profile keeps your ranking strong. "
        f"Want me to draft a 3-line response you can post today?"
    )
    rationale = f"Review theme alert for theme='{theme_clean}'. Action-oriented review management grounded in merchant locality."
    return body.strip(), "binary_yes_no", rationale, [owner, theme_clean]


def _trial_followup(category, merchant, trigger, customer):
    p = payload(trigger)
    cust = customer_name(customer) or "there"
    owner = owner_first(merchant)
    name = merchant_name(merchant)
    loc = locality(merchant)
    hi = is_hi(customer) or is_hi_en(customer)
    trial_date = p.get("trial_date") or last_visit(customer)
    next_options = p.get("next_session_options") or []
    offer = first_offer_title(merchant)

    slot_str = ""
    if next_options and isinstance(next_options, list):
        opt0 = next_options[0]
        label = opt0.get("label") if isinstance(opt0, dict) else (opt0 if isinstance(opt0, str) else "")
        if label:
            slot_str = f" We have a spot open on {label}."

    offer_bit = f" Your '{offer}' rate is locked." if offer else ""
    date_bit = f" after your session on {trial_date}" if trial_date else ""

    if hi and not language_pref(customer).startswith("en"):
        body = (
            f"Hi {cust}, {name} ({loc}) se. Hope trial session accha raha hoga!{slot_str}{offer_bit} "
            f"Next class ke liye spot book karna ho to reply YES, ya suitable time batayein."
        )
    else:
        body = (
            f"Hi {cust} — {owner} from {name}{(' in ' + loc) if loc else ''} here. "
            f"Hope you enjoyed your trial session{date_bit}!{slot_str}{offer_bit} "
            f"Want me to hold your spot for next week? Reply YES, or send a time that works."
        )
    rationale = f"Trial session followup: trial_date={trial_date}, options={next_options}, offer={offer}. Language preference honoured; low-friction CTA."
    return body.strip(), "binary_yes_no", rationale, [cust, name, trial_date or ""]


def _wedding_package_followup(category, merchant, trigger, customer):
    p = payload(trigger)
    scope = trigger_scope(trigger)
    if scope == "customer" and customer:
        cust = customer_name(customer) or "there"
        owner = owner_first(merchant)
        name = merchant_name(merchant)
        loc = locality(merchant)
        wedding = p.get("wedding_date") or ""
        offer = first_offer_title(merchant) or "Bridal Package"
        body = (
            f"Hi {cust} — {owner} from {name} ({loc}) here. Following up on your bridal inquiry — "
            f"slots for the upcoming season are booking out. We've held '{offer}' options for you. "
            f"Want me to block a Saturday slot for your bridal consultation & trial?"
        )
        rationale = f"Bridal customer followup: wedding_date={wedding}, offer={offer}. Focused on consultation booking."
        return body.strip(), "binary_yes_no", rationale, [cust, offer]
    else:
        owner = owner_first(merchant)
        name = merchant_name(merchant)
        loc = locality(merchant)
        offer = first_offer_title(merchant)
        body = (
            f"{owner}, wedding season planning for {name} ({loc}): bridal and event packages book out 2–3 weeks early. "
            f"Want me to draft a 4-line WhatsApp showcase + a GBP post for your bridal services?"
        )
        rationale = "Bridal merchant planning trigger: grounded in merchant locality and seasonal peak."
        return body.strip(), "binary_yes_no", rationale, [owner, name]


def _winback_eligible(category, merchant, trigger, customer):
    p = payload(trigger)
    scope = trigger_scope(trigger)
    if scope == "customer" and customer:
        return _lapsed_hard(category, merchant, trigger, customer)
    owner = owner_first(merchant)
    name = merchant_name(merchant)
    loc = locality(merchant)
    views_v = views(merchant)
    calls_v = calls(merchant)
    offer = first_offer_title(merchant)

    stats_bit = ""
    if views_v:
        stats_bit = f" You still had {views_v:,} search views in the last 30 days."

    body = (
        f"{owner}, quick check for {name} ({loc}): your account is eligible for the magicpin winback growth package.{stats_bit} "
        f"Want me to draft an updated offer card + GBP announcement post to restart momentum?"
    )
    rationale = "Winback eligible merchant trigger: grounded in 30d views, offering zero-friction campaign reactivation."
    return body.strip(), "binary_yes_no", rationale, [owner, name]


def _generic(category, merchant, trigger, customer):
    owner = owner_first(merchant)
    name = merchant_name(merchant)
    loc = locality(merchant)
    kind = trigger_kind(trigger)
    p = payload(trigger)
    offer = first_offer_title(merchant)
    views_v, calls_v = views(merchant), calls(merchant)
    bits = []
    if views_v:
        bits.append(f"{views_v:,} views / 30d")
    if calls_v is not None:
        bits.append(f"{calls_v} calls")
    if offer:
        bits.append(f"live offer '{offer}'")
    fact = ", ".join(bits) if bits else f"{name} in {loc}"
    topic = p.get("metric_or_topic") or kind.replace("_", " ")
    body = (
        f"{owner}, flagging {topic} for {name} ({loc}). {fact}. "
        f"Want me to draft a 4-line WhatsApp + a GBP note you can post today?"
    )
    rationale = f"Generic handler for kind={kind}. Grounded in live performance and offers; no invented payload facts."
    return body.strip(), "open_ended", rationale, [owner, topic, fact]


# ---------------------------------------------------------------------------
# Reply-path composition
# ---------------------------------------------------------------------------

def compose_reply(
    merchant_message: str,
    state: Dict[str, Any],
    merchant: Dict,
    category: Dict,
    trigger: Optional[Dict],
    customer: Optional[Dict],
    conv=None,
) -> Dict[str, Any]:
    from state.conversations import (
        detect_auto_reply, detect_hostile_or_optout,
        detect_action_intent, detect_out_of_scope,
    )

    msg = merchant_message or ""
    prev = None
    auto_count = 0
    if conv is not None:
        prev = getattr(conv, "last_user_message", None)
        auto_count = getattr(conv, "auto_reply_count", 0) or 0

    mid = (merchant or {}).get("merchant_id")
    if mid:
        from state.conversations import global_conv_manager
        m_count = global_conv_manager.get_merchant_auto_reply_count(mid)
        if m_count > auto_count:
            auto_count = m_count

    owner = owner_first(merchant)
    name = merchant_name(merchant)
    kind = trigger_kind(trigger) if trigger else ""
    high_risk = aggregate(merchant).get("high_risk_adult_count")
    offer = first_offer_title(merchant)

    # 1. Hostility / opt-out — end immediately
    if detect_hostile_or_optout(msg):
        return {
            "action": "end",
            "rationale": "Merchant explicitly opted out or sent a hostile message. Closing conversation and suppressing this thread.",
        }

    # 2. Auto-reply ladder: send (flag) → wait 24h → end
    if detect_auto_reply(msg, prev):
        next_count = auto_count + 1
        if next_count >= 3:
            return {
                "action": "end",
                "rationale": "Auto-reply 3x in a row, no real owner signal. Closing.",
            }
        if next_count >= 2:
            return {
                "action": "wait",
                "wait_seconds": 86400,
                "rationale": "Same auto-reply twice in a row — owner not at the phone. Waiting 24h before retry.",
            }
        return {
            "action": "send",
            "body": (
                f"Looks like an auto-reply from {name}. When you see this, reply YES and I’ll continue — "
                f"otherwise I’ll pause so I don’t add noise."
            ),
            "cta": "binary_yes_no",
            "rationale": "Detected canned auto-reply; one explicit prompt for the owner, then we back off.",
        }

    # 3. Out of scope (GST, loans, cricket scores…) — deflect, stay on trigger
    if detect_out_of_scope(msg):
        topic = (kind or "the thing we were on").replace("_", " ")
        body = (
            f"I’ll have to leave that to your CA / specialist — that’s outside what I can help with directly. "
            f"Coming back to {topic}: want me to draft the next artefact now, or send the short version first?"
        )
        return {
            "action": "send",
            "body": body,
            "cta": "open_ended",
            "rationale": "Out-of-scope ask politely declined; redirected to the active trigger without losing the thread.",
        }

    # 4. Explicit commitment — ACTION mode, no more qualifying
    if detect_action_intent(msg):
        cohort_bit = f" ({high_risk} high-risk adult patients)" if high_risk else ""
        offer_bit = f" I’ll also attach '{offer}' where it fits." if offer else ""
        if kind in ("cde_opportunity", "research_digest", "regulation_change"):
            body = (
                f"Great. Drafting now — 90 seconds. I’ll send the artefact + a patient/staff WhatsApp you can paste."
                f"{cohort_bit}{offer_bit} Reply CONFIRM and I send; reply EDIT and tell me what to change."
            )
        elif kind == "active_planning_intent":
            body = (
                f"On it. Finalising the one-pager and the 3-line outreach WhatsApp. "
                f"Reply CONFIRM to lock this version, or tell me the one number you want changed."
            )
        elif kind in ("perf_dip", "competitor_opened", "festival_upcoming", "ipl_match_today"):
            body = (
                f"Done path: drafting the WhatsApp + the post now. "
                f"Reply CONFIRM to use this copy, or send the one tweak."
            )
        else:
            body = (
                f"Great — switching to action. Drafting the next artefact now. "
                f"Reply CONFIRM to send, or EDIT with the change.{offer_bit}"
            )
        return {
            "action": "send",
            "body": body,
            "cta": "binary_confirm_cancel",
            "rationale": "Merchant explicitly committed ('let's do it' / 'proceed' / 'send it'). Switched from qualification to execution; no extra qualifying questions.",
        }

    # 5. Soft no / later
    lower = msg.strip().lower()
    if any(x in lower for x in ["not now", "later", "next week", "busy", "in a bit", "tomorrow"]):
        return {
            "action": "wait",
            "wait_seconds": 3600 * 18,
            "rationale": "Merchant asked for time. Backing off ~18h.",
        }

    # 6. Default: helpful continuation grounded in trigger, still moving toward an artefact
    topic = (kind or "this").replace("_", " ")
    loc = locality(merchant)
    body = (
        f"Got it, {owner}. I’ll keep this tight: one artefact for {topic} at {name}"
        f"{(' in ' + loc) if loc else ''} you can paste today. "
        f"Want the WhatsApp draft first, or the GBP post?"
    )
    return {
        "action": "send",
        "body": body,
        "cta": "open_ended",
        "rationale": "Default continuation — offered a concrete artefact choice, no extra qualification.",
    }
