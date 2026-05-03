import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres123@postgresql:5432/frauddb"
    REDIS_URL: str = "redis://redis:6379"
    KAFKA_BOOTSTRAP_SERVERS: str = "kafka:9092"
    KAFKA_TRANSACTIONS_TOPIC: str = "transactions"
    KAFKA_PROCESSED_TOPIC: str = "processed_transactions"

    class Config:
        env_file = ".env"


settings = Settings()
