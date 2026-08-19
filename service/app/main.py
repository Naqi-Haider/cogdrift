import uuid
import re
from datetime import datetime, date, timedelta
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
import numpy as np

from app.database import get_db, init_db
from app.models import Patient, GameCatalog, InitialAssessment, GameSession, DailyScore, Flag, AuditLog
from app.schemas import (
    SessionIngestRequest,
    SessionIngestResponse,
    BaselineResponse,
    TrendPoint,
    TrendResponse,
    AnomalyMarker,
    FlagRead,
    ReviewRequest,
    BulkReviewRequest,
    CaregiverMessage,
    TokenPayload,
    MANDATORY_DISCLAIMER,
)
from app.detectors.trend import compute_rolling_baseline
from app.events import publish_score_ingested
from app.auth import require_role, SEEDED_CLINICIAN_TOKEN, SEEDED_CAREGIVER_TOKEN
from app.config import settings

app = FastAPI(
    title="CogDrift API Engine",
    description="Clinician-gated anomaly-monitoring service for cognitive rehabilitation game data",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    try:
        await init_db()
    except Exception as e:
        print(f"DB Init Warning: {e}")

    try:
        await seed_initial_data_if_empty()
    except Exception as e:
        print(f"Seed Warning: {e}")


# Deterministic pattern-based screening for caregiver notes
MEDICATION_LANGUAGE_REGEX = re.compile(
    r"\b("
    r"\d+\s*mg|\d+\s*mcg|\d+\s*g|\d+\s*ml|\d+\s*pills?|\d+\s*tablets?|"
    r"milligram|milligrams|microgram|micrograms|gram|grams|milliliter|milliliters|"
    r"dosage|dose|doses|prescribe|prescribes|prescribed|prescribing|prescription|medication|medications|meds|pharmacy|"
    r"donepezil|memantine|rivastigmine|galantamine|aducanumab|lecanemab|donanemab|"
    r"namenda|aricept|exelon|razadyne|leqembi|kisunla|"
    r"titrat\w*|increase\s+dose|decrease\s+dose|daily\s+dose"
    r")\b",
    re.IGNORECASE,
)


def validate_caregiver_notes(notes: Optional[str]) -> None:
    """
    Pattern-based screening to block medication/dosage instructions in free-text guidance notes.
    CogDrift is a statistical anomaly monitoring tool, not a clinical prescribing system.
    """
    if not notes:
        return
    if MEDICATION_LANGUAGE_REGEX.search(notes):
        raise HTTPException(
            status_code=400,
            detail="This field is for activity and engagement guidance only. Medication or treatment changes must go through your clinical prescribing system — CogDrift does not transmit that information.",
        )


ISOLATION_SEVERITY_THRESHOLD = 0.0097  # from evaluate.py 5-fold CV grid search, see COGDRIFT_SPEC.md §9


def compute_severity(
    detector_type: str,
    z_score: Optional[float],
    isolation_score: Optional[float],
) -> str:
    """
    Computes flag severity per Section 15 Item 5:
    - HIGH = BOTH detectors fired
    - MODERATE = single-detector-strong (z_score <= -3.0 or isolation_score <= ISOLATION_SEVERITY_THRESHOLD)
    - LOW = single-detector-moderate (-3.0 < z_score <= -2.0 or isolation_score < 0)
    """
    if detector_type == "BOTH":
        return "HIGH"

    is_strong = (z_score is not None and z_score <= -3.0) or (
        isolation_score is not None and isolation_score <= ISOLATION_SEVERITY_THRESHOLD
    )
    if is_strong:
        return "MODERATE"

    return "LOW"


async def seed_initial_data_if_empty():
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(Flag))
        flags = res.scalars().all()
        if not flags:
            from app.worker import evaluate_patient_anomalies
            target_date = date.today().isoformat()
            demo_patients = ["P0004", "P0007", "P0012", "P0021", "P0028", "P0032", "P0040"]
            for pid in demo_patients:
                try:
                    await evaluate_patient_anomalies(pid, target_date)
                except Exception as e:
                    print(f"Seeding warning for {pid}: {e}")


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "CogDrift Engine",
        "disclaimer": MANDATORY_DISCLAIMER,
        "dev_seeded_tokens": {
            "clinician_token": SEEDED_CLINICIAN_TOKEN,
            "caregiver_token": SEEDED_CAREGIVER_TOKEN,
        },
    }


# ---------------------------------------------------------------------------
# Data Ingestion Endpoints
# ---------------------------------------------------------------------------

@app.post("/ingest/session", response_model=SessionIngestResponse)
async def ingest_game_session(
    body: SessionIngestRequest,
    db: AsyncSession = Depends(get_db),
):
    session_uuid = body.session_id or uuid.uuid4()
    session = GameSession(
        session_id=session_uuid,
        patient_id=body.patient_id,
        game_id=body.game_id,
        score=body.score,
        played_at=body.played_at,
    )
    db.add(session)
    await db.commit()

    # Recompute daily aggregate for patient
    stmt = select(GameSession).where(
        and_(
            GameSession.patient_id == body.patient_id,
            GameSession.played_at == body.played_at,
        )
    )
    res = await db.execute(stmt)
    day_sessions = res.scalars().all()

    scores = [s.score for s in day_sessions]
    daily_score_val = float(np.mean(scores)) if scores else float(body.score)

    ds_stmt = select(DailyScore).where(
        and_(
            DailyScore.patient_id == body.patient_id,
            DailyScore.date == body.played_at,
        )
    )
    ds_res = await db.execute(ds_stmt)
    existing_ds = ds_res.scalar_one_or_none()

    if existing_ds:
        existing_ds.games_played = len(day_sessions)
        existing_ds.daily_cognitive_score = daily_score_val
    else:
        new_ds = DailyScore(
            patient_id=body.patient_id,
            date=body.played_at,
            games_played=len(day_sessions),
            daily_cognitive_score=daily_score_val,
        )
        db.add(new_ds)

    await db.commit()

    # Publish RabbitMQ event
    await publish_score_ingested(
        patient_id=body.patient_id,
        played_at=body.played_at.isoformat(),
        session_id=str(session_uuid),
    )

    return SessionIngestResponse(
        session_id=session_uuid,
        patient_id=body.patient_id,
        game_id=body.game_id,
        score=body.score,
        played_at=body.played_at,
    )


# ---------------------------------------------------------------------------
# Baseline & Trend Endpoints
# ---------------------------------------------------------------------------

@app.get("/patients/{patient_id}/baseline", response_model=BaselineResponse)
async def get_patient_baseline(
    patient_id: str,
    db: AsyncSession = Depends(get_db),
):
    ia_res = await db.execute(select(InitialAssessment).where(InitialAssessment.patient_id == patient_id))
    ia = ia_res.scalar_one_or_none()
    initial_score = ia.score if ia else None

    ds_res = await db.execute(
        select(DailyScore).where(DailyScore.patient_id == patient_id).order_by(DailyScore.date.asc())
    )
    daily_scores = ds_res.scalars().all()
    scores_list = [{"date": s.date.isoformat(), "daily_cognitive_score": float(s.daily_cognitive_score)} for s in daily_scores]

    mean_val, std_val, days_h = compute_rolling_baseline(
        scores_list, initial_score=initial_score, window=settings.BASELINE_WINDOW_DAYS
    )

    cold_start_eligible = days_h >= settings.COLD_START_MIN_DAYS

    return BaselineResponse(
        patient_id=patient_id,
        rolling_mean=round(mean_val, 2) if mean_val is not None else None,
        rolling_std=round(std_val, 2) if std_val is not None else None,
        days_history=days_h,
        cold_start_eligible=cold_start_eligible,
        initial_assessment_score=initial_score,
    )


@app.get("/patients/{patient_id}/trend", response_model=TrendResponse)
async def get_patient_trend(
    patient_id: str,
    db: AsyncSession = Depends(get_db),
):
    ia_res = await db.execute(select(InitialAssessment).where(InitialAssessment.patient_id == patient_id))
    ia = ia_res.scalar_one_or_none()
    initial_score = ia.score if ia else None

    ds_res = await db.execute(
        select(DailyScore).where(DailyScore.patient_id == patient_id).order_by(DailyScore.date.asc())
    )
    daily_scores_objs = ds_res.scalars().all()

    flags_res = await db.execute(select(Flag).where(Flag.patient_id == patient_id))
    flags = flags_res.scalars().all()
    flag_dates = {f.date for f in flags}

    anomalies_list = [
        AnomalyMarker(
            date=f.date,
            flag_id=f.flag_id,
            detector_type=f.detector_type,
            status=f.status,
            z_score=f.z_score,
            isolation_score=f.isolation_score,
        )
        for f in flags
    ]

    points = []
    accumulated = []
    for s in daily_scores_objs:
        accumulated.append({"date": s.date.isoformat(), "daily_cognitive_score": float(s.daily_cognitive_score)})
        mean_val, std_val, days_h = compute_rolling_baseline(
            accumulated, initial_score=initial_score, window=settings.BASELINE_WINDOW_DAYS
        )
        z = (float(s.daily_cognitive_score) - mean_val) / std_val if std_val > 0 else 0.0
        upper = round(min(10.0, mean_val + 2.0 * std_val), 2)
        lower = round(max(0.0, mean_val - 2.0 * std_val), 2)

        points.append(
            TrendPoint(
                date=s.date,
                daily_cognitive_score=float(s.daily_cognitive_score),
                rolling_mean=round(mean_val, 2),
                rolling_std=round(std_val, 2),
                upper_bound=upper,
                lower_bound=lower,
                z_score=round(z, 2),
                is_anomaly=(s.date in flag_dates),
            )
        )

    return TrendResponse(patient_id=patient_id, points=points, anomalies=anomalies_list)


# ---------------------------------------------------------------------------
# Clinician Review Queue & Flag Endpoints (Clinician-Only JWT Protected)
# ---------------------------------------------------------------------------

@app.get("/flags", response_model=List[FlagRead])
async def list_flags(
    status_filter: Optional[str] = Query(None, alias="status"),
    patient_id: Optional[str] = Query(None, alias="patient_id"),
    user: TokenPayload = Depends(require_role(["clinician"])),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Flag)
    if status_filter:
        stmt = stmt.where(Flag.status == status_filter)
    if patient_id:
        stmt = stmt.where(Flag.patient_id == patient_id)
    stmt = stmt.order_by(Flag.created_at.desc())

    res = await db.execute(stmt)
    flags = res.scalars().all()

    result = []
    for f in flags:
        sev = compute_severity(f.detector_type, f.z_score, f.isolation_score)
        f_read = FlagRead.model_validate(f)
        f_read.severity = sev
        result.append(f_read)

    return result


@app.post("/reset-flags")
async def reset_demo_flags(
    user: TokenPayload = Depends(require_role(["clinician"])),
    db: AsyncSession = Depends(get_db),
):
    """Dev/Demo helper: Resets all flags back to pending status for demo testing."""
    stmt = select(Flag)
    res = await db.execute(stmt)
    flags = res.scalars().all()

    for f in flags:
        f.status = "pending"
        f.reviewed_by = None
        f.reviewed_at = None
        f.clinician_notes = None

        # Audit log entry with actor="system_diagnostic" per Section 15 Item 3
        audit = AuditLog(
            flag_id=f.flag_id,
            actor="system_diagnostic",
            action="reset_demo_flags",
            timestamp=datetime.utcnow(),
        )
        db.add(audit)

    await db.commit()
    return {"status": "success", "message": f"Reset {len(flags)} flags back to pending status", "count": len(flags)}


@app.get("/flags/{flag_id}", response_model=FlagRead)
async def get_flag_detail(
    flag_id: uuid.UUID,
    user: TokenPayload = Depends(require_role(["clinician"])),
    db: AsyncSession = Depends(get_db),
):
    flag = await db.get(Flag, flag_id)
    if not flag:
        raise HTTPException(status_code=404, detail="Flag not found")
    
    sev = compute_severity(flag.detector_type, flag.z_score, flag.isolation_score)
    f_read = FlagRead.model_validate(flag)
    f_read.severity = sev
    return f_read


@app.post("/flags/{flag_id}/review", response_model=FlagRead)
async def review_flag(
    flag_id: uuid.UUID,
    body: ReviewRequest,
    user: TokenPayload = Depends(require_role(["clinician"])),
    db: AsyncSession = Depends(get_db),
):
    if body.decision not in ("confirmed", "dismissed", "needs_more_data"):
        raise HTTPException(
            status_code=400,
            detail="Decision must be 'confirmed', 'dismissed', or 'needs_more_data'",
        )

    # Server-side pattern screening to block medication/dosage instructions
    validate_caregiver_notes(body.notes)

    flag = await db.get(Flag, flag_id)
    if not flag:
        raise HTTPException(status_code=404, detail="Flag not found")

    flag.status = body.decision
    flag.reviewed_by = user.sub
    flag.reviewed_at = datetime.utcnow()
    flag.clinician_notes = body.notes

    audit = AuditLog(
        flag_id=flag.flag_id,
        actor=user.sub,
        action=f"review_{body.decision}",
        timestamp=datetime.utcnow(),
    )
    db.add(audit)
    await db.commit()
    await db.refresh(flag)

    sev = compute_severity(flag.detector_type, flag.z_score, flag.isolation_score)
    f_read = FlagRead.model_validate(flag)
    f_read.severity = sev
    return f_read


@app.post("/flags/bulk-review")
async def bulk_review_flags(
    body: BulkReviewRequest,
    user: TokenPayload = Depends(require_role(["clinician"])),
    db: AsyncSession = Depends(get_db),
):
    """Bulk review endpoint for LOW severity signals per Section 15 Item 6."""
    if body.decision not in ("confirmed", "dismissed", "needs_more_data"):
        raise HTTPException(status_code=400, detail="Invalid decision")

    # Server-side pattern screening to block medication/dosage instructions
    validate_caregiver_notes(body.notes)

    res = await db.execute(select(Flag).where(Flag.flag_id.in_(body.flag_ids)))
    flags = res.scalars().all()

    # Enforce mandatory single-item review for HIGH or MODERATE flags
    for f in flags:
        sev = compute_severity(f.detector_type, f.z_score, f.isolation_score)
        if sev in ("HIGH", "MODERATE"):
            raise HTTPException(
                status_code=400,
                detail=f"Single-item review is mandatory for flag {f.flag_id} (severity: {sev}). Bulk review is restricted to LOW severity signals.",
            )

    updated_count = 0
    for f in flags:
        f.status = body.decision
        f.reviewed_by = user.sub
        f.reviewed_at = datetime.utcnow()
        f.clinician_notes = body.notes or "Bulk reviewed by clinician"
        audit = AuditLog(
            flag_id=f.flag_id,
            actor=user.sub,
            action=f"bulk_review_{body.decision}",
            timestamp=datetime.utcnow(),
        )
        db.add(audit)
        updated_count += 1

    await db.commit()
    return {"status": "success", "updated_count": updated_count}


# ---------------------------------------------------------------------------
# Caregiver Endpoint (Caregiver-Only JWT Protected & Scoped to patient_ids)
# ---------------------------------------------------------------------------

@app.get("/caregiver/{patient_id}/messages", response_model=List[CaregiverMessage])
async def get_caregiver_messages(
    patient_id: str,
    user: TokenPayload = Depends(require_role(["caregiver"])),
    db: AsyncSession = Depends(get_db),
):
    # Enforce server-side patient_id scoping per Section 7 & Section 15 Item 1
    if patient_id not in (user.patient_ids or []):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Caregiver JWT is not authorized for patient '{patient_id}'. Authorized patient IDs: {user.patient_ids}",
        )

    stmt = select(Flag).where(
        and_(
            Flag.patient_id == patient_id,
            Flag.status == "confirmed",
        )
    ).order_by(Flag.reviewed_at.desc())

    res = await db.execute(stmt)
    confirmed_flags = res.scalars().all()

    messages = []
    for f in confirmed_flags:
        msg = f.clinician_notes if f.clinician_notes else f.explanation
        messages.append(
            CaregiverMessage(
                flag_id=f.flag_id,
                patient_id=f.patient_id,
                date=f.date,
                reviewed_at=f.reviewed_at,
                clinician_approved_message=msg,
                disclaimer=MANDATORY_DISCLAIMER,
            )
        )
    return messages
