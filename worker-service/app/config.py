from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres123@postgresql:5432/frauddb"
    REDIS_URL: str = "redis://redis:6379"
    KAFKA_BOOTSTRAP_SERVERS: str = "kafka:9092"
    KAFKA_TRANSACTIONS_TOPIC: str = "transactions"
    KAFKA_PROCESSED_TOPIC: str = "processed_transactions"
    KAFKA_GROUP_ID: str = "fraud-worker-group"

    # Anomaly thresholds
    VELOCITY_WINDOW_SECONDS: int = 60
    VELOCITY_MAX_TRANSACTIONS: int = 5
    AMOUNT_MULTIPLIER_THRESHOLD: float = 3.0
    AMOUNT_LOOKBACK_HOURS: int = 24
    MAX_TRAVEL_SPEED_KMH: float = 800.0  # max plane speed

    class Config:
        env_file = ".env"


settings = Settings()
