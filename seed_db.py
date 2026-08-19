import os
import sys
import asyncio
import uuid
from datetime import date
import pandas as pd
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert as pg_insert

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "service"))

from app.models import Base, Patient, GameCatalog, InitialAssessment, GameSession, DailyScore, Flag
from app.worker import evaluate_patient_anomalies
from app.database import engine, AsyncSessionLocal


async def seed():
    data_dir = "./data"
    if not os.path.exists(os.path.join(data_dir, "patients.csv")):
        print("Data directory ./data not found! Run generate_dataset.py first.")
        return

    print("Populating PostgreSQL database with fast bulk batching...")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        # 1. Patients
        print("  -> Inserting patients...")
        patients_df = pd.read_csv(os.path.join(data_dir, "patients.csv"))
        patients_data = [
            {
                "patient_id": str(r["patient_id"]),
                "age": int(r["age"]),
                "diagnosis_stage": str(r["diagnosis_stage"]),
                "enrollment_date": date.fromisoformat(str(r["enrollment_date"])),
            }
            for _, r in patients_df.iterrows()
        ]
        if patients_data:
            stmt = pg_insert(Patient).values(patients_data).on_conflict_do_nothing()
            await session.execute(stmt)

        # 2. Game Catalog
        print("  -> Inserting game catalog...")
        catalog_df = pd.read_csv(os.path.join(data_dir, "game_catalog.csv"))
        catalog_data = [
            {
                "game_id": int(r["game_id"]),
                "game_name": str(r["game_name"]),
                "cognitive_domain": str(r["cognitive_domain"]),
                "scoring_fidelity": str(r["scoring_fidelity"]),
            }
            for _, r in catalog_df.iterrows()
        ]
        if catalog_data:
            stmt = pg_insert(GameCatalog).values(catalog_data).on_conflict_do_nothing()
            await session.execute(stmt)

        # 3. Initial Assessments
        print("  -> Inserting initial assessments...")
        ia_df = pd.read_csv(os.path.join(data_dir, "initial_assessments.csv"))
        ia_data = [
            {
                "patient_id": str(r["patient_id"]),
                "assessed_at": date.fromisoformat(str(r["assessed_at"])),
                "score": int(r["score"]),
            }
            for _, r in ia_df.iterrows()
        ]
        if ia_data:
            stmt = pg_insert(InitialAssessment).values(ia_data).on_conflict_do_nothing()
            await session.execute(stmt)

        # 4. Daily Scores (Batching in chunks of 5,000)
        print("  -> Inserting daily scores in bulk batches...")
        daily_df = pd.read_csv(os.path.join(data_dir, "daily_scores.csv"))
        daily_data = [
            {
                "patient_id": str(r["patient_id"]),
                "date": date.fromisoformat(str(r["date"])),
                "games_played": int(r["games_played"]),
                "daily_cognitive_score": float(r["daily_cognitive_score"]),
            }
            for _, r in daily_df.iterrows()
        ]
        chunk_size = 5000
        for i in range(0, len(daily_data), chunk_size):
            chunk = daily_data[i : i + chunk_size]
            stmt = pg_insert(DailyScore).values(chunk).on_conflict_do_nothing()
            await session.execute(stmt)

        # 5. Game Sessions (Batching in chunks of 5,000)
        print("  -> Inserting game sessions in bulk batches...")
        sessions_df = pd.read_csv(os.path.join(data_dir, "game_sessions.csv"))
        sessions_data = [
            {
                "session_id": uuid.UUID(str(r["session_id"])),
                "patient_id": str(r["patient_id"]),
                "game_id": int(r["game_id"]),
                "score": int(r["score"]),
                "played_at": date.fromisoformat(str(r["played_at"])),
            }
            for _, r in sessions_df.iterrows()
        ]
        for i in range(0, len(sessions_data), chunk_size):
            chunk = sessions_data[i : i + chunk_size]
            stmt = pg_insert(GameSession).values(chunk).on_conflict_do_nothing()
            await session.execute(stmt)

        await session.commit()
        print("  ✓ All CSV datasets successfully loaded into PostgreSQL!")

        # 6. Evaluate baseline anomalies to populate initial clinician review queue
        print("  -> Evaluating anomaly detectors for active patient cohort...")
        unique_pids = list(patients_df["patient_id"].unique())
        
        # Evaluate each patient on their most recent day to seed active clinician queue
        for pid in unique_pids:
            try:
                await evaluate_patient_anomalies(pid)
            except Exception as e:
                pass

        await session.commit()

        # Check total pending flags
        res = await session.execute(select(func.count()).select_from(Flag).where(Flag.status == "pending"))
        flag_count = res.scalar()
        print(f"\n=================================================================")
        print(f"  ✓ Seeding Complete! Successfully populated {len(unique_pids)} patients and {flag_count} flags.")
        print(f"=================================================================\n")


if __name__ == "__main__":
    asyncio.run(seed())
