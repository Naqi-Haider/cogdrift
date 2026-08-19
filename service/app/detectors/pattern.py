from typing import List, Tuple, Optional, Dict
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest


def build_daily_feature_vectors(
    daily_scores: List[Dict], game_sessions: List[Dict]
) -> pd.DataFrame:
    """Constructs 12-dimensional daily feature vectors per day played:
    - Game 1..10 scores (filled with patient mean if not played that day)
    - games_played
    - day_of_week (0=Mon, 6=Sun)
    """
    if not daily_scores:
        return pd.DataFrame()

    # Pre-index game sessions by date string to avoid O(N^2) filtering
    sess_by_date: Dict[str, Dict[int, float]] = {}
    for s in (game_sessions or []):
        d_str = str(s["played_at"])
        gid = int(s["game_id"])
        if 1 <= gid <= 10:
            if d_str not in sess_by_date:
                sess_by_date[d_str] = {}
            sess_by_date[d_str][gid] = float(s["score"])

    records = []
    for drow in daily_scores:
        d_str = str(drow["date"])
        games_played = int(drow["games_played"])
        dt = pd.to_datetime(d_str)
        day_of_week = dt.dayofweek

        day_map = sess_by_date.get(d_str, {})
        rec = {
            "date": d_str,
            "games_played": games_played,
            "day_of_week": day_of_week,
        }
        for gid in range(1, 11):
            rec[f"game_{gid}"] = day_map.get(gid, np.nan)
        records.append(rec)

    df_feats = pd.DataFrame(records)

    # Impute missing per-game scores with column mean, fallback to 5.0
    for gid in range(1, 11):
        col = f"game_{gid}"
        mean_val = df_feats[col].mean()
        if pd.isna(mean_val):
            mean_val = 5.0
        df_feats[col] = df_feats[col].fillna(mean_val)

    return df_feats


def detect_pattern_anomaly(
    daily_scores: List[Dict],
    game_sessions: List[Dict],
    contamination: float = 0.05,
    min_days: int = 14,
    pattern_persistence_days: int = 2,
    threshold: Optional[float] = None,
) -> Tuple[bool, Optional[float]]:
    """Fits Isolation Forest on patient history excluding the evaluation window.
    Requires >= min_days history.
    Returns (is_anomaly, isolation_raw_score).
    """
    if len(daily_scores) < min_days:
        return False, None

    df_feats = build_daily_feature_vectors(daily_scores, game_sessions)
    if len(df_feats) < min_days:
        return False, None

    feature_cols = [f"game_{g}" for g in range(1, 11)] + ["games_played", "day_of_week"]
    X = df_feats[feature_cols].values

    # Determine persistence evaluation window size (excluding window from training)
    n_eval = max(1, min(pattern_persistence_days, len(X) - min_days + 1))
    train_end = len(X) - n_eval

    if train_end < min_days - 1:
        # Fallback if remaining history is smaller than min_days - 1
        train_end = len(X) - 1
        n_eval = 1

    clf = IsolationForest(
        contamination=contamination,
        random_state=42,
        n_estimators=100,
    )
    clf.fit(X[:train_end])  # Fit on past history strictly before the evaluation window

    eval_vecs = X[-n_eval:]
    past_scores = clf.decision_function(eval_vecs)
    raw_score = float(np.max(past_scores))

    cutoff = threshold if threshold is not None else 0.0
    is_anomaly = bool(raw_score <= cutoff)

    return is_anomaly, raw_score



