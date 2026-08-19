import uuid
from datetime import datetime, date
from typing import Optional, List
from sqlalchemy import (
    Column,
    String,
    Integer,
    Numeric,
    Date,
    DateTime,
    ForeignKey,
    CheckConstraint,
    PrimaryKeyConstraint,
    Text,
    Float,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Patient(Base):
    __tablename__ = "patients"

    patient_id: Mapped[str] = mapped_column(String, primary_key=True)
    age: Mapped[int] = mapped_column(Integer, nullable=False)
    diagnosis_stage: Mapped[str] = mapped_column(String, nullable=False)
    enrollment_date: Mapped[date] = mapped_column(Date, nullable=False)

    initial_assessment: Mapped[Optional["InitialAssessment"]] = relationship(
        "InitialAssessment", back_populates="patient", uselist=False
    )
    game_sessions: Mapped[List["GameSession"]] = relationship("GameSession", back_populates="patient")
    daily_scores: Mapped[List["DailyScore"]] = relationship("DailyScore", back_populates="patient")
    flags: Mapped[List["Flag"]] = relationship("Flag", back_populates="patient")


class GameCatalog(Base):
    __tablename__ = "game_catalog"

    game_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_name: Mapped[str] = mapped_column(String, nullable=False)
    cognitive_domain: Mapped[str] = mapped_column(String, nullable=False)
    scoring_fidelity: Mapped[str] = mapped_column(String, nullable=False)

    sessions: Mapped[List["GameSession"]] = relationship("GameSession", back_populates="game")


class InitialAssessment(Base):
    __tablename__ = "initial_assessments"

    patient_id: Mapped[str] = mapped_column(
        String, ForeignKey("patients.patient_id"), primary_key=True
    )
    assessed_at: Mapped[date] = mapped_column(Date, nullable=False)
    score: Mapped[int] = mapped_column(Integer, CheckConstraint("score >= 0 AND score <= 10"), nullable=False)

    patient: Mapped["Patient"] = relationship("Patient", back_populates="initial_assessment")


class GameSession(Base):
    __tablename__ = "game_sessions"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    patient_id: Mapped[str] = mapped_column(String, ForeignKey("patients.patient_id"), nullable=False)
    game_id: Mapped[int] = mapped_column(Integer, ForeignKey("game_catalog.game_id"), nullable=False)
    score: Mapped[int] = mapped_column(Integer, CheckConstraint("score >= 0 AND score <= 10"), nullable=False)
    played_at: Mapped[date] = mapped_column(Date, nullable=False)

    patient: Mapped["Patient"] = relationship("Patient", back_populates="game_sessions")
    game: Mapped["GameCatalog"] = relationship("GameCatalog", back_populates="sessions")


class DailyScore(Base):
    __tablename__ = "daily_scores"
    __table_args__ = (PrimaryKeyConstraint("patient_id", "date"),)

    patient_id: Mapped[str] = mapped_column(String, ForeignKey("patients.patient_id"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    games_played: Mapped[int] = mapped_column(Integer, nullable=False)
    daily_cognitive_score: Mapped[float] = mapped_column(Numeric(4, 1), nullable=False)

    patient: Mapped["Patient"] = relationship("Patient", back_populates="daily_scores")


class Flag(Base):
    __tablename__ = "flags"

    flag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    patient_id: Mapped[str] = mapped_column(String, ForeignKey("patients.patient_id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    detector_type: Mapped[str] = mapped_column(String, nullable=False)  # TREND / PATTERN / BOTH
    z_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    isolation_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(
        String, default="pending", nullable=False
    )  # pending / confirmed / dismissed / needs_more_data
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    clinician_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    patient: Mapped["Patient"] = relationship("Patient", back_populates="flags")
    audit_logs: Mapped[List["AuditLog"]] = relationship("AuditLog", back_populates="flag")


class AuditLog(Base):
    __tablename__ = "audit_log"

    log_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    flag_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("flags.flag_id"), nullable=False)
    actor: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    flag: Mapped["Flag"] = relationship("Flag", back_populates="audit_logs")
