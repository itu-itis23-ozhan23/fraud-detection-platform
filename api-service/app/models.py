import uuid
from datetime import datetime
from sqlalchemy import Column, String, Numeric, DateTime, ARRAY, Integer, Text
from sqlalchemy.dialects.postgresql import UUID

from .database import Base


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(50), nullable=False, index=True)
    amount = Column(Numeric(12, 2), nullable=False)
    location = Column(String(100), nullable=False)
    latitude = Column(Numeric(10, 6), nullable=True)
    longitude = Column(Numeric(10, 6), nullable=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, index=True)
    status = Column(String(20), nullable=False, default="PENDING")  # PENDING | APPROVED | SUSPICIOUS
    fraud_score = Column(Integer, default=0)
    fraud_reasons = Column(ARRAY(Text), default=list)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
