"""
CogDrift Validation Engine & Grid Search Evaluator
=================================================

Loads synthetic dataset from --data, performs stratified ~70% train / ~30% validation split
by patient risk_profile, tunes Isolation Forest contamination rate & pattern persistence (>=2)
via 5-fold stratified cross-validation on the train set (with trend z_threshold=-2.0, persistence=3 fixed),
and selects parameters maximizing CV F1 subject to CV Stable FPR <= 0.30.

Precomputes raw scores per candidate persistence value using the CANONICAL detect_pattern_anomaly
production function directly, ensuring 100% execution parity by construction.
Reports empirical Precision, Recall, F1, per-detector contributions, trajectory-split Median Lag,
Stable FPR, Volatile FPR, and mutually-exclusive patient reconciliation.
"""

import argparse
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import List, Dict, Tuple, Optional
import numpy as np
import pandas as pd

# Add service directory to path to import CogDrift detectors
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "service"))

from app.detectors.trend import compute_rolling_baseline
from app.detectors.pattern import detect_pattern_anomaly


def parse_args():
    p = argparse.ArgumentParser(description="Evaluate CogDrift Anomaly Engine")
    p.add_argument("--data", type=str, default="./data", help="Directory containing synthetic CSVs")
    p.add_argument("--seed", type=int, default=42, help="Random seed for train/val split")
    return p.parse_args()


def load_dataset(data_dir: str):
    patients_df = pd.read_csv(os.path.join(data_dir, "patients.csv"))
    ia_df = pd.read_csv(os.path.join(data_dir, "initial_assessments.csv"))
    sessions_df = pd.read_csv(os.path.join(data_dir, "game_sessions.csv"))
    daily_df = pd.read_csv(os.path.join(data_dir, "daily_scores.csv"))
    ground_truth_df = pd.read_csv(os.path.join(data_dir, "ground_truth_events.csv"))

    risk_labels_path = os.path.join(data_dir, "patient_risk_labels.csv")
    if os.path.exists(risk_labels_path):
        risk_labels_df = pd.read_csv(risk_labels_path)
    else:
        risk_labels_df = pd.DataFrame()

    return patients_df, ia_df, sessions_df, daily_df, ground_truth_df, risk_labels_df


def precompute_patient_multipersistence(
    pid: str,
    ia_df: pd.DataFrame,
    sessions_df: pd.DataFrame,
    daily_df: pd.DataFrame,
    persistence_grid: List[int],
) -> Tuple[str, Dict[int, List[dict]]]:
    """Precomputes daily z_score and pattern raw_isolation_score per day for a patient
    for each candidate persistence value by calling CANONICAL detect_pattern_anomaly directly.
    """
    p_ia = ia_df[ia_df["patient_id"] == pid]
    initial_score = int(p_ia.iloc[0]["score"]) if not p_ia.empty else None

    p_daily = daily_df[daily_df["patient_id"] == pid].sort_values("date")
    p_sessions = sessions_df[sessions_df["patient_id"] == pid].sort_values("played_at")

    daily_scores = p_daily.to_dict("records")
    game_sessions = p_sessions.to_dict("records")

    records_by_p: Dict[int, List[dict]] = {p: [] for p in persistence_grid}

    for i in range(1, len(daily_scores) + 1):
        curr_daily = daily_scores[:i]

        mean_val, std_val, days_history = compute_rolling_baseline(curr_daily, initial_score, window=30)
        today_score = curr_daily[-1]["daily_cognitive_score"]
        z_t = (today_score - mean_val) / std_val if std_val > 0 else 0.0
        d_str = curr_daily[-1]["date"]

        for p_pers in persistence_grid:
            iso_score = None
            if i >= 14:
                # Call CANONICAL detect_pattern_anomaly with the exact candidate persistence value
                _, iso_score = detect_pattern_anomaly(
                    daily_scores=curr_daily,
                    game_sessions=game_sessions,
                    contamination=0.05,
                    min_days=14,
                    pattern_persistence_days=p_pers,
                    threshold=None,
                )

            records_by_p[p_pers].append({
                "date": d_str,
                "z_score": z_t,
                "iso_score": iso_score,
            })

    return pid, records_by_p


def _precompute_wrapper(args):
    pid, ia_sub, sess_sub, daily_sub, persistence_grid = args
    return precompute_patient_multipersistence(pid, ia_sub, sess_sub, daily_sub, persistence_grid)


def evaluate_patient_flags(
    patient_daily_records: List[dict],
    z_threshold: float,
    persistence_days: int,
    iso_threshold: Optional[float],
    detector_mode: str = "both",  # "both", "trend_only", "pattern_only"
) -> List[str]:
    """Returns list of flagged dates for a patient under given thresholds and detector mode."""
    flagged_dates = []
    consecutive_low_z = 0

    for rec in patient_daily_records:
        z = rec["z_score"]
        if z <= z_threshold:
            consecutive_low_z += 1
        else:
            consecutive_low_z = 0

        t_flag = (consecutive_low_z >= persistence_days)

        iso = rec["iso_score"]
        p_flag = (iso is not None and iso_threshold is not None and iso <= iso_threshold)

        if detector_mode == "trend_only":
            is_active = t_flag
        elif detector_mode == "pattern_only":
            is_active = p_flag
        else:
            is_active = t_flag or p_flag

        if is_active:
            flagged_dates.append(rec["date"])

    return flagged_dates


def compute_metrics(
    patient_ids: List[str],
    precomputed_records_map: Dict[str, List[dict]],
    ground_truth_df: pd.DataFrame,
    risk_labels_df: pd.DataFrame,
    iso_threshold: Optional[float],
    z_threshold: float = -2.0,
    persistence_days: int = 3,
):
    gt_map = ground_truth_df.set_index("patient_id").to_dict("index") if not ground_truth_df.empty else {}
    risk_map = risk_labels_df.set_index("patient_id")["risk_profile"].to_dict() if not risk_labels_df.empty else {}

    # Patient-level counters (mutually exclusive per patient!)
    patient_tp, patient_fn, patient_fp, patient_tn = 0, 0, 0, 0
    patient_premature = 0
    trend_tp, pattern_tp = 0, 0

    # Flag-level counters (instance level)
    total_valid_flags, total_early_or_false_flags = 0, 0

    sudden_lags, gradual_lags = [], []
    volatile_patient_count, volatile_flagged_count = 0, 0
    stable_patient_count, stable_flagged_count = 0, 0

    for pid in patient_ids:
        p_records = precomputed_records_map.get(pid, [])
        flagged_dates = evaluate_patient_flags(
            p_records, z_threshold, persistence_days, iso_threshold, detector_mode="both"
        )
        trend_flags = evaluate_patient_flags(
            p_records, z_threshold, persistence_days, iso_threshold, detector_mode="trend_only"
        )
        pattern_flags = evaluate_patient_flags(
            p_records, z_threshold, persistence_days, iso_threshold, detector_mode="pattern_only"
        )

        p_gt = gt_map.get(pid)
        p_risk = risk_map.get(pid)

        if p_risk == "volatile":
            volatile_patient_count += 1
            if flagged_dates:
                volatile_flagged_count += 1
        elif p_risk == "stable":
            stable_patient_count += 1
            if flagged_dates:
                stable_flagged_count += 1

        if p_gt:
            event_start = p_gt["event_start_date"]
            risk_profile = p_gt["risk_profile"]

            valid_flags = [d for d in flagged_dates if d >= event_start]
            valid_trend = [d for d in trend_flags if d >= event_start]
            valid_pattern = [d for d in pattern_flags if d >= event_start]

            if valid_flags:
                patient_tp += 1
                first_flag = min(valid_flags)
                lag_days = (pd.to_datetime(first_flag) - pd.to_datetime(event_start)).days
                if risk_profile == "sudden_decline":
                    sudden_lags.append(lag_days)
                elif risk_profile == "gradual_decline":
                    gradual_lags.append(lag_days)
            else:
                patient_fn += 1
                early_flags = [d for d in flagged_dates if d < event_start]
                if early_flags:
                    patient_premature += 1

            if valid_trend:
                trend_tp += 1
            if valid_pattern:
                pattern_tp += 1

            total_valid_flags += len(valid_flags)
            early_flags = [d for d in flagged_dates if d < event_start]
            total_early_or_false_flags += len(early_flags)

        else:
            if flagged_dates:
                patient_fp += 1
                total_early_or_false_flags += len(flagged_dates)
            else:
                patient_tn += 1

    # Verify strict reconciliation: TP + FP + FN + TN must equal patient count
    assert patient_tp + patient_fp + patient_fn + patient_tn == len(patient_ids), \
        f"Reconciliation error: TP({patient_tp}) + FP({patient_fp}) + FN({patient_fn}) + TN({patient_tn}) != {len(patient_ids)}"

    total_decline_patients = patient_tp + patient_fn
    patient_recall = patient_tp / total_decline_patients if total_decline_patients > 0 else 0.0
    trend_recall = trend_tp / total_decline_patients if total_decline_patients > 0 else 0.0
    pattern_recall = pattern_tp / total_decline_patients if total_decline_patients > 0 else 0.0

    total_flags = total_valid_flags + total_early_or_false_flags
    flag_precision = total_valid_flags / total_flags if total_flags > 0 else 0.0

    patient_precision = patient_tp / (patient_tp + patient_fp) if (patient_tp + patient_fp) > 0 else 0.0
    patient_f1 = 2 * (patient_precision * patient_recall) / (patient_precision + patient_recall) if (patient_precision + patient_recall) > 0 else 0.0

    volatile_fpr = volatile_flagged_count / volatile_patient_count if volatile_patient_count > 0 else 0.0
    stable_fpr = stable_flagged_count / stable_patient_count if stable_patient_count > 0 else 0.0

    median_sudden_lag = float(np.median(sudden_lags)) if sudden_lags else None
    median_gradual_lag = float(np.median(gradual_lags)) if gradual_lags else None

    return {
        "patient_recall": patient_recall,
        "trend_recall": trend_recall,
        "pattern_recall": pattern_recall,
        "patient_precision": patient_precision,
        "patient_f1": patient_f1,
        "flag_precision": flag_precision,
        "patient_tp": patient_tp,
        "patient_fp": patient_fp,
        "patient_fn": patient_fn,
        "patient_tn": patient_tn,
        "patient_premature": patient_premature,
        "total_flags": total_flags,
        "valid_flags": total_valid_flags,
        "false_flags": total_early_or_false_flags,
        "volatile_fpr": volatile_fpr,
        "volatile_flagged": volatile_flagged_count,
        "volatile_total": volatile_patient_count,
        "stable_fpr": stable_fpr,
        "stable_flagged": stable_flagged_count,
        "stable_total": stable_patient_count,
        "median_sudden_lag": median_sudden_lag,
        "median_gradual_lag": median_gradual_lag,
    }


def main():
    args = parse_args()
    patients_df, ia_df, sessions_df, daily_df, ground_truth_df, risk_labels_df = load_dataset(args.data)

    all_pids = patients_df["patient_id"].unique()
    risk_map = risk_labels_df.set_index("patient_id")["risk_profile"].to_dict() if not risk_labels_df.empty else {}

    # Stratified 70/30 split per risk profile group
    train_pids, val_pids = [], []
    grouped_pids = {}
    for pid in all_pids:
        r = risk_map.get(pid, "unknown")
        grouped_pids.setdefault(r, []).append(pid)

    for r_profile, p_list in sorted(grouped_pids.items()):
        p_arr = np.array(p_list)
        np.random.seed(args.seed)
        shuffled = np.random.permutation(p_arr)
        n_tr = max(1, int(len(shuffled) * 0.7))
        train_pids.extend(shuffled[:n_tr])
        val_pids.extend(shuffled[n_tr:])

    print(f"Dataset Loaded: {len(all_pids)} Total Patients")
    print("Stratified Group Counts:")
    for r_profile, p_list in sorted(grouped_pids.items()):
        tr_cnt = len([p for p in p_list if p in train_pids])
        va_cnt = len([p for p in p_list if p in val_pids])
        print(f"  - {r_profile:<18}: {len(p_list)} total (Train: {tr_cnt}, Val: {va_cnt})")

    print(f"Train set: {len(train_pids)} patients | Validation set: {len(val_pids)} patients")
    print("-" * 75)

    # Real candidate persistence grid (>= 2)
    pattern_persistence_grid = [2, 3]
    contamination_grid = [0.001, 0.002, 0.003, 0.005, 0.008, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10]

    cache_file = os.path.join(args.data, ".precomputed_cache.pkl")
    precomputed_by_p: Dict[int, Dict[str, List[dict]]] = {p: {} for p in pattern_persistence_grid}

    if os.path.exists(cache_file):
        import pickle
        print(f"Loading pre-computed signals from cache ({cache_file})...")
        with open(cache_file, "rb") as f:
            precomputed_by_p = pickle.load(f)
    else:
        print("Pre-computing daily signals per persistence candidate using canonical detect_pattern_anomaly...")
        tasks = [
            (
                pid,
                ia_df[ia_df["patient_id"] == pid],
                sessions_df[sessions_df["patient_id"] == pid],
                daily_df[daily_df["patient_id"] == pid],
                pattern_persistence_grid,
            )
            for pid in all_pids
        ]
        with ProcessPoolExecutor(max_workers=min(os.cpu_count() or 4, 8)) as executor:
            futures = [executor.submit(_precompute_wrapper, t) for t in tasks]
            for f in as_completed(futures):
                pid, p_records_by_p = f.result()
                for p_pers in pattern_persistence_grid:
                    precomputed_by_p[p_pers][pid] = p_records_by_p[p_pers]
        
        import pickle
        try:
            with open(cache_file, "wb") as f:
                pickle.dump(precomputed_by_p, f)
        except Exception:
            pass

    # Fixed statistical defaults for trend detector (COGDRIFT_SPEC §9)
    FIXED_Z_THRESHOLD = -2.0
    FIXED_TREND_PERSISTENCE = 3
    MAX_ALLOWED_STABLE_FPR = 0.30  # Clinical FPR ceiling constraint

    # 5-Fold Stratified Cross-Validation on 70% Train Set
    n_folds = 5
    fold_train_pids = [[] for _ in range(n_folds)]
    fold_val_pids = [[] for _ in range(n_folds)]

    for r_profile, p_list in sorted(grouped_pids.items()):
        tr_list = [p for p in p_list if p in train_pids]
        np.random.seed(args.seed + 1)
        shuffled_tr = np.random.permutation(np.array(tr_list))
        for idx, pid in enumerate(shuffled_tr):
            val_fold_idx = idx % n_folds
            for f in range(n_folds):
                if f == val_fold_idx:
                    fold_val_pids[f].append(pid)
                else:
                    fold_train_pids[f].append(pid)

    grid_results = []
    best_candidate = None
    best_constrained_f1 = -1.0

    print("\nRunning 5-Fold Stratified Cross-Validation on Train Set...")
    print(f"(Trend Detector fixed at z_thresh={FIXED_Z_THRESHOLD}, persistence={FIXED_TREND_PERSISTENCE})")
    print(f"(Selecting parameters maximizing CV F1 subject to CV Stable FPR <= {MAX_ALLOWED_STABLE_FPR})")

    for p_pers in pattern_persistence_grid:
        precomputed_map = precomputed_by_p[p_pers]

        # Collect train raw isolation scores specifically for this persistence configuration
        train_raw_scores = []
        for pid in train_pids:
            for rec in precomputed_map.get(pid, []):
                if rec["iso_score"] is not None:
                    train_raw_scores.append(rec["iso_score"])
        train_raw_scores = np.array(train_raw_scores)

        for contam in contamination_grid:
            thresh = float(np.percentile(train_raw_scores, contam * 100)) if len(train_raw_scores) > 0 else 0.0
            
            fold_f1s, fold_recalls, fold_precisions, fold_stable_fprs = [], [], [], []

            for f in range(n_folds):
                cv_val = fold_val_pids[f]
                res_f = compute_metrics(
                    cv_val, precomputed_map, ground_truth_df, risk_labels_df,
                    z_threshold=FIXED_Z_THRESHOLD, persistence_days=FIXED_TREND_PERSISTENCE,
                    iso_threshold=thresh,
                )
                fold_f1s.append(res_f["patient_f1"])
                fold_recalls.append(res_f["patient_recall"])
                fold_precisions.append(res_f["patient_precision"])
                fold_stable_fprs.append(res_f["stable_fpr"])

            mean_cv_f1 = float(np.mean(fold_f1s))
            mean_cv_recall = float(np.mean(fold_recalls))
            mean_cv_precision = float(np.mean(fold_precisions))
            mean_cv_stable_fpr = float(np.mean(fold_stable_fprs))

            full_train_res = compute_metrics(
                train_pids, precomputed_map, ground_truth_df, risk_labels_df,
                z_threshold=FIXED_Z_THRESHOLD, persistence_days=FIXED_TREND_PERSISTENCE,
                iso_threshold=thresh,
            )

            cand = {
                "contamination": contam,
                "pattern_persistence": p_pers,
                "threshold": thresh,
                "cv_f1": mean_cv_f1,
                "cv_recall": mean_cv_recall,
                "cv_precision": mean_cv_precision,
                "cv_stable_fpr": mean_cv_stable_fpr,
                "train_flag_precision": full_train_res["flag_precision"],
            }
            grid_results.append(cand)

            # Constrained optimization: max F1 subject to Stable FPR <= 0.30
            if mean_cv_stable_fpr <= MAX_ALLOWED_STABLE_FPR:
                if mean_cv_f1 > best_constrained_f1:
                    best_constrained_f1 = mean_cv_f1
                    best_candidate = cand

    # Fallback to min stable FPR if no candidate satisfies <= 0.30
    if best_candidate is None:
        best_candidate = min(grid_results, key=lambda x: x["cv_stable_fpr"])

    best_contam = best_candidate["contamination"]
    best_pat_pers = best_candidate["pattern_persistence"]
    best_thresh = best_candidate["threshold"]

    print("\n[5-Fold Train Cross-Validation Grid Search Matrix (Pattern Persistence >= 2)]")
    print(f"{'Contam':<10}{'PatPers':<10}{'Score Thresh':<16}{'CV Mean F1':<14}{'CV Recall':<12}{'CV Precision':<15}{'CV Stable FPR':<15}{'Train Flag Prec':<16}")
    for r in grid_results:
        is_win = "*" if (r["contamination"] == best_contam and r["pattern_persistence"] == best_pat_pers) else ""
        print(f"{r['contamination']:<10.3f}{r['pattern_persistence']:<10}{r['threshold']:<16.4f}{r['cv_f1']:<14.3f}{r['cv_recall']:<12.3f}{r['cv_precision']:<15.3f}{r['cv_stable_fpr']:<15.3f}{r['train_flag_precision']:<16.3f} {is_win}")

    print(f"\nWinning Parameters (from 5-Fold CV, Maximizing CV F1 under Stable FPR <= {MAX_ALLOWED_STABLE_FPR}):")
    print(f"  - Contamination: {best_contam:.3f}")
    print(f"  - Pattern Persistence: {best_pat_pers} consecutive days")
    print(f"  - Score Threshold: {best_thresh:.4f}")
    print(f"  - CV Mean F1: {best_candidate['cv_f1']:.3f} (CV Stable FPR: {best_candidate['cv_stable_fpr']:.3f})")
    print("=" * 85)

    # 2. Final Benchmark Evaluation on 30% Held-Out Validation Set
    print("\nRunning Benchmark Evaluation on 30% Held-Out Validation Set...")
    val_precomputed_map = precomputed_by_p[best_pat_pers]
    val_res = compute_metrics(
        val_pids, val_precomputed_map, ground_truth_df, risk_labels_df,
        z_threshold=FIXED_Z_THRESHOLD, persistence_days=FIXED_TREND_PERSISTENCE,
        iso_threshold=best_thresh,
    )

    print("\n" + "=" * 85)
    print("                 COGDRIFT VALIDATION REPORT                     ")
    print("=" * 85)
    print(f"Patient-Level Recall (Combined):     {val_res['patient_recall']:.3f} ({val_res['patient_tp']}/{val_res['patient_tp'] + val_res['patient_fn']})")
    print(f"  ├── Trend-Only Recall:             {val_res['trend_recall']:.3f}")
    print(f"  └── Pattern-Only Recall:           {val_res['pattern_recall']:.3f}")
    print(f"Patient-Level Precision:             {val_res['patient_precision']:.3f}")
    print(f"Patient-Level F1-Score:              {val_res['patient_f1']:.3f}")
    print(f"Flag-Level Precision (Instance):     {val_res['flag_precision']:.3f} ({val_res['valid_flags']}/{val_res['total_flags']} flags)")
    print(f"Stable Profile Patient FPR:          {val_res['stable_fpr']:.3f} ({val_res['stable_flagged']}/{val_res['stable_total']} stable patients)")
    print(f"Volatile Profile Patient FPR:        {val_res['volatile_fpr']:.3f} ({val_res['volatile_flagged']}/{val_res['volatile_total']} volatile patients)")
    print(f"Median Lag (Sudden Decline):         {val_res['median_sudden_lag']} days")
    print(f"Median Lag (Gradual Decline):        {val_res['median_gradual_lag']} days")
    print(f"Patient TP / FP / FN / TN:          {val_res['patient_tp']} / {val_res['patient_fp']} / {val_res['patient_fn']} / {val_res['patient_tn']}")
    print(f"Premature Flags on Decline Patients: {val_res['patient_premature']}")
    print(f"Reconciliation Check:                {val_res['patient_tp']} TP + {val_res['patient_fp']} FP + {val_res['patient_fn']} FN + {val_res['patient_tn']} TN = {val_res['patient_tp'] + val_res['patient_fp'] + val_res['patient_fn'] + val_res['patient_tn']} (Total Validation Patients: {len(val_pids)})")
    print("=" * 85)


if __name__ == "__main__":
    main()
