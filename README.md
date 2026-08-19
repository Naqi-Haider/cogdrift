# CogDrift

**A clinician-gated anomaly-monitoring engine for cognitive rehabilitation data.**

CogDrift watches daily cognitive-game performance for early-stage Alzheimer's patients and flags statistically unusual patterns — a sudden drop, a slow multi-week drift — for a licensed clinician to review. It never diagnoses, never alerts a caregiver directly, and never lets anything reach a caregiver without a human confirming it first.

> **Statistical signal, not a diagnosis.** Every surface in this system — API responses, UI, logs — says so. This is a research prototype, not a certified medical device.

---

## Why this exists

CogDrift started as a module inside [NeuroHaven](#), a cognitive rehabilitation platform for early-stage Alzheimer's patients built as a final-year project. The doctor's dashboard needed a way to flag when a patient's daily game scores looked genuinely concerning — not just noisy — without turning that judgment call over to an algorithm.

Rather than bury that logic inside a larger app, I pulled it out into its own standalone, open-source service: independent database, independent repo, no dependency on the parent project's infrastructure or data. It's built to run and be evaluated entirely on its own.

## What it actually does

Ten cognitive games produce daily scores. CogDrift runs two independent detectors against each patient's own history:

- **Trend detector** — a rolling 30-day personal baseline with a z-score/persistence rule (`z ≤ -2.0` sustained for 3 consecutive days). Catches sudden, sharp drops well; median detection lag of ~4.5 days on synthetic sudden-decline patients.
- **Pattern detector** — a per-patient Isolation Forest over each day's 10-game score vector, with its own persistence requirement to avoid single-day noise triggering a flag.

A flag from either detector goes into a clinician review queue — never straight to a caregiver. A clinician confirms, dismisses, or requests more data. Only a clinician-confirmed flag ever produces a caregiver-facing message, and even that message is content-filtered server-side to block anything resembling a medication or dosage instruction — a real gap found during development (see below), not a hypothetical one.

## Architecture

```
Patient app (game scores)
        │
        ▼
  ingestion-api (FastAPI) ──publishes──► RabbitMQ ──consumes──► drift-worker
        │                                                            │
        ▼                                                            ▼
    Postgres  ◄──────────────────────────────────────────  Flag created (pending)
        │
        ▼
  Clinician review queue (JWT-gated, role-scoped)
        │  confirm
        ▼
  Caregiver portal (JWT-scoped to their patient(s) only, content-filtered messages)
```

- **Event-driven, not polling-driven internally**: new scores publish a `score.ingested` event; a worker recomputes just that patient's detectors, with a nightly reconciliation pass as a safety net.
- **Frontend delivery is simple polling** (30–60s) — a clinician's queue isn't a live chat, and polling is far less to build and debug than a persistent connection for a use case that doesn't need one.

## Security and safety design

- **JWT-based RBAC, not a spoofable header.** `X-User-Role` was considered and explicitly rejected — a client-supplied header can't enforce anything. Roles and, for caregivers, a `patient_ids` claim are signed and verified server-side on every request.
- **Caregivers are scoped to their own patient(s) only, enforced at the endpoint**, not just hidden in the UI — covered by a real test that checks a caregiver token gets `200` on an authorized patient and `403` on one outside its scope.
- **Content-safety guardrail on clinician→caregiver notes.** During UI testing, a free-text guidance field was found capable of carrying an actual medication dosage instruction ("increase the dosage to 10mg") through to a caregiver as a permanent record — a scope violation with real potential for harm in a system that was never built to carry that kind of instruction safely. Fixed with server-side pattern screening, enforced uniformly across every review action (confirm/dismiss/needs-more-data), not just the confirm path, so it can't be bypassed by a future code change.
- **Every flag-touching API response carries a `disclaimer` field** baked into the schema, not left to documentation to remember.

## The evaluation — and why the honest result matters more than a clean one

CogDrift ships with a full evaluation harness (`evaluate.py`) against a synthetic, privacy-safe dataset with known ground-truth decline events. Building it correctly took real iteration, and the failure modes found along the way are worth stating plainly rather than hiding:

- An early version of the hyperparameter grid search wasn't actually testing different model configurations — it was reinterpreting one fixed model's output through an unrelated formula. Fixed by properly deriving thresholds from the model's real score distribution.
- Precision and recall were briefly computed by mixing two different units (per-patient counts against per-flag-instance counts) — an apples-to-oranges ratio that looked plausible and wasn't. Fixed by separating them into two clearly labeled metrics.
- Unconstrained F1 optimization discovered and selected a **"flag every patient at least once"** configuration — because with enough independent daily tests, that's a mathematical inevitability (multiple-comparisons problem), and F1 alone doesn't penalize it enough. Fixed by adding a persistence requirement to the pattern detector and constraining hyperparameter selection to a stable-FPR ceiling, not raw F1-argmax.
- A subtle self-evaluation leakage bug let the Isolation Forest partially train on the same days it was later scoring for persistence — biasing results in a way that took careful tracing to find. Fixed by strictly excluding the full evaluation window from training.
- Even after "unifying" the evaluation and production code into one function, they were briefly invoked differently enough to still diverge — a reminder that "calls the same function" and "exercises the same code path" are different claims, and both need checking.

**The final, honest numbers**, on a stratified 70/30 split with 5-fold cross-validated, FPR-constrained hyperparameter selection:

| Metric | Value |
|---|---|
| Patient-level recall | 0.222 (4/18) |
| Median lag, sudden decline | 4.5 days |
| Median lag, gradual decline | not currently detected |
| Held-out stable-patient FPR | 0.375 |
| Held-out volatile-patient FPR | 0.200 |

This is a conservative system: it currently catches some sudden-onset decline and misses gradual decline entirely, across every configuration tested. That's a real, specific, documented limitation — not glossed over with a vague "future work" line. The most likely next lever is per-patient-relative feature normalization (comparing a patient against their own historical spread rather than a pooled population threshold), which is genuine v2 scope, not a quick tuning fix.

## Tech stack

**Backend:** FastAPI, SQLAlchemy (async) + PostgreSQL, Alembic, `aio-pika` (RabbitMQ), APScheduler, scikit-learn, PyJWT
**Frontend:** React + Vite + TypeScript, Recharts, Tailwind
**Infra:** Docker Compose
**Data:** a from-scratch synthetic patient/game-score generator with documented fidelity per game (`FAITHFUL` / `PARTIAL` / `ASSUMED` against the real scoring logic it's modeled on) and injected, labeled ground-truth decline events for evaluation

## Running it locally

```bash
# 1. Generate a synthetic dataset
python generate_dataset.py --patients 150 --days 120 --seed 42 --out ./data

# 2. Bring up the stack
docker compose up --build

# 3. Run the evaluation
python evaluate.py --data ./data

# 4. Run the test suite
PYTHONPATH=service pytest service/tests/test_engine.py
```

## Project structure

```
cogdrift/
├── COGDRIFT_SPEC.md        # the full design doc — architecture, decisions, and honest results
├── generate_dataset.py     # synthetic data generator
├── evaluate.py              # stratified CV evaluation harness
├── docker-compose.yml
├── service/
│   └── app/
│       ├── main.py
│       ├── auth.py          # JWT verification, RBAC
│       ├── worker.py        # event-driven + nightly reconciliation
│       └── detectors/
│           ├── trend.py
│           └── pattern.py
└── demo-ui/                 # Clinician + Caregiver portals
```

See [`COGDRIFT_SPEC.md`](./COGDRIFT_SPEC.md) for the complete design history, every architectural decision, and the full evaluation writeup.

## Disclaimer

CogDrift is a research prototype for statistical anomaly monitoring in cognitive rehabilitation data. It is not a certified diagnostic device. Every detection signal must be reviewed and confirmed by a licensed clinician before any notification reaches a caregiver.