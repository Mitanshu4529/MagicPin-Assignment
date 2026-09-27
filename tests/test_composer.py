"""
Test composition: active vs expired offer usage, customer vs merchant send_as, language adaptation, and trigger ranking.
"""
from composer.engine import compose
from composer.decision import rank_triggers_pairs


def test_active_offer_used_and_expired_ignored():
    category = {
        "slug": "dentists",
        "voice": {"tone": "peer_clinical", "vocab_taboo": ["guaranteed"]},
    }
    merchant = {
        "merchant_id": "m_meera",
        "category_slug": "dentists",
        "identity": {"name": "Dr. Meera's Clinic", "owner_first_name": "Meera", "locality": "Lajpat Nagar"},
        "offers": [
            {"id": "o_1", "title": "Dental Cleaning @ ₹299", "status": "active"},
            {"id": "o_2", "title": "Deep Scaling @ ₹999", "status": "expired"},
        ],
    }
    trigger = {
        "id": "trg_recall",
        "scope": "customer",
        "kind": "recall_due",
        "payload": {
            "last_service_date": "2025-11-04",
            "available_slots": [{"label": "Wed 6pm"}, {"label": "Thu 5pm"}],
        },
    }
    customer = {
        "customer_id": "c_priya",
        "identity": {"name": "Priya", "language_pref": "hi-en mix"},
        "relationship": {"last_visit": "2025-11-04"},
        "state": "lapsed_soft",
    }

    action = compose(category, merchant, trigger, customer)

    assert action["send_as"] == "merchant_on_behalf"
    assert "₹299" in action["body"]
    assert "₹999" not in action["body"]  # Expired offer must NOT be present
    assert "Deep Scaling" not in action["body"]
    assert "guaranteed" not in action["body"].lower()


def test_merchant_send_as_vera():
    category = {"slug": "salons", "voice": {"tone": "warm_practical"}}
    merchant = {
        "merchant_id": "m_studio",
        "category_slug": "salons",
        "identity": {"name": "Studio 11", "owner_first_name": "Lakshmi", "locality": "Kapra"},
    }
    trigger = {
        "id": "trg_curious",
        "scope": "merchant",
        "kind": "curious_ask_due",
        "payload": {},
    }

    action = compose(category, merchant, trigger, None)

    assert action["send_as"] == "vera"
    assert "Lakshmi" in action["body"]
    assert action["cta"] == "open_ended"


def test_trigger_ranking_urgency():
    t_low = ({"id": "t1", "urgency": 1, "scope": "merchant"}, {"merchant_id": "m1"}, None)
    t_high = ({"id": "t2", "urgency": 4, "scope": "merchant"}, {"merchant_id": "m1"}, None)
    t_med = ({"id": "t3", "urgency": 2, "scope": "customer"}, {"merchant_id": "m1"}, {"customer_id": "c1"})

    ranked = rank_triggers_pairs([t_low, t_high, t_med])
    assert ranked[0][0]["id"] == "t2"
    assert ranked[1][0]["id"] == "t3"
    assert ranked[2][0]["id"] == "t1"


def test_all_five_categories_voice_and_specifics():
    # 1. Dentist: professional clinical tone, Dr. prefix
    cat_dentist = {"slug": "dentists", "voice": {"tone": "peer_clinical", "vocab_taboo": ["cure", "guaranteed"]}}
    merch_dentist = {
        "merchant_id": "m_d", "category_slug": "dentists",
        "identity": {"name": "Asha Dental", "owner_first_name": "Asha", "locality": "Saket"},
    }
    trig_dentist = {
        "id": "trg_d", "scope": "merchant", "kind": "cde_opportunity",
        "payload": {"credits": 3, "fee": "free"},
    }
    action_d = compose(cat_dentist, merch_dentist, trig_dentist, None)
    assert "Dr. Asha" in action_d["body"]
    assert "credits" in action_d["body"].lower()

    # 2. Salon: warm, trend-oriented
    cat_salon = {"slug": "salons", "voice": {"tone": "warm_practical"}}
    merch_salon = {
        "merchant_id": "m_s", "category_slug": "salons",
        "identity": {"name": "Glow Salon", "owner_first_name": "Pooja", "locality": "Bandra"},
        "offers": [{"id": "o1", "title": "Hair Spa @ ₹499", "status": "active"}],
    }
    trig_salon = {
        "id": "trg_s", "scope": "merchant", "kind": "festival_upcoming",
        "payload": {"festival": "Diwali", "days_until": 15},
    }
    action_s = compose(cat_salon, merch_salon, trig_salon, None)
    assert "Pooja" in action_s["body"]
    assert "Hair Spa @ ₹499" in action_s["body"]

    # 3. Restaurant: operator-to-operator, delivery/dine-in
    cat_rest = {"slug": "restaurants", "voice": {"tone": "operator_peer"}}
    merch_rest = {
        "merchant_id": "m_r", "category_slug": "restaurants",
        "identity": {"name": "Pizza Junction", "owner_first_name": "Rahul", "locality": "Dwarka"},
        "offers": [{"id": "o2", "title": "Buy 1 Get 1 Free", "status": "active"}],
    }
    trig_rest = {
        "id": "trg_r", "scope": "merchant", "kind": "ipl_match_today",
        "payload": {"match": "CSK vs RCB", "venue": "Chepauk", "is_weeknight": False},
    }
    action_r = compose(cat_rest, merch_rest, trig_rest, None)
    assert "Rahul" in action_r["body"]
    assert "CSK vs RCB" in action_r["body"]

    # 4. Gym: habit/retention focused
    cat_gym = {"slug": "gyms", "voice": {"tone": "motivational"}}
    merch_gym = {
        "merchant_id": "m_g", "category_slug": "gyms",
        "identity": {"name": "Fit Studio", "owner_first_name": "Vikram", "locality": "Indiranagar"},
        "customer_aggregate": {"total_active_members": 120},
    }
    trig_gym = {
        "id": "trg_g", "scope": "merchant", "kind": "perf_dip",
        "payload": {"metric": "calls", "delta_pct": -0.25, "window": "7d", "vs_baseline": 20},
    }
    action_g = compose(cat_gym, merch_gym, trig_gym, None)
    assert "Vikram" in action_g["body"]
    assert "120" in action_g["body"]

    # 5. Pharmacy: safety-conscious, utility-first
    cat_pharm = {"slug": "pharmacies", "voice": {"tone": "trustworthy_precise"}}
    merch_pharm = {
        "merchant_id": "m_p", "category_slug": "pharmacies",
        "identity": {"name": "City Medicos", "owner_first_name": "Anil", "locality": "Aliganj"},
        "customer_aggregate": {"chronic_rx_count": 85},
    }
    trig_pharm = {
        "id": "trg_p", "scope": "merchant", "kind": "supply_alert",
        "payload": {"molecule": "Paracetamol 650", "batches": ["B102", "B103"], "mfr": "PharmaCorp"},
    }
    action_p = compose(cat_pharm, merch_pharm, trig_pharm, None)
    assert "Anil" in action_p["body"]
    assert "85" in action_p["body"]
    assert "B102" in action_p["body"]


def test_renewal_and_review_and_trial_handlers():
    # Renewal due
    cat = {"slug": "gyms"}
    merch = {
        "merchant_id": "m1", "category_slug": "gyms",
        "identity": {"name": "Zen Gym", "owner_first_name": "Amit", "locality": "Aundh"},
        "subscription": {"plan": "Growth", "days_remaining": 5},
        "performance": {"views": 1500, "calls": 25},
    }
    trig_ren = {"id": "trg_ren", "scope": "merchant", "kind": "renewal_due", "payload": {}}
    act_ren = compose(cat, merch, trig_ren, None)
    assert "5 days" in act_ren["body"]
    assert "Growth" in act_ren["body"]
    assert "1,500" in act_ren["body"]

    # Review theme emerged
    trig_rev = {"id": "trg_rev", "scope": "merchant", "kind": "review_theme_emerged", "payload": {"theme": "friendly staff"}}
    act_rev = compose(cat, merch, trig_rev, None)
    assert "friendly staff" in act_rev["body"]

    # Trial followup
    cust = {"customer_id": "c1", "identity": {"name": "Simran", "language_pref": "en"}, "relationship": {"last_visit": "2026-04-20"}}
    trig_trial = {
        "id": "trg_trial", "scope": "customer", "kind": "trial_followup",
        "payload": {"trial_date": "2026-04-20", "next_session_options": [{"label": "Sat 10am"}]},
    }
    act_trial = compose(cat, merch, trig_trial, cust)
    assert act_trial["send_as"] == "merchant_on_behalf"
    assert "Simran" in act_trial["body"]
    assert "Sat 10am" in act_trial["body"]


def test_perf_dip_non_negative_delta_phrasing():
    cat = {"slug": "salons"}
    merch = {
        "merchant_id": "m_salon", "category_slug": "salons",
        "identity": {"name": "Style Salon", "owner_first_name": "Maya", "locality": "Viman Nagar"},
        "performance": {"views": 2500, "calls": 10, "delta_7d": {"views_pct": 0.08, "calls_pct": 0.0}},
    }
    # Placeholder trigger with no negative delta
    trig = {"id": "trg_dip", "scope": "merchant", "kind": "perf_dip", "payload": {"placeholder": True}}
    act = compose(cat, merch, trig, None)
    assert "+8%" not in act["body"]  # Must NOT claim a positive number as a performance dip!
    assert "dip alert" in act["body"].lower() or "calls" in act["body"].lower()
