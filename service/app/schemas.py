import uuid
from datetime import datetime, date
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict

MANDATORY_DISCLAIMER = "statistical signal, not a diagnosis — reviewed by a clinician"


# Ingestion Schemas
class SessionIngestRequest(BaseModel):
    session_id: Optional[uuid.UUID] = None
    patient_id: str
    game_id: int
    score: int = Field(ge=0, le=10)
    played_at: date


class SessionIngestResponse(BaseModel):
    status: str = "success"
    session_id: uuid.UUID
    patient_id: str
    game_id: int
    score: int
    played_at: date


# Baseline & Trend Schemas
class BaselineResponse(BaseModel):
    patient_id: str
    rolling_mean: Optional[float]
    rolling_std: Optional[float]
    days_history: int
    cold_start_eligible: bool
    initial_assessment_score: Optional[int]


class AnomalyMarker(BaseModel):
    date: date
    flag_id: uuid.UUID
    detector_type: str  # TREND | PATTERN | BOTH
    status: str  # pending | confirmed | dismissed | needs_more_data
    z_score: Optional[float] = None
    isolation_score: Optional[float] = None


class TrendPoint(BaseModel):
    date: date
    daily_cognitive_score: float
    rolling_mean: Optional[float]
    rolling_std: Optional[float]
    upper_bound: Optional[float] = None
    lower_bound: Optional[float] = None
    z_score: Optional[float]
    is_anomaly: bool = False


class TrendResponse(BaseModel):
    patient_id: str
    points: List[TrendPoint]
    anomalies: List[AnomalyMarker] = []


# Flag & Review Schemas
class FlagRead(BaseModel):
    flag_id: uuid.UUID
    patient_id: str
    created_at: datetime
    date: date
    detector_type: str
    severity: str = "LOW"  # HIGH | MODERATE | LOW
    z_score: Optional[float]
    isolation_score: Optional[float]
    status: str
    explanation: str
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    clinician_notes: Optional[str] = None
    disclaimer: str = Field(default=MANDATORY_DISCLAIMER)

    model_config = ConfigDict(from_attributes=True)


class ReviewRequest(BaseModel):
    decision: str  # confirmed | dismissed | needs_more_data
    notes: Optional[str] = None


class BulkReviewRequest(BaseModel):
    flag_ids: List[uuid.UUID]
    decision: str = "dismissed"
    notes: Optional[str] = None


class CaregiverMessage(BaseModel):
    flag_id: uuid.UUID
    patient_id: str
    date: date
    reviewed_at: Optional[datetime]
    clinician_approved_message: str
    disclaimer: str = Field(default=MANDATORY_DISCLAIMER)


class TokenPayload(BaseModel):
    sub: str
    role: str  # clinician | caregiver | admin
    patient_ids: List[str] = []
    exp: int
