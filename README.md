# Vera Message Engine

A production-ready, competition-tested 4-context composition engine and conversational assistant for the **magicpin AI Challenge** ("Build a Merchant AI Assistant — Vera").

---

## Architecture

```
                        ┌─────────────────────────────────────────┐
                        │               bot.py (FastAPI)          │
                        │  GET  /v1/healthz                       │
                        │  GET  /v1/metadata                      │
                        │  POST /v1/context ──→ state/store.py   │
                        │  POST /v1/tick    ──→ composer/engine   │
                        │  POST /v1/reply   ──→ state/convs +     │
                        │                       composer/engine   │
                        │  POST /v1/teardown                      │
                        └─────────────────────────────────────────┘
                                      │
            ┌────────────────────────────────────────────────┐
            │         4-Context State (in-memory)            │
            │  CategoryContext  MerchantContext               │
            │  CustomerContext  TriggerContext                 │
            │  ContextStore (versioned, thread-safe, dual-idx)│
            └────────────────────────────────────────────────┘
                                      │
            ┌────────────────────────────────────────────────┐
            │         composer/                              │
            │  grounding.py  – fact extraction, taboo check  │
            │  decision.py   – should_act, rank, cta/template│
            │  engine.py     – 26-kind body composer + reply │
            └────────────────────────────────────────────────┘
                                      │
            ┌────────────────────────────────────────────────┐
            │         llm/client.py  (optional polish)       │
            │  OpenAI │ Anthropic │ Gemini │ DeepSeek        │
            │  Groq   │ Ollama    │ OpenRouter               │
            └────────────────────────────────────────────────┘
```

---

## Design Principles & Capabilities

### 1. Strict Grounding & Anti-Hallucination
Every claim, metric, percentage, date, price, locality, owner name, and citation in a composed message comes **directly from one of the four contexts** or deterministic calculations on those facts. No hallucinated competitors, invented clinical statistics, or fabricated batch numbers.

Key guarantees:
- `is_placeholder(trigger)` flags placeholder payloads; handlers never invent specific metric values.
- `strip_taboos(text, category)` removes vertical-forbidden vocabulary (e.g. "guaranteed", "miracle", "100% safe") before the body is returned.
- Offers cited in messages are `active_offers(merchant)` only; expired or paused offers are excluded.
- Performance dip and spike handlers strictly validate deltas so positive numbers are never presented as drops, and vice versa.

### 2. 4-Context Vertical Composition
`compose_action()` receives `(category, merchant, trigger, customer)` and dispatches to 26 specialized kind handlers covering all 5 verticals:
- **Dentists**: Clinical, peer-to-peer, technical vocabulary permitted, "Dr." prefix required, clinical recall intervals.
- **Salons**: Warm, professional, trend & occasion-oriented, service+price anchors (e.g. "Haircut @ ₹99").
- **Restaurants**: Timely, operator-to-operator, delivery vs. dine-in split awareness, local demand / event awareness.
- **Gyms**: Motivational, habit & streak retention, member count grounding.
- **Pharmacies**: Utility-first, trustworthy, safety-conscious, chronic Rx vs. seasonal OTC clarity.

### 3. Multi-Turn Conversation State Machine
`state/conversations.py` and `composer/engine.py` apply an intelligent decision ladder:
1. **Hostility / Opt-out** → `action: "end"` immediately; permanently suppresses conversation and merchant thread.
2. **Auto-reply detection**:
   - Turn 1: `action: "send"` (politely flag for owner)
   - Turn 2: `action: "wait"`, `wait_seconds: 86400`
   - Turn 3+: `action: "end"` (graceful exit)
3. **Out of Scope** (GST, tax, loans, scores) → `action: "send"` (politely deflect, redirect to active trigger)
4. **Explicit Commitment** ("let's do it", "proceed", "send it") → `action: "send"` in ACTION mode immediately (no re-qualifying)
5. **Soft No / Later** → `action: "wait"`, `wait_seconds: 64800`
6. **Default continuation** → `action: "send"` with concrete low-friction next step

### 4. Anti-spam / Suppression / Restraint
- `ConversationManager.suppress(key)` prevents re-processing the same trigger once acted on.
- Expired triggers (`now >= expires_at`) are skipped.
- Customer-scoped triggers without customer consent or without loaded customer are safely skipped.
- `/v1/tick` enforces the official maximum limit of 20 actions per tick.

---

## Running Locally

```bash
# 1. Create and activate virtual environment
python -m venv venv
venv\Scripts\activate  # Windows (or source venv/bin/activate on Linux)

# 2. Install dependencies
pip install -r requirements.txt

# 3. Start server
python bot.py
```

Optional LLM configuration:
```bash
set LLM_PROVIDER=openai
set OPENAI_API_KEY=sk-...
python bot.py
```

---

## Running Automated Tests

```bash
# Run full automated test suite (26 tests)
python tests/run_tests.py

# Run offline smoke composition of all 30 test pairs
python _smoke.py

# Run HTTP endpoint integration smoke
python _http_smoke.py
```

---

## Running Official Judge Simulator

```bash
# 1. Start bot server in one terminal
python bot.py

# 2. In another terminal, run judge simulator:
python judge_simulator.py
```

---

## Deployment (Docker)

```bash
# Build Docker image
docker build -t vera-bot .

# Run Docker container
docker run -p 8080:8080 -e PORT=8080 vera-bot
```

---

## Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/healthz` | Liveness probe; returns uptime and context counts |
| `GET` | `/v1/metadata` | Bot metadata, team information, and approach description |
| `POST` | `/v1/context` | Push CategoryContext, MerchantContext, CustomerContext, or TriggerContext |
| `POST` | `/v1/tick` | Periodic wake-up; evaluates active triggers and returns up to 20 actions |
| `POST` | `/v1/reply` | Multi-turn conversation handler (actions: `send`, `wait`, `end`) |
| `POST` | `/v1/teardown` | Optional endpoint to clear in-memory state |

### Context Versioning Rules
- **Same version re-pushed**: `200 OK` (idempotent no-op)
- **Higher version pushed**: `200 OK` (atomic replacement)
- **Lower/stale version pushed**: `409 Conflict` (`{"accepted": false, "reason": "stale_version", "current_version": N}`)
- **Malformed scope**: `400 Bad Request` (`{"accepted": false, "reason": "invalid_scope"}`)files
submission.jsonl         30 composed actions for the canonical test set
requirements.txt         Python dependencies
```

---

## Running the Judge Simulator

```bash
# Edit details/judge_simulator.py — set BOT_URL, LLM_PROVIDER, LLM_API_KEY
# Then:
venv\Scripts\python details\judge_simulator.py
```

Set `TEST_SCENARIO` to `"warmup"`, `"all"`, or `"full_evaluation"`.

---

## Evaluation Results (self-test)

- **All 30 canonical test pairs compose without errors** (verified via `_smoke.py`)
- **HTTP contract**: healthz, metadata, context push (200 + 409), tick (actions), reply (all transitions) — verified via `_http_smoke.py`
- **Auto-reply ladder** on same conversation: send → wait (86400s) → end ✓
- **Hostile opt-out**: `action: end` on first hostile turn ✓
- **Intent transition**: ACTION body (no re-qualifying) ✓
- **Out-of-scope deflect**: politely declines GST/loan asks and redirects to active trigger ✓
