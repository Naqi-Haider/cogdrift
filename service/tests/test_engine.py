import pytest
from datetime import date, timedelta
from fastapi import HTTPException
from fastapi.testclient import TestClient
import jwt

from app.detectors.trend import compute_rolling_baseline, detect_trend_anomaly
from app.detectors.pattern import build_daily_feature_vectors, detect_pattern_anomaly
from app.detectors.explainer import generate_flag_explanation
from app.schemas import FlagRead, MANDATORY_DISCLAIMER
from app.auth import create_token, decode_token
from app.main import app, get_db
from app.config import settings


def test_trend_detector_baseline():
    scores = [{"date": f"2026-01-{i+1:02d}", "daily_cognitive_score": 7.0} for i in range(20)]
    mean_val, std_val, days_h = compute_rolling_baseline(scores, initial_score=8, window=30)
    assert mean_val == 7.0
    assert std_val >= 0.3
    assert days_h == 20


def test_trend_anomaly_persistence():
    # 20 days normal scores
    scores = [{"date": f"2026-01-{i+1:02d}", "daily_cognitive_score": 7.5} for i in range(20)]
    # Drop for 3 consecutive days
    scores.append({"date": "2026-01-21", "daily_cognitive_score": 2.0})
    scores.append({"date": "2026-01-22", "daily_cognitive_score": 2.0})
    scores.append({"date": "2026-01-23", "daily_cognitive_score": 2.0})

    is_anomaly, z, m, s = detect_trend_anomaly(scores, initial_score=8, z_threshold=-2.0, persistence_days=3)
    assert is_anomaly is True
    assert z < -2.0


def test_pattern_anomaly_detector_window_parity():
    daily_scores = [
        {"date": f"2026-01-{i+1:02d}", "daily_cognitive_score": 7.5, "games_played": 3}
        for i in range(20)
    ]
    # Add drops
    daily_scores.append({"date": "2026-01-21", "daily_cognitive_score": 2.0, "games_played": 1})
    daily_scores.append({"date": "2026-01-22", "daily_cognitive_score": 2.0, "games_played": 1})
    daily_scores.append({"date": "2026-01-23", "daily_cognitive_score": 2.0, "games_played": 1})

    game_sessions = [
        {"played_at": f"2026-01-{i+1:02d}", "game_id": 1, "score": 8.0}
        for i in range(20)
    ]
    game_sessions.append({"played_at": "2026-01-21", "game_id": 1, "score": 2.0})
    game_sessions.append({"played_at": "2026-01-22", "game_id": 1, "score": 2.0})
    game_sessions.append({"played_at": "2026-01-23", "game_id": 1, "score": 2.0})

    for p_pers in [2, 3]:
        is_anom_none, raw_score = detect_pattern_anomaly(
            daily_scores, game_sessions, pattern_persistence_days=p_pers, threshold=None
        )
        assert raw_score is not None

        # Verify that passing threshold=T yields anomaly iff raw_score <= T
        is_anom_low, _ = detect_pattern_anomaly(
            daily_scores, game_sessions, pattern_persistence_days=p_pers, threshold=raw_score - 0.05
        )
        assert is_anom_low is False

        is_anom_high, _ = detect_pattern_anomaly(
            daily_scores, game_sessions, pattern_persistence_days=p_pers, threshold=raw_score + 0.05
        )
        assert is_anom_high is True


def test_jwt_auth_positive_and_negative_cases():
    # 1. Happy path: valid token decodes
    token = create_token("doc_123", "clinician")
    payload = decode_token(token)
    assert payload.sub == "doc_123"
    assert payload.role == "clinician"

    # 2. Negative case: tampered signature fails
    tampered_token = token[:-5] + "XXXXX"
    with pytest.raises(HTTPException) as exc_info:
        decode_token(tampered_token)
    assert exc_info.value.status_code == 401
    assert "Invalid authentication token" in exc_info.value.detail

    # 3. Negative case: token signed with wrong secret fails
    forged_token = jwt.encode({"sub": "hacker", "role": "clinician"}, "wrong_secret_key", algorithm="HS256")
    with pytest.raises(HTTPException) as exc_info:
        decode_token(forged_token)
    assert exc_info.value.status_code == 401

    # 4. Negative case: expired token fails
    expired_token = create_token("doc_123", "clinician", expires_delta=timedelta(seconds=-10))
    with pytest.raises(HTTPException) as exc_info:
        decode_token(expired_token)
    assert exc_info.value.status_code == 401
    assert "expired" in exc_info.value.detail.lower()


def test_explainer_output():
    exp_trend = generate_flag_explanation("TREND", -2.45, None, 3, [], "2026-01-23")
    assert "z = -2.45" in exp_trend
    assert "3 consecutive days" in exp_trend

    exp_pattern = generate_flag_explanation("PATTERN", None, -0.12, 3, [], "2026-01-23")
    assert "Isolation score: -0.120" in exp_pattern


def test_flag_disclaimer_schema():
    flag_data = {
        "flag_id": "123e4567-e89b-12d3-a456-426614174000",
        "patient_id": "P0001",
        "created_at": "2026-01-23T10:00:00",
        "date": "2026-01-23",
        "detector_type": "TREND",
        "z_score": -2.4,
        "isolation_score": None,
        "status": "pending",
        "explanation": "Test explanation",
    }
    flag_model = FlagRead(**flag_data)
    assert flag_model.disclaimer == MANDATORY_DISCLAIMER


def test_guidance_note_content_filter():
    from app.main import validate_caregiver_notes

    # Legitimate non-clinical engagement guidance notes pass
    validate_caregiver_notes("Continue daily rehabilitation exercises as scheduled.")
    validate_caregiver_notes("Exercise engagement has dropped; recommend checking in with the patient.")

    # Medication and dosage pattern text raises HTTPException 400
    with pytest.raises(HTTPException) as exc_info:
        validate_caregiver_notes("increase the dosage to 10mg")
    assert exc_info.value.status_code == 400

    with pytest.raises(HTTPException) as exc_info:
        validate_caregiver_notes("10 milligrams daily")
    assert exc_info.value.status_code == 400

    with pytest.raises(HTTPException) as exc_info:
        validate_caregiver_notes("prescribe memantine for patient")
    assert exc_info.value.status_code == 400


def test_caregiver_rbac_endpoint_scoping():
    class DummyAsyncSession:
        async def execute(self, stmt):
            class DummyResult:
                def scalars(self):
                    class DummyScalars:
                        def all(self):
                            return []
                    return DummyScalars()
            return DummyResult()

    async def override_get_db():
        yield DummyAsyncSession()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    try:
        # Caregiver token scoped only to P0004 and P0007
        cg_token = create_token("cg_01", "caregiver", patient_ids=["P0004", "P0007"])
        clinician_token = create_token("doc_01", "clinician")

        # 1. Scoped patient access succeeds (200)
        res_ok = client.get(
            "/caregiver/P0004/messages",
            headers={"Authorization": f"Bearer {cg_token}"}
        )
        assert res_ok.status_code == 200

        # 2. Unscoped patient access is blocked with 403 Forbidden
        res_unauth_patient = client.get(
            "/caregiver/P0012/messages",
            headers={"Authorization": f"Bearer {cg_token}"}
        )
        assert res_unauth_patient.status_code == 403
        assert "not authorized" in res_unauth_patient.json()["detail"].lower()

        # 3. Wrong role (clinician token on caregiver endpoint) is blocked with 403 Forbidden
        res_wrong_role = client.get(
            "/caregiver/P0004/messages",
            headers={"Authorization": f"Bearer {clinician_token}"}
        )
        assert res_wrong_role.status_code == 403

        # 4. Tampered token signature is blocked with 401 Unauthorized
        tampered_token = cg_token[:-5] + "XXXXX"
        res_tampered = client.get(
            "/caregiver/P0004/messages",
            headers={"Authorization": f"Bearer {tampered_token}"}
        )
        assert res_tampered.status_code == 401
    finally:
        app.dependency_overrides.pop(get_db, None)
