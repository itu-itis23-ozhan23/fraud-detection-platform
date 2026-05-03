import asyncio
import logging
import uuid
from datetime import datetime

from sqlalchemy import Column, String, Numeric, DateTime, ARRAY, Integer, Text, update
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from .config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(settings.DATABASE_URL, echo=False, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(50), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    location = Column(String(100), nullable=False)
    latitude = Column(Numeric(10, 6), nullable=True)
    longitude = Column(Numeric(10, 6), nullable=True)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(20), nullable=False, default="PENDING")
    fraud_score = Column(Integer, default=0)
    fraud_reasons = Column(ARRAY(Text), default=list)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


async def update_transaction_status(
    tx_id: str,
    status: str,
    fraud_score: int,
    fraud_reasons: list[str],
    processed_at: datetime,
) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(Transaction)
            .where(Transaction.id == uuid.UUID(tx_id))
            .values(
                status=status,
                fraud_score=fraud_score,
                fraud_reasons=fraud_reasons,
                processed_at=processed_at,
            )
        )
        await session.commit()


async def wait_for_db():
    for attempt in range(15):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Worker DB tables ready.")
            return
        except Exception as exc:
            logger.warning(f"DB not ready (attempt {attempt + 1}/15): {exc}")
            await asyncio.sleep(3)
    raise RuntimeError("DB unavailable after 15 attempts.")
