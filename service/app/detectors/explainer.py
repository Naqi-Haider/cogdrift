from typing import List, Dict, Optional
import pandas as pd
import numpy as np


GAME_NAME_MAP = {
    1: "abstract_reasoning",
    2: "digit_span",
    3: "focus_flow",
    4: "memory_match",
    5: "paired_associate",
    6: "sequence_recall",
    7: "statement_completion",
    8: "train_of_thought",
    9: "word_select",
    10: "sound_sequence",
}


def compute_per_game_deltas(
    game_sessions: List[Dict], target_date: str
) -> List[Dict]:
    """Calculates per-game score drop on target_date compared to patient's historical average."""
    if not game_sessions:
        return []

    df = pd.DataFrame(game_sessions)
    df["played_at_str"] = df["played_at"].astype(str)

    target_sessions = df[df["played_at_str"] == target_date]
    history_sessions = df[df["played_at_str"] < target_date]

    if target_sessions.empty or history_sessions.empty:
        return []

    hist_means = history_sessions.groupby("game_id")["score"].mean().to_dict()

    deltas = []
    for _, srow in target_sessions.iterrows():
        gid = int(srow["game_id"])
        score_today = float(srow["score"])
        hist_avg = float(hist_means.get(gid, score_today))
        delta = score_today - hist_avg  # Negative indicates drop below average

        deltas.append({
            "game_id": gid,
            "game_name": GAME_NAME_MAP.get(gid, f"game_{gid}"),
            "today_score": score_today,
            "historical_avg": round(hist_avg, 1),
            "delta": round(delta, 1),
        })

    # Sort by largest negative delta (drops)
    deltas.sort(key=lambda x: x["delta"])
    return deltas


def generate_flag_explanation(
    detector_type: str,  # TREND / PATTERN / BOTH
    z_score: Optional[float],
    isolation_score: Optional[float],
    persistence_days: int,
    game_sessions: List[Dict],
    target_date: str,
) -> str:
    """Dual-path plain language explanation generator for clinician review queue."""
    explanation_parts = []

    # Path 1: Trend explanation
    if detector_type in ("TREND", "BOTH") and z_score is not None:
        z_fmt = f"{z_score:.2f}"
        explanation_parts.append(
            f"Trend signal: Daily cognitive score dropped to z = {z_fmt} below patient's 30-day baseline for {persistence_days} consecutive days."
        )

    # Path 2: Pattern explanation & game score deltas
    deltas = compute_per_game_deltas(game_sessions, target_date)
    top_drops = [d for d in deltas if d["delta"] < 0][:3]

    if detector_type in ("PATTERN", "BOTH"):
        iso_fmt = f"{isolation_score:.3f}" if isolation_score is not None else "N/A"
        pattern_str = f"Pattern signal: Unusual daily gameplay score vector (Isolation score: {iso_fmt})."
        if top_drops:
            drop_items = [
                f"{d['game_name']} ({d['today_score']} vs avg {d['historical_avg']}, delta: {d['delta']})"
                for d in top_drops
            ]
            pattern_str += f" Largest performance drops: {', '.join(drop_items)}."
        explanation_parts.append(pattern_str)
    elif detector_type == "TREND" and top_drops:
        drop_items = [
            f"{d['game_name']} (score {d['today_score']} vs avg {d['historical_avg']})"
            for d in top_drops
        ]
        explanation_parts.append(f"Primary contributing games: {', '.join(drop_items)}.")

    if not explanation_parts:
        return "Statistical signal detected against patient rolling baseline."

    return " | ".join(explanation_parts)
