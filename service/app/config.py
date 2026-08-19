import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://cogdrift:dev_only_change_me@postgres:5432/cogdrift"
    RABBITMQ_URL: str = "amqp://guest:guest@rabbitmq:5672/"
    
    BASELINE_WINDOW_DAYS: int = 30
    COLD_START_MIN_DAYS: int = 14
    TREND_Z_THRESHOLD: float = -2.0
    TREND_PERSISTENCE_DAYS: int = 3
    ISOLATION_FOREST_CONTAMINATION: float = 0.005
    PATTERN_PERSISTENCE_DAYS: int = 3
    
    JWT_SECRET: str = "dev_jwt_secret_change_in_production_key_12345"
    JWT_ALGORITHM: str = "HS256"
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
