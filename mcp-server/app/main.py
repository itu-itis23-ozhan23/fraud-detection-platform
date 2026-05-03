"""
MCP Server — Fraud Detection Platform
Exposes two tools for AI agents:
  • get_recent_frauds   – list recent suspicious transactions
  • check_user_status   – get risk profile of a specific user
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

import redis.asyncio as aioredis
from mcp.server.fastmcp import FastMCP
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres123@postgresql:5432/frauddb",
)
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
MCP_HOST = os.getenv("MCP_HOST", "0.0.0.0")
MCP_PORT = int(os.getenv("MCP_PORT", "8080"))

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

mcp = FastMCP("Fraud Detection Platform")


# ── Helper ────────────────────────────────────────────────────────────────────

def _serialize(row) -> dict:
    result = {}
    for key, value in row._mapping.items():
        if isinstance(value, (datetime,)):
            result[key] = value.isoformat()
        elif isinstance(value, uuid.UUID):
            result[key] = str(value)
        else:
            result[key] = value
    return result


# ── Tools ─────────────────────────────────────────────────────────────────────

@mcp.tool()
async def get_recent_frauds(
    time_range_minutes: int = 60,
    limit: int = 20,
) -> str:
    """
    Retrieve recent suspicious (fraud) transactions.

    Args:
        time_range_minutes: How many minutes back to look (default 60).
        limit: Maximum number of results to return (default 20, max 100).

    Returns:
        JSON string with list of fraud transactions and summary statistics.
    """
    limit = min(limit, 100)
    since = datetime.now(timezone.utc) - timedelta(minutes=time_range_minutes)

    async with SessionLocal() as db:
        result = await db.execute(
            text(
                """
                SELECT id, user_id, amount, location, timestamp,
                       status, fraud_score, fraud_reasons, processed_at
                FROM transactions
                WHERE status = 'SUSPICIOUS'
                  AND timestamp >= :since
                ORDER BY timestamp DESC
                LIMIT :limit
                """
            ),
            {"since": since, "limit": limit},
        )
        rows = result.fetchall()

    items = [_serialize(r) for r in rows]

    return json.dumps(
        {
            "time_range_minutes": time_range_minutes,
            "total_found": len(items),
            "since": since.isoformat(),
            "frauds": items,
        },
        ensure_ascii=False,
    )


@mcp.tool()
async def check_user_status(user_id: str) -> str:
    """
    Check the fraud risk status of a specific user.

    Args:
        user_id: The user identifier to look up.

    Returns:
        JSON string with risk level, transaction counts, and recent activity.
    """
    async with SessionLocal() as db:
        total_result = await db.execute(
            text("SELECT COUNT(*) FROM transactions WHERE user_id = :uid"),
            {"uid": user_id},
        )
        total = total_result.scalar() or 0

        suspicious_result = await db.execute(
            text(
                "SELECT COUNT(*) FROM transactions WHERE user_id = :uid AND status = 'SUSPICIOUS'"
            ),
            {"uid": user_id},
        )
        suspicious = suspicious_result.scalar() or 0

        recent_result = await db.execute(
            text(
                """
                SELECT id, amount, location, timestamp, status, fraud_score, fraud_reasons
                FROM transactions
                WHERE user_id = :uid
                ORDER BY timestamp DESC
                LIMIT 10
                """
            ),
            {"uid": user_id},
        )
        recent = [_serialize(r) for r in recent_result.fetchall()]

    if total == 0:
        risk_level = "UNKNOWN"
    else:
        ratio = suspicious / total
        if ratio >= 0.5:
            risk_level = "HIGH"
        elif ratio >= 0.2:
            risk_level = "MEDIUM"
        else:
            risk_level = "LOW"

    return json.dumps(
        {
            "user_id": user_id,
            "risk_level": risk_level,
            "total_transactions": total,
            "suspicious_transactions": suspicious,
            "fraud_rate_pct": round(suspicious / total * 100, 1) if total else 0,
            "recent_transactions": recent,
        },
        ensure_ascii=False,
    )


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info(f"Starting MCP Server on {MCP_HOST}:{MCP_PORT}")
    mcp.run(transport="sse", host=MCP_HOST, port=MCP_PORT)
