import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..database import get_db
from ..models import Transaction
from ..schemas import TransactionCreate, TransactionResponse
from ..kafka_producer import send_transaction
from ..metrics import transactions_received_total

router = APIRouter()


@router.post("/", response_model=TransactionResponse, status_code=201)
async def create_transaction(
    payload: TransactionCreate,
    db: AsyncSession = Depends(get_db),
):
    """Ingest a new transaction. Publishes to Kafka for async anomaly detection."""
    ts = payload.timestamp or datetime.now(timezone.utc)

    tx = Transaction(
        id=uuid.uuid4(),
        user_id=payload.user_id,
        amount=float(payload.amount),
        location=payload.location,
        latitude=payload.latitude,
        longitude=payload.longitude,
        timestamp=ts,
        status="PENDING",
        fraud_score=0,
        fraud_reasons=[],
    )
    db.add(tx)
    await db.commit()
    await db.refresh(tx)

    transactions_received_total.inc()

    # Publish to Kafka for the worker to process
    await send_transaction({
        "id": str(tx.id),
        "user_id": tx.user_id,
        "amount": float(tx.amount),
        "location": tx.location,
        "latitude": float(tx.latitude) if tx.latitude else None,
        "longitude": float(tx.longitude) if tx.longitude else None,
        "timestamp": ts.isoformat(),
    })

    return tx


@router.get("/{transaction_id}", response_model=TransactionResponse)
async def get_transaction(transaction_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Transaction).where(Transaction.id == transaction_id))
    tx = result.scalar_one_or_none()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return tx
