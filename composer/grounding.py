"""
Fact extraction and anti-hallucination helpers.

Every number, date, price, discount, locality, owner name, and citation
in a composed message MUST come from one of the four contexts or from
a clearly labelled derived calculation on those facts.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


def _d(obj: Optional[Dict], *keys, default=None):
    cur = obj or {}
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


def owner_first(merchant: Dict) -> str:
    return (_d(merchant, "identity", "owner_first_name") or "there").strip()


def merchant_name(merchant: Dict) -> str:
    return (_d(merchant, "identity", "name") or "your business").strip()


def locality(merchant: Dict) -> str:
    return (_d(merchant, "identity", "locality") or "").strip()


def city(merchant: Dict) -> str:
    return (_d(merchant, "identity", "city") or "").strip()


def locality_city(merchant: Dict) -> str:
    loc, c = locality(merchant), city(merchant)
    if loc and c:
        return f"{loc}, {c}"
    return loc or c or ""


def category_slug(merchant: Dict, category: Optional[Dict] = None) -> str:
    return (merchant or {}).get("category_slug") or (category or {}).get("slug") or ""


def languages(merchant: Dict) -> List[str]:
    return list(_d(merchant, "identity", "languages") or [])


def verified(merchant: Dict) -> bool:
    return bool(_d(merchant, "identity", "verified"))


def customer_name(customer: Optional[Dict]) -> str:
    if not customer:
        return ""
    return (_d(customer, "identity", "name") or "").strip()


def language_pref(customer: Optional[Dict]) -> str:
    if not customer:
        return "en"
    return (_d(customer, "identity", "language_pref") or "en").strip().lower()


def is_hi(customer: Optional[Dict]) -> bool:
    pref = language_pref(customer)
    return pref in ("hi", "hindi") or pref.startswith("hi")


def is_hi_en(customer: Optional[Dict]) -> bool:
    pref = language_pref(customer)
    return "mix" in pref or pref in ("hi-en", "hi_en", "hinglish")


def customer_state(customer: Optional[Dict]) -> str:
    if not customer:
        return ""
    return (customer.get("state") or "").strip()


def last_visit(customer: Optional[Dict]) -> Optional[str]:
    return _d(customer, "relationship", "last_visit")


def visits_total(customer: Optional[Dict]) -> Optional[int]:
    v = _d(customer, "relationship", "visits_total")
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def lifetime_value(customer: Optional[Dict]) -> Optional[int]:
    v = _d(customer, "relationship", "lifetime_value")
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def preferred_slots(customer: Optional[Dict]) -> str:
    return (_d(customer, "preferences", "preferred_slots") or "").strip()


def channel(customer: Optional[Dict]) -> str:
    return (_d(customer, "preferences", "channel") or "whatsapp").strip()


def views(merchant: Dict) -> Optional[int]:
    v = _d(merchant, "performance", "views")
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def calls(merchant: Dict) -> Optional[int]:
    v = _d(merchant, "performance", "calls")
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def ctr(merchant: Dict) -> Optional[float]:
    v = _d(merchant, "performance", "ctr")
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def delta_views_pct(merchant: Dict) -> Optional[float]:
    v = _d(merchant, "performance", "delta_7d", "views_pct")
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def delta_calls_pct(merchant: Dict) -> Optional[float]:
    v = _d(merchant, "performance", "delta_7d", "calls_pct")
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def pct_label(value: Optional[float], signed: bool = True) -> str:
    """Format a fraction like -0.30 as '-30%'."""
    if value is None:
        return ""
    n = int(round(value * 100))
    if signed and n > 0:
        return f"+{n}%"
    return f"{n}%"


def ctr_label(value: Optional[float]) -> str:
    if value is None:
        return ""
    return f"{value * 100:.1f}%"


def active_offers(merchant: Dict) -> List[Dict]:
    offers = merchant.get("offers") or []
    out = []
    for o in offers:
        if not isinstance(o, dict):
            continue
        status = (o.get("status") or "active").lower()
        if status in ("active", "live", ""):
            out.append(o)
    return out


def offer_titles(merchant: Dict) -> List[str]:
    return [o.get("title") for o in active_offers(merchant) if o.get("title")]


def first_offer_title(merchant: Dict) -> Optional[str]:
    titles = offer_titles(merchant)
    return titles[0] if titles else None


def catalog_offer(category: Optional[Dict], title_contains: str) -> Optional[Dict]:
    if not category:
        return None
    needle = title_contains.lower()
    for o in category.get("offer_catalog") or []:
        t = (o.get("title") or "").lower()
        if needle in t:
            return o
    return None


def peer_stats(category: Optional[Dict]) -> Dict:
    return (category or {}).get("peer_stats") or {}


def peer_ctr(category: Optional[Dict]) -> Optional[float]:
    v = peer_stats(category).get("avg_ctr")
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def peer_calls(category: Optional[Dict]) -> Optional[int]:
    v = peer_stats(category).get("avg_calls_30d")
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def peer_views(category: Optional[Dict]) -> Optional[int]:
    v = peer_stats(category).get("avg_views_30d")
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def digest_item(category: Optional[Dict], item_id: Optional[str]) -> Optional[Dict]:
    if not category or not item_id:
        return None
    for d in category.get("digest") or []:
        if d.get("id") == item_id:
            return d
    return None


def first_digest_of_kind(category: Optional[Dict], kind: str) -> Optional[Dict]:
    if not category:
        return None
    for d in category.get("digest") or []:
        if d.get("kind") == kind:
            return d
    return None


def seasonal_beats(category: Optional[Dict]) -> List[Dict]:
    return list((category or {}).get("seasonal_beats") or [])


def trend_signals(category: Optional[Dict]) -> List[Dict]:
    return list((category or {}).get("trend_signals") or [])


def aggregate(merchant: Dict) -> Dict:
    return merchant.get("customer_aggregate") or {}


def signals(merchant: Dict) -> List[str]:
    return list(merchant.get("signals") or [])


def payload(trigger: Dict) -> Dict:
    return trigger.get("payload") or {}


def is_placeholder(trigger: Dict) -> bool:
    p = payload(trigger)
    return bool(p.get("placeholder"))


def trigger_kind(trigger: Dict) -> str:
    return (trigger.get("kind") or "").strip()


def trigger_scope(trigger: Dict) -> str:
    return (trigger.get("scope") or "merchant").strip()


def suppression_key(trigger: Dict) -> Optional[str]:
    return trigger.get("suppression_key")


def days_since(iso_date: Optional[str], now: Optional[datetime] = None) -> Optional[int]:
    if not iso_date:
        return None
    try:
        raw = iso_date.replace("Z", "+00:00")
        # date-only
        if "T" not in raw and len(raw) <= 10:
            dt = datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        now_dt = now or datetime.now(timezone.utc)
        if now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=timezone.utc)
        return max(0, int((now_dt - dt).total_seconds() // 86400))
    except Exception:
        return None


def months_since(iso_date: Optional[str], now: Optional[datetime] = None) -> Optional[int]:
    d = days_since(iso_date, now)
    if d is None:
        return None
    return max(1, round(d / 30))


def format_inr(n: Optional[int]) -> str:
    if n is None:
        return ""
    s = f"{int(n):,}"
    # Indian grouping for 5+ digits: 1,420 vs 14,20 — keep simple Western for small,
    # Indian for larger
    if n >= 100000:
        # 1,00,000 style
        s = str(int(n))
        last3 = s[-3:]
        rest = s[:-3]
        parts = []
        while len(rest) > 2:
            parts.append(rest[-2:])
            rest = rest[:-2]
        if rest:
            parts.append(rest)
        s = ",".join(reversed(parts)) + "," + last3
    return f"₹{s}"


def extract_price_from_title(title: str) -> Optional[str]:
    m = re.search(r"₹\s*[\d,]+", title or "")
    return m.group(0).replace(" ", "") if m else None


def taboo_list(category: Optional[Dict]) -> List[str]:
    return list(_d(category, "voice", "vocab_taboo") or [])


def tone(category: Optional[Dict]) -> str:
    return (_d(category, "voice", "tone") or "").strip()


def contains_taboo(text: str, category: Optional[Dict]) -> List[str]:
    found = []
    lower = (text or "").lower()
    for t in taboo_list(category):
        # skip parenthetical notes
        core = t.split("(")[0].strip().lower()
        if core and core in lower:
            found.append(t)
    return found


def strip_taboos(text: str, category: Optional[Dict]) -> str:
    out = text
    replacements = {
        "guaranteed": "typically",
        "100% safe": "well-studied",
        "completely cure": "help manage",
        "miracle": "",
        "best in city": "in your locality",
        "guaranteed glow": "noticeable glow",
        "permanent results": "lasting results",
        "instant transformation": "visible change",
        "guaranteed packed house": "stronger covers",
        "miracle marketing": "focused outreach",
        "viral guarantee": "better reach",
        "guaranteed weight loss": "weight-loss support",
        "shred in 7 days": "a structured 4-week plan",
        "miracle transformation": "steady progress",
        "fastest results": "focused results",
        "miracle cure": "standard care",
        "guaranteed result": "expected outcome",
    }
    for bad, good in replacements.items():
        out = re.sub(re.escape(bad), good, out, flags=re.IGNORECASE)
    return re.sub(r"\s{2,}", " ", out).strip()


def conversation_id_for(trigger: Dict, merchant: Dict, customer: Optional[Dict] = None) -> str:
    tid = trigger.get("id") or "trg"
    mid = (merchant or {}).get("merchant_id") or "m"
    cid = (customer or {}).get("customer_id") if customer else None
    if cid:
        return f"conv_{cid}_{tid}"
    return f"conv_{mid}_{tid}"
