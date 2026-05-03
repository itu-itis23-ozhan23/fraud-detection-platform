from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from ..database import get_db
from ..models import Transaction
from ..schemas import FraudListResponse, TransactionResponse

router = APIRouter()


@router.get("/", response_model=FraudListResponse)
async def list_frauds(
    start: Optional[datetime] = Query(None, description="ISO-8601 start datetime"),
    end: Optional[datetime] = Query(None, description="ISO-8601 end datetime"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List suspicious transactions within an optional time range."""
    if end is None:
        end = datetime.now(timezone.utc)
    if start is None:
        start = end - timedelta(hours=24)

    base_query = (
        select(Transaction)
        .where(
            Transaction.status == "SUSPICIOUS",
            Transaction.timestamp >= start,
            Transaction.timestamp <= end,
        )
        .order_by(Transaction.timestamp.desc())
    )

    count_result = await db.execute(
        select(func.count()).select_from(base_query.subquery())
    )
    total = count_result.scalar() or 0

    result = await db.execute(base_query.offset(offset).limit(limit))
    items = result.scalars().all()

    return FraudListResponse(
        total=total,
        items=[TransactionResponse.model_validate(t) for t in items],
    )
