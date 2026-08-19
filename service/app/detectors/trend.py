from typing import List, Tuple, Optional, Dict
import numpy as np
import pandas as pd


def compute_rolling_baseline(
    daily_scores: List[Dict],  # list of dicts with 'date' and 'daily_cognitive_score'
    initial_score: Optional[int] = None,
    window: int = 30,
) -> Tuple[float, float, int]:
    """Computes patient rolling mean and std over specified window.
    Seeds cold start (<14 days) using initial_score prior.
    Returns (rolling_mean, rolling_std, days_history).
    """
    n_days = len(daily_scores)
    if n_days == 0:
        if initial_score is not None:
            return float(initial_score), 1.0, 0
        return 7.0, 1.0, 0

    scores = [float(s["daily_cognitive_score"]) for s in daily_scores[-window:]]

    if n_days < 14 and initial_score is not None:
        # Weighted prior: initial_score weighted by (14 - n_days)
        prior_weight = max(0, 14 - n_days)
        combined_scores = scores + [float(initial_score)] * prior_weight
        mean_val = float(np.mean(combined_scores))
        std_val = float(np.std(combined_scores, ddof=1)) if len(combined_scores) > 1 else 1.0
    else:
        mean_val = float(np.mean(scores))
        std_val = float(np.std(scores, ddof=1)) if len(scores) > 1 else 1.0

    std_val = max(std_val, 0.3)  # Floor std to prevent division by near-zero
    return mean_val, std_val, n_days


def detect_trend_anomaly(
    daily_scores: List[Dict],
    initial_score: Optional[int] = None,
    window: int = 30,
    z_threshold: float = -2.0,
    persistence_days: int = 3,
) -> Tuple[bool, Optional[float], Optional[float], Optional[float]]:
    """Detects if patient daily score has sustained z_score < z_threshold for persistence_days.
    Returns (is_anomaly, latest_z_score, rolling_mean, rolling_std).
    """
    if len(daily_scores) < persistence_days:
        return False, None, None, None

    z_scores = []
    # Calculate rolling z-score for recent days to check persistence
    for i in range(len(daily_scores) - persistence_days, len(daily_scores)):
        historical = daily_scores[: i + 1]
        history_window = historical[:-1]  # history prior to target day
        target_score = float(historical[-1]["daily_cognitive_score"])

        mean_val, std_val, _ = compute_rolling_baseline(
            history_window if history_window else historical,
            initial_score=initial_score,
            window=window,
        )
        z = (target_score - mean_val) / std_val
        z_scores.append((z, mean_val, std_val))

    latest_z, latest_mean, latest_std = z_scores[-1]
    
    # Flag condition: z < z_threshold for ALL of the last persistence_days
    is_anomaly = all(z < z_threshold for z, _, _ in z_scores)
    return is_anomaly, float(latest_z), float(latest_mean), float(latest_std)
