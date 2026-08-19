import asyncio
import logging
from datetime import datetime, date
from typing import Dict, List, Optional
from sqlalchemy import select, and_
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import Patient, InitialAssessment, DailyScore, GameSession, Flag, AuditLog
from app.detectors.trend import detect_trend_anomaly
from app.detectors.pattern import detect_pattern_anomaly
from app.detectors.explainer import generate_flag_explanation
from app.events import consume_score_ingested_events

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cogdrift.worker")


async def evaluate_patient_anomalies(patient_id: str, target_date_str: Optional[str] = None):
    """Recomputes detectors for patient_id and writes flag if anomaly detected."""
    async with AsyncSessionLocal() as session:
        # 1. Fetch initial assessment
        ia_stmt = select(InitialAssessment).where(InitialAssessment.patient_id == patient_id)
        ia_res = await session.execute(ia_stmt)
        init_assess = ia_res.scalar_one_or_none()
        initial_score = init_assess.score if init_assess else None

        # 2. Fetch daily scores sorted by date
        ds_stmt = (
            select(DailyScore)
            .where(DailyScore.patient_id == patient_id)
            .order_by(DailyScore.date.asc())
        )
        ds_res = await session.execute(ds_stmt)
        daily_scores_objs = ds_res.scalars().all()
        if not daily_scores_objs:
            return

        daily_scores = [
            {
                "patient_id": s.patient_id,
                "date": s.date.isoformat(),
                "games_played": s.games_played,
                "daily_cognitive_score": float(s.daily_cognitive_score),
            }
            for s in daily_scores_objs
        ]

        if target_date_str:
            daily_scores = [s for s in daily_scores if s["date"] <= target_date_str]

        if not daily_scores:
            return

        target_date = daily_scores[-1]["date"]

        # 3. Fetch game sessions
        gs_stmt = (
            select(GameSession)
            .where(
                and_(
                    GameSession.patient_id == patient_id,
                    GameSession.played_at <= date.fromisoformat(target_date),
                )
            )
            .order_by(GameSession.played_at.asc())
        )
        gs_res = await session.execute(gs_stmt)
        game_sessions = [
            {
                "session_id": str(s.session_id),
                "patient_id": s.patient_id,
                "game_id": s.game_id,
                "score": s.score,
                "played_at": s.played_at.isoformat(),
            }
            for s in gs_res.scalars().all()
        ]

        # 4. Run Detectors
        trend_anomaly, z_score, rolling_mean, rolling_std = detect_trend_anomaly(
            daily_scores=daily_scores,
            initial_score=initial_score,
            window=settings.BASELINE_WINDOW_DAYS,
            z_threshold=settings.TREND_Z_THRESHOLD,
            persistence_days=settings.TREND_PERSISTENCE_DAYS,
        )

        from app.main import ISOLATION_SEVERITY_THRESHOLD

        pattern_anomaly, iso_score = detect_pattern_anomaly(
            daily_scores=daily_scores,
            game_sessions=game_sessions,
            contamination=settings.ISOLATION_FOREST_CONTAMINATION,
            min_days=settings.COLD_START_MIN_DAYS,
            pattern_persistence_days=settings.PATTERN_PERSISTENCE_DAYS,
            threshold=ISOLATION_SEVERITY_THRESHOLD,
        )

        if not (trend_anomaly or pattern_anomaly):
            return

        detector_type = "BOTH" if (trend_anomaly and pattern_anomaly) else ("TREND" if trend_anomaly else "PATTERN")

        # 5. Check if flag already exists for this patient & date
        target_date_obj = date.fromisoformat(target_date)
        existing_flag_stmt = select(Flag).where(
            and_(
                Flag.patient_id == patient_id,
                Flag.date == target_date_obj,
                Flag.status == "pending",
            )
        )
        existing = await session.execute(existing_flag_stmt)
        if existing.scalar_one_or_none():
            logger.info(f"Pending flag already exists for patient {patient_id} on {target_date}")
            return

        # 6. Generate explanation & create flag
        explanation = generate_flag_explanation(
            detector_type=detector_type,
            z_score=z_score,
            isolation_score=iso_score,
            persistence_days=settings.TREND_PERSISTENCE_DAYS,
            game_sessions=game_sessions,
            target_date=target_date,
        )

        new_flag = Flag(
            patient_id=patient_id,
            date=target_date_obj,
            detector_type=detector_type,
            z_score=z_score,
            isolation_score=iso_score,
            status="pending",
            explanation=explanation,
        )
        session.add(new_flag)
        await session.flush()

        # Audit log creation
        audit = AuditLog(
            flag_id=new_flag.flag_id,
            actor="drift_worker",
            action="flag_created",
            timestamp=datetime.utcnow(),
        )
        session.add(audit)
        await session.commit()
        logger.info(f"Flag created for patient {patient_id} on {target_date}: {detector_type}")


async def handle_event(data: dict):
    patient_id = data.get("patient_id")
    played_at = data.get("played_at")
    if patient_id:
        logger.info(f"Processing score.ingested event for patient {patient_id}")
        await evaluate_patient_anomalies(patient_id, target_date_str=played_at)


async def nightly_reconciliation_pass():
    logger.info("Starting APScheduler nightly reconciliation pass...")
    async with AsyncSessionLocal() as session:
        patients_stmt = select(Patient.patient_id)
        res = await session.execute(patients_stmt)
        pids = res.scalars().all()
        for pid in pids:
            await evaluate_patient_anomalies(pid)
    logger.info("Nightly reconciliation pass completed.")


async def main():
    scheduler = AsyncIOScheduler()
    # Run reconciliation pass nightly at 02:00
    scheduler.add_job(nightly_reconciliation_pass, "cron", hour=2, minute=0)
    scheduler.start()

    logger.info("CogDrift Worker started. Consuming RabbitMQ events...")
    try:
        await consume_score_ingested_events(handle_event)
    except Exception as e:
        logger.error(f"Worker event consumption error: {e}")
        # Keep process alive for scheduler if RabbitMQ unavailable
        while True:
            await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
