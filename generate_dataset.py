"""
CogDrift synthetic dataset generator
=====================================

Generates a realistic, privacy-safe synthetic dataset matching the real
NeuroHaven game catalog and, wherever the real Dart scoring logic was
available, the real per-game scoring formulas.

FIDELITY KEY (see GAME_CATALOG and each score_* function):
  FAITHFUL - the exact scoring formula from the provided .dart file
  PARTIAL  - formula is faithful, but a config default not shown in the
             file (round count, pair count, option count) was assumed
  ASSUMED  - no scoring/normalization formula was visible in the provided
             file at all (only raw counters, or no file at all); a
             reasonable proxy was built

Two corrections from earlier versions of this script:
  1. memory_match was originally modeled on memory_scoring_service.dart /
     memory_test_data.dart (a picture target/foil recognition test). Real
     memory_match_logic.dart is a completely different game — classic
     card-flip pairs matching. Fixed.
  2. That picture-recognition test was then assumed to be the 10th game.
     It's actually a ONE-TIME onboarding baseline assessment ("taken at
     first, at the start of the application first time, to get the
     average evaluation of patient performance") — not one of the 10
     recurring daily games at all. The real 10th game is sound_sequence,
     a Simon-Says-style audio sequence game (no source file available,
     so it's modeled ASSUMED by structural analogy to sequence_recall).

     Consequence: the picture-recall test is no longer in GAME_CATALOG /
     game_sessions. It's now a separate initial_assessments.csv — one row
     per patient, generated once at enrollment — which is exactly what a
     personalized baseline needs on day one, instead of running blind for
     the first ~14 days of a patient's history.

Usage:
    python generate_dataset.py --patients 40 --days 120 --seed 42 --out ./data

Outputs (all CSV, written to --out):
    patients.csv              one row per patient (no risk_profile — that's hidden)
    game_catalog.csv          the 10 recurring games (id, name, domain, fidelity)
    initial_assessments.csv   one-time onboarding baseline score per patient
    game_sessions.csv         one row per game played (patient, game, score, date)
    daily_scores.csv          one row per patient per day played (aggregate score)
    ground_truth_events.csv   hidden labels: which patients have a real decline
                               event and when it starts. FOR VALIDATION ONLY —
                               never feed this into CogDrift's ingestion API.
    schema.sql                Postgres/Supabase table definitions matching the CSVs
"""

import argparse
import os
import uuid
from datetime import date, timedelta

import numpy as np
import pandas as pd

GAME_CATALOG = [
    (1, "abstract_reasoning", "executive_function", "PARTIAL"),
    (2, "digit_span", "working_memory", "FAITHFUL"),
    (3, "focus_flow", "sustained_attention", "ASSUMED"),
    (4, "memory_match", "visual_working_memory", "ASSUMED"),
    (5, "paired_associate", "associative_memory", "PARTIAL"),
    (6, "sequence_recall", "short_term_memory", "ASSUMED"),
    (7, "statement_completion", "language_comprehension", "PARTIAL"),
    (8, "train_of_thought", "executive_function", "ASSUMED"),
    (9, "word_select", "semantic_memory", "PARTIAL"),
    (10, "sound_sequence", "auditory_working_memory", "ASSUMED"),
]

RISK_PROFILES = ["stable", "gradual_decline", "sudden_decline", "volatile"]
RISK_WEIGHTS = [0.55, 0.20, 0.15, 0.10]
SIM_START_DATE = date(2026, 1, 1)


def parse_args():
    p = argparse.ArgumentParser(description="Generate a synthetic CogDrift dataset")
    p.add_argument("--patients", type=int, default=40)
    p.add_argument("--days", type=int, default=120)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", type=str, default="./data")
    return p.parse_args()


def make_patients(n, rng):
    rows = []
    for i in range(n):
        pid = f"P{i + 1:04d}"
        age = int(rng.integers(60, 88))
        risk = rng.choice(RISK_PROFILES, p=RISK_WEIGHTS)
        enroll_offset = int(rng.integers(0, 30))
        rows.append(
            {
                "patient_id": pid,
                "age": age,
                "diagnosis_stage": "early_stage_alzheimers",
                "enrollment_date": (SIM_START_DATE + timedelta(days=enroll_offset)).isoformat(),
                "_risk_profile": risk,
            }
        )
    return pd.DataFrame(rows)


def baseline_curve(risk, days, rng):
    base = float(np.clip(rng.normal(7.2, 0.4), 5.5, 8.5))
    curve = np.full(days, base)
    event_start = None

    if risk == "gradual_decline":
        event_start = int(rng.integers(days // 4, max(days // 4 + 1, days // 2)))
        decline_rate = rng.uniform(0.015, 0.035)
        for d in range(event_start, days):
            curve[d] = max(2.0, base - decline_rate * (d - event_start))
    elif risk == "sudden_decline":
        event_start = int(rng.integers(days // 4, max(days // 4 + 1, 3 * days // 4)))
        drop = rng.uniform(2.0, 3.5)
        recovers = rng.random() < 0.4
        for d in range(event_start, days):
            if recovers and d > event_start + 14:
                recovery_frac = min(1.0, (d - event_start - 14) / 20)
                curve[d] = base - drop * (1 - recovery_frac)
            else:
                curve[d] = base - drop
    elif risk == "volatile":
        curve = base + rng.normal(0, 1.1, days)
    else:
        curve = base + rng.normal(0, 0.25, days)

    return np.clip(curve, 1, 10), event_start


# ---------------------------------------------------------------------------
# Per-game scoring simulations (the 10 recurring games)
# ---------------------------------------------------------------------------

def score_abstract_reasoning(ability, rng):
    """PARTIAL. Real formula (abstract_reasoning_screen.dart):
    finalScore = round(correctCount / questionCount * 10).clamp(0,10).
    ASSUMED: questionCount=10 (matches the code's `clamp(10, ...)` floor).
    ASSUMED: 4-option MCQ (normal-difficulty foilCount=3 -> 4 options),
    giving a ~0.25 guess floor, which is real behavior of the actual UI's
    difficulty system, not an invented number."""
    n = 10
    p_correct = float(np.clip(0.22 + 0.075 * ability, 0.20, 0.97))
    correct = int(rng.binomial(n, p_correct))
    return int(np.clip(round(correct / n * 10), 0, 10))


def score_digit_span(ability, rng, start_length=3):
    """FAITHFUL. Real formula (digit_span_logic.dart):
    score = ((maxLevelReached - startLength) * 10 // (15 - startLength)).clamp(0,10)
    Simulated via a staircase: probability of extending the span decreases
    each level and increases with ability — the same shape as a real
    adaptive span test.

    CALIBRATION NOTE: the per-level success probability itself isn't in the
    real code (that lives in actual human behavior, not the scoring class),
    so these three constants (0.93 base, 0.02 ability slope, 0.014 per-level
    decay) are a tuned assumption, not a confirmed value. They were picked
    so an average-ability patient (~7/10) lands around score 6, comparable
    to the other games. Retune if it doesn't match how patients actually
    perform on this game."""
    level = start_length
    while True:
        p_success = float(np.clip(0.93 + 0.02 * (ability - 5) - 0.014 * (level - start_length), 0.02, 0.97))
        if rng.random() < p_success:
            level += 1
        else:
            break
    max_level_reached = level
    raw = (max_level_reached - start_length) * 10 // (15 - start_length)
    return int(np.clip(raw, 0, 10))


def score_focus_flow(ability, rng):
    """ASSUMED. focus_flow_logic.dart only exposes raw correctTaps / lives /
    score-plus-10-per-hit counters — no visible normalization to 0-10.
    Proxy: hit-rate-based score, with slightly higher day-to-day noise than
    other games since sustained-attention tasks are known to be more
    sensitive to fatigue/sleep than pure memory tasks."""
    accuracy = float(np.clip(ability / 10 + rng.normal(0, 0.12), 0.05, 0.98))
    return int(np.clip(round(accuracy * 10), 0, 10))


def score_memory_match(ability, rng, pair_count=6):
    """ASSUMED. memory_match_logic.dart (the real card-flip pairs game)
    exposes moves / matchesFound / wrongCount but no score getter at all.
    Proxy: efficiency-based — moves = pairCount + extra wrong attempts,
    extra attempts fall as ability rises. pair_count=6 (12 cards) is an
    assumed grid size, not from the code (totalCards has no default there)."""
    expected_extra = max(0.3, (10 - ability) * 1.3)
    extra = int(rng.poisson(expected_extra))
    moves = pair_count + extra
    raw = (pair_count / moves) * 10
    return int(np.clip(round(raw), 0, 10))


_PAIRED_ASSOCIATE_PAIR_COUNT = 4  # real constructor default (pairCount = 4)


def score_paired_associate(ability, rng, pair_count=_PAIRED_ASSOCIATE_PAIR_COUNT):
    """PARTIAL. Real formula (paired_associate_logic.dart):
    exact match = 2pts, typo-tolerant/semantic match = 1pt, else 0;
    finalScore = round(totalScore / (pairs*2) * 10).clamp(0,10).
    pair_count=4 is the actual code default. Outcome probabilities per
    pair (exact/partial/semantic/miss) are ability-scaled since the real
    semantic-similarity model isn't in the provided file."""
    p_exact = float(np.clip(0.08 + 0.085 * ability, 0.03, 0.92))
    remaining = 1 - p_exact
    p_partial = 0.5 * remaining * float(np.clip(ability / 10, 0.1, 1))
    p_semantic = 0.25 * remaining * float(np.clip(ability / 10, 0.1, 1))
    p_miss = max(0.0, 1 - p_exact - p_partial - p_semantic)
    probs = np.array([p_exact, p_partial, p_semantic, p_miss])
    probs = probs / probs.sum()

    total_score = 0
    for _ in range(pair_count):
        outcome = rng.choice(["exact", "partial", "semantic", "miss"], p=probs)
        if outcome == "exact":
            total_score += 2
        elif outcome in ("partial", "semantic"):
            total_score += 1
    return int(np.clip(round(total_score / (pair_count * 2) * 10), 0, 10))


def score_sequence_recall(ability, rng, start_length=3):
    """ASSUMED. sequence_recall_logic.dart has no score/finalScore getter
    at all — only currentLevel. This reuses digit_span's real formula by
    strong structural analogy (both are 'reach the highest level via
    correct sequential taps' staircase games with the same startLength=3
    default), not a confirmed formula for this specific game."""
    return score_digit_span(ability, rng, start_length=start_length)


def score_statement_completion(ability, rng):
    """PARTIAL. Real formula (statement_completion_screen.dart) is
    identical in shape to abstract_reasoning: round(correct/n*10).clamp(0,10),
    n=10 assumed via the same `clamp(10, ...)` floor. Option count (and
    therefore guess floor) isn't shown per-question, assumed 4-option MCQ."""
    return score_abstract_reasoning(ability, rng)


def score_train_of_thought(ability, rng):
    """ASSUMED. train_of_thought_logic.dart exposes score+=1 per correct
    route and lives/totalRouted counters but no normalization to 0-10.
    Proxy: routing-accuracy-based score."""
    accuracy = float(np.clip(ability / 10 + rng.normal(0, 0.1), 0.05, 0.98))
    return int(np.clip(round(accuracy * 10), 0, 10))


_WORD_SELECT_ROUNDS = 5  # ASSUMED session length; roundCount default not shown


def score_word_select(ability, rng, rounds=_WORD_SELECT_ROUNDS):
    """PARTIAL. Real formula (word_select_logic.dart), verified exactly
    against the round data — every round has exactly 4 correctWords:
      roundScore = clip((correctSelected/4)*10 - wrongSelected*2, 0, 10)
      finalScore = round(mean(roundScore across rounds)).clamp(0,10)
    rounds=5 (how many rounds make up one session) is assumed — the
    real roundCount default wasn't in the provided file."""
    correct_per_round = 4
    p_hit = float(np.clip(ability / 10, 0.15, 0.98))
    wrong_lambda = max(0.05, (10 - ability) * 0.25)

    round_scores = []
    for _ in range(rounds):
        correct_selected = int(rng.binomial(correct_per_round, p_hit))
        wrong_selected = int(rng.poisson(wrong_lambda))
        raw = (correct_selected / correct_per_round) * 10 - wrong_selected * 2
        round_scores.append(float(np.clip(raw, 0, 10)))

    final = round(float(np.mean(round_scores)))
    return int(np.clip(final, 0, 10))


def score_sound_sequence(ability, rng, start_length=3):
    """ASSUMED — no source file. Per your description ('similar to Simon
    says — cards produce a sound, patient must remember and match the
    sequence to succeed'), this is structurally a Simon-Says staircase
    game like sequence_recall, just with audio cues (animal/car/etc.
    sounds) instead of visual tile highlighting. Reuses the same
    calibrated staircase as digit_span/sequence_recall.

    If a sound_sequence_logic.dart (or similar) file exists, upload it
    and this becomes FAITHFUL/PARTIAL instead of ASSUMED — worth doing,
    since audio-cue recall for elderly patients can plausibly have a
    different error profile than visual recall (e.g. hearing-related
    confounds), which this proxy doesn't model at all."""
    return score_digit_span(ability, rng, start_length=start_length)


SCORE_FUNCS = {
    1: score_abstract_reasoning,
    2: score_digit_span,
    3: score_focus_flow,
    4: score_memory_match,
    5: score_paired_associate,
    6: score_sequence_recall,
    7: score_statement_completion,
    8: score_train_of_thought,
    9: score_word_select,
    10: score_sound_sequence,
}


def score_game(game_id, ability, rng):
    return SCORE_FUNCS[game_id](ability, rng)


def simulate_day_play(rng, ability_today, engagement_bias=1.0):
    if rng.random() < 0.08:
        return []
    n_games = len(GAME_CATALOG)
    n_games_today = int(np.clip(rng.binomial(n_games, 0.55 * engagement_bias), 1, n_games))
    game_ids = [g[0] for g in GAME_CATALOG]
    games_today = rng.choice(game_ids, size=n_games_today, replace=False)
    sessions = []
    for gid in games_today:
        score = score_game(int(gid), ability_today, rng)
        sessions.append((int(gid), score))
    return sessions


# ---------------------------------------------------------------------------
# One-time onboarding baseline assessment (NOT one of the 10 recurring games)
# ---------------------------------------------------------------------------

def score_initial_assessment(ability, rng, targets=10, foils=6):
    """PARTIAL. This is the picture-recognition test from
    memory_scoring_service.dart / memory_test_data.dart: exact hits score
    1.0, foil picks score 0.5 (every foil shares a category with some
    target in the real catalog, so every foil pick is a 'semantic error'
    under that code's rule). Hit rate rises and intrusion rate falls with
    ability — standard recognition-memory pattern.

    Run ONCE per patient, at enrollment — it's the onboarding baseline,
    not a recurring game — using the patient's ability on their
    enrollment day as the input. ASSUMED: the raw score's normalization
    to a stored value (not shown in the two files); clipped to [0,10]
    here."""
    hit_prob = float(np.clip(ability / 10, 0.15, 0.98))
    exact_hits = int(rng.binomial(targets, hit_prob))
    intrusion_lambda = max(0.05, 0.3 + 1.2 * (10 - ability) / 10)
    num_intrusions = int(min(foils, rng.poisson(intrusion_lambda)))
    raw_score = exact_hits * 1.0 + num_intrusions * 0.5
    return int(np.clip(round(raw_score), 0, 10))


SCHEMA_SQL = """-- CogDrift dev schema (Postgres / Supabase compatible)
create table if not exists patients (
    patient_id text primary key,
    age integer,
    diagnosis_stage text,
    enrollment_date date
);

create table if not exists game_catalog (
    game_id integer primary key,
    game_name text,
    cognitive_domain text,
    scoring_fidelity text  -- FAITHFUL / PARTIAL / ASSUMED, see generator docstring
);

-- One-time onboarding baseline, NOT part of the recurring 10-game loop.
-- Use this to seed a patient's personalized baseline from day one instead
-- of waiting out the cold-start period blind.
create table if not exists initial_assessments (
    patient_id text primary key references patients(patient_id),
    assessed_at date,
    score integer check (score between 0 and 10)
);

create table if not exists game_sessions (
    session_id uuid primary key,
    patient_id text references patients(patient_id),
    game_id integer references game_catalog(game_id),
    score integer check (score between 0 and 10),
    played_at date
);

create table if not exists daily_scores (
    patient_id text references patients(patient_id),
    date date,
    games_played integer,
    daily_cognitive_score numeric(4,1),
    primary key (patient_id, date)
);
"""


def main():
    args = parse_args()
    rng = np.random.default_rng(args.seed)
    os.makedirs(args.out, exist_ok=True)

    patients_df = make_patients(args.patients, rng)
    all_sessions, all_daily, ground_truth, initial_assessments = [], [], [], []

    for _, prow in patients_df.iterrows():
        pid = prow["patient_id"]
        risk = prow["_risk_profile"]
        curve, event_start = baseline_curve(risk, args.days, rng)

        # one-time onboarding assessment, using day-0 ability
        assessment_score = score_initial_assessment(curve[0], rng)
        initial_assessments.append(
            {"patient_id": pid, "assessed_at": prow["enrollment_date"], "score": assessment_score}
        )

        for d in range(args.days):
            engagement_bias = 0.8 if (event_start is not None and d >= event_start) else 1.0
            today = (SIM_START_DATE + timedelta(days=d)).isoformat()
            sessions = simulate_day_play(rng, curve[d], engagement_bias)

            for gid, score in sessions:
                all_sessions.append(
                    {"session_id": str(uuid.uuid4()), "patient_id": pid, "game_id": gid, "score": score, "played_at": today}
                )
            if sessions:
                daily_score = round(float(np.mean([s for _, s in sessions])), 1)
                all_daily.append(
                    {"patient_id": pid, "date": today, "games_played": len(sessions), "daily_cognitive_score": daily_score}
                )

        if event_start is not None:
            ground_truth.append(
                {
                    "patient_id": pid,
                    "risk_profile": risk,
                    "event_start_day_index": event_start,
                    "event_start_date": (SIM_START_DATE + timedelta(days=event_start)).isoformat(),
                }
            )

    patient_risk_labels = patients_df[["patient_id", "_risk_profile"]].rename(columns={"_risk_profile": "risk_profile"})
    patient_risk_labels.to_csv(os.path.join(args.out, "patient_risk_labels.csv"), index=False)

    patients_df.drop(columns=["_risk_profile"]).to_csv(os.path.join(args.out, "patients.csv"), index=False)
    pd.DataFrame(GAME_CATALOG, columns=["game_id", "game_name", "cognitive_domain", "scoring_fidelity"]).to_csv(
        os.path.join(args.out, "game_catalog.csv"), index=False
    )
    pd.DataFrame(initial_assessments).to_csv(os.path.join(args.out, "initial_assessments.csv"), index=False)
    pd.DataFrame(all_sessions).to_csv(os.path.join(args.out, "game_sessions.csv"), index=False)
    pd.DataFrame(all_daily).to_csv(os.path.join(args.out, "daily_scores.csv"), index=False)
    pd.DataFrame(ground_truth).to_csv(os.path.join(args.out, "ground_truth_events.csv"), index=False)

    with open(os.path.join(args.out, "schema.sql"), "w") as f:
        f.write(SCHEMA_SQL)

    print(f"Games in catalog:       {len(GAME_CATALOG)} (all 10 real names confirmed)")
    print(f"Patients:               {len(patients_df)}")
    print(f"Initial assessments:    {len(initial_assessments)}")
    print(f"Game sessions:          {len(all_sessions)}")
    print(f"Daily score rows:       {len(all_daily)}")
    print(f"Labeled decline events: {len(ground_truth)}")
    print(f"Files written to:       {os.path.abspath(args.out)}")


if __name__ == "__main__":
    main()
