import os
import sys
import asyncio
import uuid
from datetime import date
import pandas as pd
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "service"))

from app.config import settings
from app.models import Base, Patient, GameCatalog, InitialAssessment, GameSession, DailyScore, Flag, AuditLog
from app.worker import evaluate_patient_anomalies

DB_URL = "postgresql+asyncpg://cogdrift:dev_only_change_me@localhost:5432/cogdrift"
engine = create_async_engine(DB_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)


async def seed():
    data_dir = "./data"
    if not os.path.exists(os.path.join(data_dir, "patients.csv")):
        print("Data directory ./data not found!")
        return

    print("Populating PostgreSQL database from synthetic CSV dataset in ./data...")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        # 1. Patients
        patients_df = pd.read_csv(os.path.join(data_dir, "patients.csv"))
        for _, r in patients_df.iterrows():
            p = await session.get(Patient, r["patient_id"])
            if not p:
                session.add(
                    Patient(
                        patient_id=r["patient_id"],
                        age=int(r["age"]),
                        diagnosis_stage=r["diagnosis_stage"],
                        enrollment_date=date.fromisoformat(str(r["enrollment_date"])),
                    )
                )

        # 2. Game Catalog
        catalog_df = pd.read_csv(os.path.join(data_dir, "game_catalog.csv"))
        for _, r in catalog_df.iterrows():
            g = await session.get(GameCatalog, int(r["game_id"]))
            if not g:
                session.add(
                    GameCatalog(
                        game_id=int(r["game_id"]),
                        game_name=r["game_name"],
                        cognitive_domain=r["cognitive_domain"],
                        scoring_fidelity=r["scoring_fidelity"],
                    )
                )

        # 3. Initial Assessments
        ia_df = pd.read_csv(os.path.join(data_dir, "initial_assessments.csv"))
        for _, r in ia_df.iterrows():
            ia = await session.get(InitialAssessment, r["patient_id"])
            if not ia:
                session.add(
                    InitialAssessment(
                        patient_id=r["patient_id"],
                        assessed_at=date.fromisoformat(str(r["assessed_at"])),
                        score=int(r["score"]),
                    )
                )

        # 4. Daily Scores
        daily_df = pd.read_csv(os.path.join(data_dir, "daily_scores.csv"))
        for _, r in daily_df.iterrows():
            ds = await session.get(DailyScore, (r["patient_id"], date.fromisoformat(str(r["date"]))))
            if not ds:
                session.add(
                    DailyScore(
                        patient_id=r["patient_id"],
                        date=date.fromisoformat(str(r["date"])),
                        games_played=int(r["games_played"]),
                        daily_cognitive_score=float(r["daily_cognitive_score"]),
                    )
                )

        # 5. Game Sessions
        sessions_df = pd.read_csv(os.path.join(data_dir, "game_sessions.csv"))
        for _, r in sessions_df.iterrows():
            sid = uuid.UUID(str(r["session_id"]))
            gs = await session.get(GameSession, sid)
            if not gs:
                session.add(
                    GameSession(
                        session_id=sid,
                        patient_id=r["patient_id"],
                        game_id=int(r["game_id"]),
                        score=int(r["score"]),
                        played_at=date.fromisoformat(str(r["played_at"])),
                    )
                )

        await session.commit()
        print("CSVs loaded successfully into Postgres!")

        print("Evaluating all daily score dates for patients to populate clinician review queue...")
        unique_pids = patients_df["patient_id"].unique()
        for pid in unique_pids:
            patient_daily_df = daily_df[daily_df["patient_id"] == pid].sort_values("date")
            for d in patient_daily_df["date"].tolist()[14:]: # Skip cold start <14 days
                try:
                    await evaluate_patient_anomalies(pid, target_date_str=str(d))
                except Exception:
                    pass

        await session.commit()

        # Check total pending flags
        res = await session.execute(select(func.count()).select_from(Flag).where(Flag.status == "pending"))
        flag_count = res.scalar()
        print(f"Seeding complete! Database is populated with {len(unique_pids)} patients and {flag_count} active pending flags.")


if __name__ == "__main__":
    asyncio.run(seed())
