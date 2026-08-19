import os
import sys
import asyncio
import pandas as pd
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "service"))

from app.worker import evaluate_patient_anomalies

from app.database import engine, AsyncSessionLocal

async def main():
    df = pd.read_csv("./data/ground_truth_events.csv")
    print(f"Creating clinician flags for {len(df)} ground truth decline patients...")
    for _, r in df.iterrows():
        pid = r["patient_id"]
        event_date = r["event_start_date"]
        # Evaluate event date and 5 days after event date
        for offset in range(0, 10, 2):
            d = pd.to_datetime(event_date) + pd.Timedelta(days=offset)
            date_str = d.strftime("%Y-%m-%d")
            try:
                await evaluate_patient_anomalies(pid, target_date_str=date_str)
            except Exception as e:
                print(f"Error evaluating {pid} on {date_str}: {e}")

    print("Demo flags generation complete!")

if __name__ == "__main__":
    asyncio.run(main())
