"""
Unit tests for the Anomaly Detection Engine
============================================
Tests cover:
  - Haversine distance calculation
  - Coordinate lookup helpers
  - Velocity check (Redis ZSET sliding window)
  - Amount check (3× average threshold)
  - Location / impossible-travel check
  - Top-level detect() — status, reasons, fraud score

Uses fakeredis.aioredis so no real Redis instance is needed.
Run with:
    pytest worker-service/tests/ -v
"""

import json
import math
import time
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, AsyncMock

import pytest
import pytest_asyncio
import fakeredis.aioredis

# ── Module-level import ────────────────────────────────────────────────────────
# Patch settings before importing the module under test so the import does not
# try to read a real .env file.
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.anomaly_detector import (
    _haversine_km,
    _coords_for,
    check_velocity,
    check_amount,
    check_location,
    detect,
    CITY_COORDS,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def redis():
    """Fresh in-memory fakeredis instance for each test."""
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


def _now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def _tx(
    user_id: str = "user_1",
    amount: float = 100.0,
    location: str = "istanbul",
    lat: float = None,
    lon: float = None,
    seconds_ago: float = 0,
) -> dict:
    ts = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "amount": amount,
        "location": location,
        "latitude": lat,
        "longitude": lon,
        "timestamp": ts.isoformat(),
    }


# ── Pure-function tests ────────────────────────────────────────────────────────

class TestHaversine:
    def test_same_point_is_zero(self):
        assert _haversine_km(41.0, 28.9, 41.0, 28.9) == pytest.approx(0.0, abs=1e-6)

    def test_istanbul_to_ankara(self):
        """Istanbul → Ankara is ~350 km."""
        lat1, lon1 = CITY_COORDS["istanbul"]
        lat2, lon2 = CITY_COORDS["ankara"]
        dist = _haversine_km(lat1, lon1, lat2, lon2)
        assert 340 < dist < 360, f"Expected ~350 km, got {dist:.1f} km"

    def test_istanbul_to_new_york(self):
        """Istanbul → New York is ~9000 km."""
        lat1, lon1 = CITY_COORDS["istanbul"]
        lat2, lon2 = CITY_COORDS["new york"]
        dist = _haversine_km(lat1, lon1, lat2, lon2)
        assert 8800 < dist < 9200, f"Expected ~9000 km, got {dist:.1f} km"

    def test_symmetry(self):
        lat1, lon1 = CITY_COORDS["istanbul"]
        lat2, lon2 = CITY_COORDS["berlin"]
        assert _haversine_km(lat1, lon1, lat2, lon2) == pytest.approx(
            _haversine_km(lat2, lon2, lat1, lon1), rel=1e-6
        )


class TestCoordsFor:
    def test_explicit_coords_take_priority(self):
        result = _coords_for("istanbul", 10.0, 20.0)
        assert result == (10.0, 20.0)

    def test_city_lookup(self):
        result = _coords_for("istanbul", None, None)
        assert result == CITY_COORDS["istanbul"]

    def test_case_insensitive_lookup(self):
        assert _coords_for("ISTANBUL", None, None) == CITY_COORDS["istanbul"]
        assert _coords_for("Istanbul", None, None) == CITY_COORDS["istanbul"]

    def test_unknown_city_returns_none(self):
        result = _coords_for("nonexistentcity", None, None)
        assert result is None


# ── Velocity tests ─────────────────────────────────────────────────────────────

class TestCheckVelocity:
    @pytest.mark.asyncio
    async def test_single_transaction_not_suspicious(self, redis):
        count = await check_velocity(redis, "user_1", _now_ts())
        assert count == 1

    @pytest.mark.asyncio
    async def test_five_transactions_at_threshold(self, redis):
        base = _now_ts()
        for i in range(5):
            count = await check_velocity(redis, "user_1", base + i * 0.1)
        # 5 transactions — exactly at threshold (not over)
        assert count == 5

    @pytest.mark.asyncio
    async def test_six_transactions_exceeds_threshold(self, redis):
        base = _now_ts()
        for i in range(6):
            count = await check_velocity(redis, "user_1", base + i * 0.1)
        assert count == 6  # > VELOCITY_MAX_TRANSACTIONS (5)

    @pytest.mark.asyncio
    async def test_old_transactions_excluded(self, redis):
        """Transactions older than VELOCITY_WINDOW_SECONDS (60s) should not count."""
        old_ts = _now_ts() - 120  # 2 minutes ago — outside window
        await check_velocity(redis, "user_1", old_ts)
        await check_velocity(redis, "user_1", old_ts + 1)
        # Now add a fresh transaction; old ones should be pruned
        count = await check_velocity(redis, "user_1", _now_ts())
        assert count == 1

    @pytest.mark.asyncio
    async def test_different_users_isolated(self, redis):
        base = _now_ts()
        for i in range(6):
            await check_velocity(redis, "user_A", base + i * 0.1)
        count_b = await check_velocity(redis, "user_B", base)
        assert count_b == 1  # user_B is unaffected by user_A's activity


# ── Amount tests ───────────────────────────────────────────────────────────────

class TestCheckAmount:
    @pytest.mark.asyncio
    async def test_first_transaction_returns_zero_avg(self, redis):
        avg = await check_amount(redis, "user_1", str(uuid.uuid4()), 500.0, _now_ts())
        assert avg == 0.0

    @pytest.mark.asyncio
    async def test_average_computed_correctly(self, redis):
        base = _now_ts()
        uid = "user_2"
        # Seed three transactions at 100
        for i in range(3):
            await check_amount(redis, uid, str(uuid.uuid4()), 100.0, base + i)
        # 4th call should see avg of 100
        avg = await check_amount(redis, uid, str(uuid.uuid4()), 100.0, base + 3)
        assert avg == pytest.approx(100.0, rel=0.01)

    @pytest.mark.asyncio
    async def test_current_tx_excluded_from_avg(self, redis):
        """The transaction being evaluated must NOT be included in its own average."""
        uid = "user_3"
        base = _now_ts()
        tx_id = str(uuid.uuid4())
        # Seed 3 prior transactions at 50
        for i in range(3):
            await check_amount(redis, uid, str(uuid.uuid4()), 50.0, base + i)
        # Spike: evaluate a 300 tx — its own value should not pollute the avg
        avg = await check_amount(redis, uid, tx_id, 300.0, base + 3)
        assert avg == pytest.approx(50.0, rel=0.01)

    @pytest.mark.asyncio
    async def test_old_transactions_outside_24h_excluded(self, redis):
        uid = "user_4"
        old_ts = _now_ts() - (25 * 3600)  # 25 hours ago
        # Two huge old amounts
        for i in range(2):
            await check_amount(redis, uid, str(uuid.uuid4()), 10000.0, old_ts + i)
        # Fresh small amount — old ones should be pruned
        avg = await check_amount(redis, uid, str(uuid.uuid4()), 50.0, _now_ts())
        assert avg == 0.0  # All history expired


# ── Location tests ─────────────────────────────────────────────────────────────

class TestCheckLocation:
    @pytest.mark.asyncio
    async def test_first_transaction_no_previous_location(self, redis):
        result = await check_location(redis, "user_1", "istanbul", None, None, _now_ts())
        assert result is False

    @pytest.mark.asyncio
    async def test_same_city_not_suspicious(self, redis):
        ts = _now_ts()
        await check_location(redis, "user_1", "istanbul", None, None, ts)
        # 5 minutes later, same city
        result = await check_location(redis, "user_1", "istanbul", None, None, ts + 300)
        assert result is False

    @pytest.mark.asyncio
    async def test_nearby_location_not_suspicious(self, redis):
        """Distance < 10 km should always be ignored."""
        ts = _now_ts()
        await check_location(redis, "user_1", "istanbul", 41.0082, 28.9784, ts)
        result = await check_location(
            redis, "user_1", "istanbul", 41.0100, 28.9800, ts + 1
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_impossible_travel_detected(self, redis):
        """Istanbul → New York in 1 minute is physically impossible."""
        ts = _now_ts()
        await check_location(redis, "user_1", "istanbul", None, None, ts)
        # 1 minute later in New York
        result = await check_location(redis, "user_1", "new york", None, None, ts + 60)
        assert result is True

    @pytest.mark.asyncio
    async def test_reasonable_travel_not_suspicious(self, redis):
        """Istanbul → Ankara in 1 hour by plane is fine (~350 km, ~350 km/h < 800 km/h)."""
        ts = _now_ts()
        await check_location(redis, "user_1", "istanbul", None, None, ts)
        result = await check_location(redis, "user_1", "ankara", None, None, ts + 3600)
        assert result is False

    @pytest.mark.asyncio
    async def test_unknown_location_skipped(self, redis):
        """Transactions with unrecognised city name and no coords should not flag."""
        ts = _now_ts()
        await check_location(redis, "user_1", "istanbul", None, None, ts)
        result = await check_location(
            redis, "user_1", "unknowncity", None, None, ts + 60
        )
        assert result is False


# ── Top-level detect() tests ────────────────────────────────────────────────────

class TestDetect:
    @pytest.mark.asyncio
    async def test_clean_transaction_is_approved(self, redis):
        tx = _tx(user_id="clean_user", amount=100.0, location="istanbul")
        status, reasons, score = await detect(redis, tx)
        assert status == "APPROVED"
        assert reasons == []
        assert score == 0

    @pytest.mark.asyncio
    async def test_velocity_burst_triggers_suspicious(self, redis):
        """6 rapid-fire transactions should trip the velocity rule."""
        user_id = "burst_user"
        base = _now_ts()
        results = []
        for i in range(6):
            tx = _tx(user_id=user_id, amount=100.0, location="istanbul", seconds_ago=-i * 0.1)
            status, reasons, score = await detect(redis, tx)
            results.append((status, reasons))
        # At least one transaction should be SUSPICIOUS due to velocity
        suspicious = [r for r in results if r[0] == "SUSPICIOUS"]
        assert len(suspicious) >= 1

    @pytest.mark.asyncio
    async def test_amount_spike_alone_not_suspicious(self, redis):
        """A single amount violation (without a second rule) stays APPROVED."""
        uid = "spike_user"
        base_ts = _now_ts() - 10
        # Seed 3 normal transactions
        for i in range(3):
            seed_tx = _tx(user_id=uid, amount=100.0, location="istanbul", seconds_ago=30 + i)
            await detect(redis, seed_tx)
        # One huge spike — only 1 rule fires
        spike_tx = _tx(user_id=uid, amount=5000.0, location="istanbul")
        status, reasons, score = await detect(redis, spike_tx)
        assert status == "APPROVED"
        assert "amount_exceeded" in reasons
        assert len(reasons) == 1

    @pytest.mark.asyncio
    async def test_two_violations_marks_suspicious(self, redis):
        """Velocity + amount both triggered → SUSPICIOUS."""
        uid = "double_offender"
        base = _now_ts()
        # Seed amount history
        for i in range(3):
            seed = _tx(user_id=uid, amount=50.0, location="istanbul", seconds_ago=100 + i)
            await detect(redis, seed)
        # Flood with 5 fast transactions to build velocity
        for i in range(5):
            flood = _tx(user_id=uid, amount=50.0, location="istanbul", seconds_ago=-(i * 0.01))
            await detect(redis, flood)
        # Now fire a huge amount spike
        spike = _tx(user_id=uid, amount=10000.0, location="istanbul")
        status, reasons, score = await detect(redis, spike)
        assert status == "SUSPICIOUS"
        assert "amount_exceeded" in reasons
        assert score >= 70

    @pytest.mark.asyncio
    async def test_impossible_travel_plus_velocity_is_suspicious(self, redis):
        """Impossible travel + velocity burst → SUSPICIOUS with score 100."""
        uid = "traveler"
        base = _now_ts()
        # Build velocity
        for i in range(6):
            tx = _tx(user_id=uid, location="istanbul", seconds_ago=-(i * 0.1))
            await detect(redis, tx)
        # Now jump to New York 1 minute later — impossible travel
        ny_tx = _tx(user_id=uid, location="new york", seconds_ago=-60)
        status, reasons, score = await detect(redis, ny_tx)
        assert status == "SUSPICIOUS"
        assert "impossible_travel" in reasons
        assert score >= 70

    @pytest.mark.asyncio
    async def test_fraud_score_scales_with_violations(self, redis):
        """0 violations → score 0; confirmed fraud (≥2) → score ≥ 70."""
        uid = "score_test"
        # Clean
        tx = _tx(user_id=uid + "_clean", amount=100.0, location="ankara")
        _, _, score_clean = await detect(redis, tx)
        assert score_clean == 0

    @pytest.mark.asyncio
    async def test_different_users_do_not_interfere(self, redis):
        """Redis state for user_A must not affect user_B's evaluation."""
        # Saturate user_A with velocity
        for i in range(10):
            tx_a = _tx(user_id="isolation_user_A", location="istanbul", seconds_ago=-(i * 0.1))
            await detect(redis, tx_a)
        # user_B's first transaction should always be APPROVED
        tx_b = _tx(user_id="isolation_user_B", amount=100.0, location="istanbul")
        status, reasons, score = await detect(redis, tx_b)
        assert status == "APPROVED"
        assert reasons == []
