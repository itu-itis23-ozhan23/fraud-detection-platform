from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


# ── Request Schemas ──────────────────────────────────────────────────────────

class TransactionCreate(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=50, examples=["user_001"])
    amount: float = Field(..., gt=0, examples=[250.00])
    location: str = Field(..., min_length=1, max_length=100, examples=["Istanbul"])
    latitude: Optional[float] = Field(None, examples=[41.0082])
    longitude: Optional[float] = Field(None, examples=[28.9784])
    timestamp: Optional[datetime] = None


# ── Response Schemas ─────────────────────────────────────────────────────────

class TransactionResponse(BaseModel):
    id: uuid.UUID
    user_id: str
    amount: float
    location: str
    latitude: Optional[float]
    longitude: Optional[float]
    timestamp: datetime
    status: str
    fraud_score: int
    fraud_reasons: List[str]
    processed_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class UserStatusResponse(BaseModel):
    user_id: str
    total_transactions: int
    suspicious_transactions: int
    risk_level: str          # LOW | MEDIUM | HIGH
    recent_transactions: List[TransactionResponse]


class FraudListResponse(BaseModel):
    total: int
    items: List[TransactionResponse]


class PaginationParams(BaseModel):
    page: int = Field(1, ge=1)
    size: int = Field(20, ge=1, le=100)
