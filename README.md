# CogDrift

**A clinician-gated anomaly-monitoring engine for cognitive rehabilitation data.**

CogDrift watches daily cognitive-game performance for early-stage Alzheimer's patients and flags statistically unusual patterns — a sudden drop, a slow multi-week drift — for a licensed clinician to review. It never diagnoses, never alerts a caregiver directly, and never lets anything reach a caregiver without a human confirming it first.

> **Statistical signal, not a diagnosis.** Every surface in this system — API responses, UI, logs — says so. This is a research prototype, not a certified medical device.

---

## Live Cloud Showcase & Architecture

The entire CogDrift system is deployed and runnable across three dedicated tiers:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        FRONTEND (Vercel)                               │
│  React + TypeScript + Vite + Tailwind CSS                              │
│  • Clinician Review Queue & Severity Sorting                           │
│  • Interactive 30d/60d Rolling Baseline Trajectory Chart (±2σ Bands)   │
│  • Scoped Caregiver Portal with Server-Enforced RBAC                   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ HTTPS (JWT Auth)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   BACKEND METRICS ENGINE (Back4App)                    │
│  Dockerized FastAPI Service (Python 3.12, scikit-learn, SQLAlchemy)    │
│  • Dual Broker Modes: In-Process BackgroundTasks OR Distributed AMQP   │
│  • Rolling 30d Z-Score Trend Detector + Isolation Forest Pattern Engine│
│  • Server-Side Medication/Dosage Safety Guardrail Screening           │
│  • /internal/reconcile Cron Endpoint for Nightly Sweeps                │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Asyncpg SSL Connection Pool
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                      DATABASE (Neon PostgreSQL)                         │
│  Serverless PostgreSQL (Singapore Region - ap-southeast-1)             │
│  • Patients, DailyScores, GameSessions, GameCatalog, Flags, AuditLogs  │
│  • High-throughput bulk batching with ON CONFLICT DO NOTHING           │
└────────────────────────────────────────────────────────────────────────┘
```

- **Frontend (Vercel)**: Deployed from the [`demo-ui`](./demo-ui) directory. Connects to the backend API via `VITE_API_BASE_URL`.
- **Backend (Back4App Containers)**: Dockerized FastAPI container with automated health monitoring (`/health`) and dynamic URL auto-normalization for async PostgreSQL.
- **Database (Neon PostgreSQL)**: Cloud-hosted serverless PostgreSQL with SSL encryption and async connection pooling.

---

## Why this exists

CogDrift started as a module inside [NeuroHaven](#), a cognitive rehabilitation platform for early-stage Alzheimer's patients built as a final-year project. The doctor's dashboard needed a way to flag when a patient's daily game scores looked genuinely concerning — not just noisy — without turning that judgment call over to an algorithm.

Rather than bury that logic inside a larger app, I pulled it out into its own standalone, open-source service: independent database, independent repo, no dependency on the parent project's infrastructure or data. It's built to run and be evaluated entirely on its own.

---

## What it actually does

Ten cognitive games produce daily scores. CogDrift runs two independent detectors against each patient's own history:

- **Trend detector** — a rolling 30-day personal baseline with a z-score/persistence rule (`z ≤ -2.0` sustained for 3 consecutive days). Catches sudden, sharp drops well; median detection lag of ~4.5 days on synthetic sudden-decline patients.
- **Pattern detector** — a per-patient Isolation Forest over each day's 10-game score vector (`contamination = 0.005`, persistence = 3 days) to avoid single-day noise triggering a flag.

A flag from either detector goes into a clinician review queue — never straight to a caregiver. A clinician confirms, dismisses, or requests more data. Only a clinician-confirmed flag ever produces a caregiver-facing message, and even that message is content-filtered server-side to block anything resembling a medication or dosage instruction — a real gap found during development (see below), not a hypothetical one.

---

## Architecture & Dual-Mode Broker

```
Patient app (game scores)
        │
        ▼
  ingestion-api (FastAPI) ───[EVENT_BROKER_MODE]───► Background Tasks / RabbitMQ
        │                                                            │
        ▼                                                            ▼
    Neon Postgres ◄──────────────────────────────────────────  Flag created (pending)
        │
        ▼
  Clinician review queue (JWT-gated, role-scoped)
        │  confirm
        ▼
  Caregiver portal (JWT-scoped to their patient(s) only, content-filtered messages)
```

CogDrift features a **dual-mode event dispatcher** configured via `EVENT_BROKER_MODE`:
1. **`in_process` (Default for Minimal Cloud / Back4App)**: Uses FastAPI `BackgroundTasks` to asynchronously trigger detection algorithms immediately after responding `200 OK` to score ingestion. Requires zero extra message broker infrastructure.
2. **`rabbitmq` (Distributed Worker Mode)**: Publishes `score.ingested` AMQP events to RabbitMQ consumed by an external `drift-worker` pool for high-throughput distributed architectures.

---

## Security and safety design

- **JWT-based RBAC, not a spoofable header.** `X-User-Role` was considered and explicitly rejected — a client-supplied header can't enforce anything. Roles and, for caregivers, a `patient_ids` claim are signed and verified server-side on every request.
- **Caregivers are scoped to their own patient(s) only, enforced at the endpoint**, not just hidden in the UI — covered by a real test that checks a caregiver token gets `200` on an authorized patient and `403` on one outside its scope.
- **Content-safety guardrail on clinician→caregiver notes.** During UI testing, a free-text guidance field was found capable of carrying an actual medication dosage instruction ("increase the dosage to 10mg") through to a caregiver as a permanent record — a scope violation with real potential for harm in a system that was never built to carry that kind of instruction safely. Fixed with server-side pattern screening, enforced uniformly across every review action (confirm/dismiss/needs-more-data), not just the confirm path, so it can't be bypassed by a future code change.
- **Every flag-touching API response carries a `disclaimer` field** baked into the schema, not left to documentation to remember.
- **Protected Internal Reconciliation**: `/internal/reconcile` is secured via constant-time token comparison (`secrets.compare_digest`) for nightly safety audits triggered by external cron schedulers.

---

## The evaluation — and why the honest result matters more than a clean one

CogDrift ships with a full evaluation harness (`evaluate.py`) against a synthetic, privacy-safe dataset with known ground-truth decline events. Building it correctly took real iteration, and the failure modes found along the way are worth stating plainly rather than hiding:

1. **Fake grid search**: An early version of the hyperparameter grid search wasn't actually testing different model configurations — it was reinterpreting one fixed model's output through an unrelated formula. Fixed by properly deriving thresholds from the model's real score distribution.
2. **Mixed-unit metrics**: Precision and recall were briefly computed by mixing two different units (per-patient counts against per-flag-instance counts) — an apples-to-oranges ratio that looked plausible and wasn't. Fixed by separating them into two clearly labeled metrics.
3. **Degenerate F1-argmax selection**: Unconstrained F1 optimization discovered and selected a "flag every patient at least once" configuration — because with enough independent daily tests, that's a mathematical inevitability (multiple-comparisons problem), and F1 alone doesn't penalize it enough. Fixed by adding a persistence requirement to the pattern detector and constraining hyperparameter selection to a stable-FPR ceiling, not raw F1-argmax.
4. **Self-evaluation leakage**: A subtle self-evaluation leakage bug let the Isolation Forest partially train on the same days it was later scoring for persistence — biasing results in a way that took careful tracing to find. Fixed by strictly excluding the full evaluation window from training.
5. **Code path divergence on unified functions**: Even after "unifying" the evaluation and production code into one shared function, they were initially invoked differently enough to still diverge — a reminder that "calls the same function" and "exercises the same code path" are different claims, and both require explicit validation.

**The final, honest numbers**, on a stratified 70/30 split with 5-fold cross-validated, FPR-constrained hyperparameter selection (`contamination=0.005`, `pattern_persistence=3`, `score_threshold=0.0097`):

| Metric | Value | Notes |
|---|---|---|
| **Held-Out Stable Patient FPR** | **0.375** (9/24) | Primary generalization validation result (unseen stable patients) |
| **Held-Out Volatile Patient FPR** | **0.200** (1/5) | Measured on held-out volatile patient validation group |
| **Patient-Level Recall** | **0.222** (4/18) | Catches acute sudden-onset decline events |
| **Median Lag, Sudden Decline** | **4.5 days** | Turnaround time on detected acute decline cases |
| **Median Lag, Gradual Decline** | *not currently detected* | Documented baseline limitation across all tested configs |
| Cross-Validation Stable FPR (Selection) | 0.291 | Model selection estimate on training folds |

> **Note on generalization**: The held-out result (**0.375**) is the primary generalization metric to evaluate; the cross-validation selection estimate (**0.291**) was modestly optimistic by a margin consistent with a small validation cohort (24 held-out stable patients).

This is a conservative system: it currently catches some sudden-onset decline and misses gradual decline entirely, across every configuration tested. That's a real, specific, documented limitation — not glossed over with a vague "future work" line. The most likely next lever is per-patient-relative feature normalization (comparing a patient against their own historical spread rather than a pooled population threshold), which is genuine v2 scope, not a quick tuning fix.

---

## Tech stack

- **Backend:** FastAPI, SQLAlchemy (async `asyncpg`), Alembic, `aio-pika` (RabbitMQ), APScheduler, scikit-learn, PyJWT, Pydantic v2
- **Frontend:** React 18, Vite, TypeScript, Tailwind CSS, Lucide Icons, Recharts
- **Cloud Infrastructure:**
  - **Containers:** Back4App Containers (Dockerized FastAPI runtime)
  - **Database:** Neon Serverless PostgreSQL (`ap-southeast-1` Singapore, SSL)
  - **Hosting / CDN:** Vercel (React Vite SPA)
- **Local Infra:** Docker Compose (FastAPI + PostgreSQL + RabbitMQ)
- **Data Generator:** Synthetic patient generator with documented fidelity per game (`FAITHFUL` / `PARTIAL` / `ASSUMED`) and injected, labeled ground-truth decline events.

---

## Running it locally

```bash
# 1. Generate synthetic dataset
python generate_dataset.py --patients 150 --days 120 --seed 42 --out ./data

# 2. Bring up local Docker Compose stack (FastAPI + Postgres + RabbitMQ)
docker compose up --build

# 3. Seed the database with fast bulk batching
DATABASE_URL="postgresql+asyncpg://cogdrift:dev_only_change_me@localhost:5432/cogdrift" python seed_db.py

# 4. Generate demo review flags
DATABASE_URL="postgresql+asyncpg://cogdrift:dev_only_change_me@localhost:5432/cogdrift" python create_demo_flags.py

# 5. Run the evaluation harness
python evaluate.py --data ./data

# 6. Run the full backend test suite
PYTHONPATH=service pytest service/tests/test_engine.py
```

---

## Environment Variables Configuration

> ⚠️ **Security Warning**: Secrets (`JWT_SECRET`, `ADMIN_RECONCILE_TOKEN`, database credentials) must be generated as cryptographically strong random values and stored exclusively in private environment variables (e.g. Back4App / Vercel dashboard settings). Never commit production secrets to source control.

| Variable | Description | Example / Default |
|---|---|---|
| `DATABASE_URL` | PostgreSQL connection string (`asyncpg`) | `postgresql+asyncpg://<user>:<password>@<host>/<db>?ssl=require` |
| `EVENT_BROKER_MODE` | Event dispatch mode (`in_process` or `rabbitmq`) | `in_process` |
| `JWT_SECRET` | Secret key for signing clinician/caregiver JWTs | `<generate-secure-random-secret>` |
| `ADMIN_RECONCILE_TOKEN` | Token for authenticating `/internal/reconcile` | `<generate-secure-random-token>` |
| `BASELINE_WINDOW_DAYS` | Rolling window length for personal baseline | `30` |
| `COLD_START_MIN_DAYS` | Minimum days of history required before flagging | `14` |
| `TREND_Z_THRESHOLD` | Standard deviation threshold for trend drop | `-2.0` |
| `TREND_PERSISTENCE_DAYS`| Consecutive days required for trend flag | `3` |
| `ISOLATION_FOREST_CONTAMINATION` | Expected anomaly contamination rate | `0.005` |
| `PATTERN_PERSISTENCE_DAYS` | Consecutive anomalous days for pattern flag | `3` |
| `VITE_API_BASE_URL` | Frontend API URL pointing to backend service | `https://<your-backend-app>.b4a.run` |

---

## Project structure

```
cogdrift/
├── generate_dataset.py     # Synthetic data generator with clinical decline profiles
├── evaluate.py             # Stratified CV evaluation harness with FPR constraints
├── seed_db.py              # High-performance bulk PostgreSQL seeding script
├── create_demo_flags.py    # Generates initial clinician review flags for live demo
├── docker-compose.yml      # Local multi-container development environment
├── service/                # Backend FastAPI application
│   ├── Dockerfile          # Production container build
│   ├── requirements.txt    # Python dependencies
│   └── app/
│       ├── main.py         # REST endpoints, RBAC middleware, content safety
│       ├── database.py     # Async SQLAlchemy engine with URL auto-normalization
│       ├── config.py       # Pydantic v2 application settings
│       ├── auth.py         # JWT verification, RBAC role-scoping
│       ├── worker.py       # Anomaly evaluation workers & reconciliation
│       └── detectors/
│           ├── trend.py    # Rolling baseline & Z-score trend detector
│           └── pattern.py  # Isolation Forest multi-game pattern detector
└── demo-ui/                # Frontend React + Vite + TypeScript dashboard (Vercel)
    ├── src/
    │   ├── App.tsx         # Main container, role switching, health status
    │   └── components/
    │       ├── ReviewQueue.tsx     # Clinician triage queue & review actions
    │       ├── TrendChart.tsx      # Recharts rolling trajectory & confidence bands
    │       └── CaregiverView.tsx   # Scoped caregiver feed with safety disclaimers
```

---

## Disclaimer

CogDrift is a research prototype for statistical anomaly monitoring in cognitive rehabilitation data. It is not a certified diagnostic device. Every detection signal must be reviewed and confirmed by a licensed clinician before any notification reaches a caregiver.