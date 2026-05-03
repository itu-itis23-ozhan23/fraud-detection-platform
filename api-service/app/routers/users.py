from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from ..database import get_db
from ..models import Transaction
from ..schemas import UserStatusResponse, TransactionResponse

router = APIRouter()


@router.get("/{user_id}/status", response_model=UserStatusResponse)
async def get_user_status(user_id: str, db: AsyncSession = Depends(get_db)):
    """Return transaction history and risk level for a specific user."""

    # Count total
    total_result = await db.execute(
        select(func.count()).where(Transaction.user_id == user_id)
    )
    total = total_result.scalar() or 0

    if total == 0:
        raise HTTPException(status_code=404, detail=f"No transactions found for user '{user_id}'")

    # Count suspicious
    suspicious_result = await db.execute(
        select(func.count()).where(
            Transaction.user_id == user_id,
            Transaction.status == "SUSPICIOUS",
        )
    )
    suspicious = suspicious_result.scalar() or 0

    # Recent 20 transactions
    recent_result = await db.execute(
        select(Transaction)
        .where(Transaction.user_id == user_id)
        .order_by(Transaction.timestamp.desc())
        .limit(20)
    )
    recent = recent_result.scalars().all()

    # Compute risk level
    if total == 0:
        risk = "LOW"
    else:
        ratio = suspicious / total
        if ratio >= 0.5:
            risk = "HIGH"
        elif ratio >= 0.2:
            risk = "MEDIUM"
        else:
            risk = "LOW"

    return UserStatusResponse(
        user_id=user_id,
        total_transactions=total,
        suspicious_transactions=suspicious,
        risk_level=risk,
        recent_transactions=[TransactionResponse.model_validate(t) for t in recent],
    )
