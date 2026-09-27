from state.store import ContextStore


def test_context_push_and_retrieval():
    store = ContextStore()
    payload = {"slug": "dentists", "voice": {"tone": "peer_clinical"}}
    accepted, ack_id, stored_at, version = store.push_context("category", "dentists", 1, payload)
    
    assert accepted is True
    assert ack_id == "ack_dentists_v1"
    assert version == 1
    assert store.get_category("dentists") == payload


def test_context_idempotency_same_version():
    store = ContextStore()
    payload = {"slug": "salons", "voice": {"tone": "warm_practical"}}
    
    # First push
    accepted1, ack1, _, v1 = store.push_context("category", "salons", 1, payload)
    assert accepted1 is True
    assert v1 == 1

    # Second push with identical version (idempotent no-op)
    accepted2, ack2, _, v2 = store.push_context("category", "salons", 1, payload)
    assert accepted2 is True
    assert ack2 == "ack_salons_v1"
    assert v2 == 1


def test_context_version_replacement_higher_version():
    store = ContextStore()
    payload_v1 = {"merchant_id": "m_001", "performance": {"views": 100}}
    payload_v2 = {"merchant_id": "m_001", "performance": {"views": 250}}

    store.push_context("merchant", "m_001", 1, payload_v1)
    accepted, ack_id, _, v = store.push_context("merchant", "m_001", 2, payload_v2)

    assert accepted is True
    assert ack_id == "ack_m_001_v2"
    assert v == 2
    assert store.get_merchant("m_001")["performance"]["views"] == 250


def test_context_stale_rejection_lower_version():
    store = ContextStore()
    payload_v3 = {"merchant_id": "m_001", "version": 3}
    payload_v2 = {"merchant_id": "m_001", "version": 2}

    store.push_context("merchant", "m_001", 3, payload_v3)
    accepted, reason, _, current_ver = store.push_context("merchant", "m_001", 2, payload_v2)

    assert accepted is False
    assert reason == "stale_version"
    assert current_ver == 3


def test_invalid_scope_rejection():
    store = ContextStore()
    accepted, reason, _, _ = store.push_context("invalid_scope", "test_id", 1, {})
    assert accepted is False
    assert "invalid_scope" in reason
