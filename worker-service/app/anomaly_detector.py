"""
Anomaly Detection Engine
========================
Hybrid rule-based + ML anomaly detection.

Rule-based layer (primary)
--------------------------
Checks three independent criteria per transaction. A transaction is marked
SUSPICIOUS when at least TWO criteria are violated.

1. Velocity   – same user made >5 transactions in the last 60 s  (Redis ZSET)
2. Amount     – transaction amount > 3× user's 24-h average      (Redis ZSET)
3. Location   – consecutive transactions imply impossible travel  (Redis HASH)
                (required speed > 800 km/h)

ML layer (tiebreaker)
---------------------
An Isolation Forest model is trained on a rolling window of recent feature
vectors stored in Redis. When exactly ONE rule fires (borderline case), the
model is consulted: if it scores the transaction as an outlier (anomaly_score
< ISO_THRESHOLD), the transaction is escalated to SUSPICIOUS.

This hybrid approach combines the interpretability of rule-based detection
with the pattern-recognition capability of unsupervised ML — neither alone
is sufficient for a production fraud system.

Feature vector: [amount_ratio, velocity_count, distance_km, elapsed_hours]
  - amount_ratio:   current_amount / 24h_avg  (1.0 if no history)
  - velocity_count: transactions in last 60 s
  - distance_km:    distance from last known location (0 if unknown)
  - elapsed_hours:  hours since last transaction (capped at 24)
"""

import json
import math
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import redis.asyncio as aioredis
from sklearn.ensemble import IsolationForest

from .config import settings

logger = logging.getLogger(__name__)

# ── Isolation Forest configuration ────────────────────────────────────────────

ISO_FEATURE_KEY = "ml:iso_forest:features"   # Redis ZSET storing feature vectors
ISO_WINDOW_SIZE = 500                          # Max samples kept for training
ISO_MIN_SAMPLES = 30                           # Minimum samples before ML kicks in
ISO_RETRAIN_EVERY = 50                         # Retrain after every N new samples
ISO_THRESHOLD = -0.05                          # anomaly_score < threshold → outlier
ISO_CONTAMINATION = 0.08                       # Expected fraud rate ~8%

# Module-level model cache (retrained in-process, no serialization needed)
_iso_model: Optional[IsolationForest] = None
_iso_sample_count: int = 0


async def _store_feature_vector(
    redis: aioredis.Redis,
    tx_id: str,
    features: list[float],
    ts: float,
) -> int:
    """
    Store a feature vector in the global Redis ZSET (score = timestamp).
    Returns the total number of stored samples after pruning.
    """
    member = json.dumps({"id": tx_id, "features": features})
    pipe = redis.pipeline()
    pipe.zadd(ISO_FEATURE_KEY, {member: ts})
    # Keep only the most recent ISO_WINDOW_SIZE samples
    pipe.zremrangebyrank(ISO_FEATURE_KEY, 0, -(ISO_WINDOW_SIZE + 1))
    pipe.zcard(ISO_FEATURE_KEY)
    results = await pipe.execute()
    return results[2]  # zcard


async def _load_feature_matrix(redis: aioredis.Redis) -> Optional[np.ndarray]:
    """Load all stored feature vectors and return as a numpy matrix."""
    raw_members = await redis.zrange(ISO_FEATURE_KEY, 0, -1)
    if len(raw_members) < ISO_MIN_SAMPLES:
        return None
    rows = []
    for m in raw_members:
        try:
            obj = json.loads(m)
            rows.append(obj["features"])
        except Exception:
            pass
    if len(rows) < ISO_MIN_SAMPLES:
        return None
    return np.array(rows, dtype=float)


async def _maybe_retrain(redis: aioredis.Redis, sample_count: int) -> None:
    """Retrain the Isolation Forest every ISO_RETRAIN_EVERY new samples."""
    global _iso_model, _iso_sample_count

    if sample_count % ISO_RETRAIN_EVERY != 0:
        return

    X = await _load_feature_matrix(redis)
    if X is None:
        return

    try:
        model = IsolationForest(
            n_estimators=100,
            contamination=ISO_CONTAMINATION,
            random_state=42,
            n_jobs=-1,
        )
        model.fit(X)
        _iso_model = model
        _iso_sample_count = len(X)
        logger.info(
            "Isolation Forest retrained on %d samples (contamination=%.0f%%).",
            len(X),
            ISO_CONTAMINATION * 100,
        )
        try:
            from .metrics import ml_model_training_total, ml_training_samples
            ml_model_training_total.inc()
            ml_training_samples.set(len(X))
        except ImportError:
            pass
    except Exception as exc:
        logger.warning("Isolation Forest training failed: %s", exc)


def _iso_score(features: list[float]) -> Optional[float]:
    """
    Return the anomaly score for a feature vector using the cached model.
    Lower (more negative) = more anomalous.
    Returns None if no model is available yet.
    """
    if _iso_model is None:
        return None
    try:
        X = np.array([features], dtype=float)
        return float(_iso_model.score_samples(X)[0])
    except Exception:
        return None

# Well-known Turkish city coordinates (lat, lon)
CITY_COORDS: dict[str, tuple[float, float]] = {
    "istanbul": (41.0082, 28.9784),
    "ankara": (39.9334, 32.8597),
    "izmir": (38.4192, 27.1287),
    "antalya": (36.8969, 30.7133),
    "bursa": (40.1826, 29.0665),
    "adana": (37.0000, 35.3213),
    "konya": (37.8746, 32.4932),
    "gaziantep": (37.0662, 37.3833),
    "kayseri": (38.7225, 35.4875),
    "trabzon": (41.0015, 39.7178),
    "samsun": (41.2867, 36.3300),
    "eskisehir": (39.7767, 30.5206),
    "diyarbakir": (37.9144, 40.2306),
    "mersin": (36.8000, 34.6333),
    "denizli": (37.7765, 29.0864),
    "london": (51.5074, -0.1278),
    "berlin": (52.5200, 13.4050),
    "paris": (48.8566, 2.3522),
    "amsterdam": (52.3676, 4.9041),
    "new york": (40.7128, -74.0060),
    "dubai": (25.2048, 55.2708),
}


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    R = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _coords_for(location: str, lat: Optional[float], lon: Optional[float]):
    """Return (lat, lon) from explicit coords or city lookup."""
    if lat is not None and lon is not None:
        return lat, lon
    return CITY_COORDS.get(location.lower().strip())


# ── Redis helpers ──────────────────────────────────────────────────────────────

async def check_velocity(redis: aioredis.Redis, user_id: str, ts: float) -> int:
    """
    Adds the current transaction timestamp to a sorted set and returns the
    number of transactions in the last VELOCITY_WINDOW_SECONDS seconds.
    """
    key = f"user:{user_id}:velocity"
    window = settings.VELOCITY_WINDOW_SECONDS
    cutoff = ts - window

    pipe = redis.pipeline()
    pipe.zadd(key, {str(ts): ts})
    pipe.zremrangebyscore(key, 0, cutoff)
    pipe.zcard(key)
    pipe.expire(key, window * 5)
    results = await pipe.execute()
    return results[2]  # zcard result


async def check_amount(
    redis: aioredis.Redis, user_id: str, tx_id: str, amount: float, ts: float
) -> float:
    """
    Stores (tx_id, amount) in a sorted set keyed by timestamp.
    Returns the average amount over the last 24 h EXCLUDING the current transaction.
    Returns 0 if there is no prior history.
    """
    key = f"user:{user_id}:amounts"
    lookback = settings.AMOUNT_LOOKBACK_HOURS * 3600
    cutoff = ts - lookback

    member = json.dumps({"id": tx_id, "amount": amount})

    pipe = redis.pipeline()
    pipe.zadd(key, {member: ts})
    pipe.zremrangebyscore(key, 0, cutoff)
    pipe.zrange(key, 0, -1, withscores=False)
    pipe.expire(key, int(lookback * 1.1))
    results = await pipe.execute()

    members: list[str] = results[2]
    prior_amounts = []
    for m in members:
        try:
            obj = json.loads(m)
            if obj["id"] != tx_id:
                prior_amounts.append(float(obj["amount"]))
        except Exception:
            pass

    if not prior_amounts:
        return 0.0
    return sum(prior_amounts) / len(prior_amounts)


async def check_location(
    redis: aioredis.Redis,
    user_id: str,
    location: str,
    lat: Optional[float],
    lon: Optional[float],
    ts: float,
) -> bool:
    """
    Compares the current location to the last known location.
    Returns True if the required travel speed exceeds MAX_TRAVEL_SPEED_KMH.
    """
    key = f"user:{user_id}:last_location"
    current_coords = _coords_for(location, lat, lon)

    prev_raw = await redis.get(key)

    # Always update last location
    if current_coords:
        await redis.set(
            key,
            json.dumps({"lat": current_coords[0], "lon": current_coords[1], "ts": ts}),
            ex=86400 * 2,
        )

    if not prev_raw or not current_coords:
        return False

    prev = json.loads(prev_raw)
    prev_coords = (prev["lat"], prev["lon"])
    prev_ts = prev["ts"]

    elapsed_h = (ts - prev_ts) / 3600.0
    if elapsed_h <= 0:
        return False

    distance_km = _haversine_km(prev_coords[0], prev_coords[1], current_coords[0], current_coords[1])

    if distance_km < 10:
        return False  # Same area — not suspicious

    required_speed = distance_km / elapsed_h
    is_impossible = required_speed > settings.MAX_TRAVEL_SPEED_KMH

    if is_impossible:
        logger.info(
            f"Impossible travel for {user_id}: {distance_km:.0f} km in {elapsed_h*60:.1f} min "
            f"({required_speed:.0f} km/h)"
        )

    return is_impossible


# ── Main entry point ───────────────────────────────────────────────────────────

async def detect(redis: aioredis.Redis, tx: dict) -> tuple[str, list[str], int]:
    """
    Hybrid detection pipeline:
      1. Run all three rule-based checks.
      2. Build a feature vector and store it for ML training.
      3. If exactly ONE rule fires (borderline), consult the Isolation Forest.
         If it also flags the transaction, escalate to SUSPICIOUS.

    Returns (status, fraud_reasons, fraud_score).
    """
    user_id: str = tx["user_id"]
    amount: float = float(tx["amount"])
    location: str = tx["location"]
    lat: Optional[float] = tx.get("latitude")
    lon: Optional[float] = tx.get("longitude")
    ts: float = datetime.fromisoformat(tx["timestamp"]).timestamp()
    tx_id: str = tx["id"]

    violations: list[str] = []

    # 1. Velocity check
    count = await check_velocity(redis, user_id, ts)
    if count > settings.VELOCITY_MAX_TRANSACTIONS:
        violations.append("velocity_exceeded")
        logger.debug(f"[{user_id}] velocity={count}")

    # 2. Amount check
    avg = await check_amount(redis, user_id, tx_id, amount, ts)
    if avg > 0 and amount > settings.AMOUNT_MULTIPLIER_THRESHOLD * avg:
        violations.append("amount_exceeded")
        logger.debug(f"[{user_id}] amount={amount:.2f} avg={avg:.2f}")

    # 3. Location / impossible-travel check
    #    Also capture distance and elapsed time for the ML feature vector
    key = f"user:{user_id}:last_location"
    prev_raw = await redis.get(key)
    current_coords = _coords_for(location, lat, lon)
    distance_km = 0.0
    elapsed_hours = 0.0
    if prev_raw and current_coords:
        prev = json.loads(prev_raw)
        elapsed_hours = min((ts - prev["ts"]) / 3600.0, 24.0)
        distance_km = _haversine_km(prev["lat"], prev["lon"], current_coords[0], current_coords[1])

    impossible = await check_location(redis, user_id, location, lat, lon, ts)
    if impossible:
        violations.append("impossible_travel")

    # ── Build feature vector for ML ────────────────────────────────────────────
    # [amount_ratio, velocity_count, distance_km, elapsed_hours]
    amount_ratio = (amount / avg) if avg > 0 else 1.0
    features = [
        float(amount_ratio),
        float(count),
        float(distance_km),
        float(elapsed_hours),
    ]

    # Store vector and potentially retrain the model
    sample_count = await _store_feature_vector(redis, tx_id, features, ts)
    await _maybe_retrain(redis, sample_count)

    # ── ML tiebreaker: exactly 1 rule fired → ask the model ───────────────────
    ml_escalated = False
    if len(violations) == 1:
        iso_score = _iso_score(features)
        if iso_score is not None and iso_score < ISO_THRESHOLD:
            violations.append("ml_isolation_forest")
            ml_escalated = True
            logger.info(
                f"[{user_id}] ML escalation: iso_score={iso_score:.4f} "
                f"(threshold={ISO_THRESHOLD}), features={features}"
            )
            try:
                from .metrics import ml_escalations_total
                ml_escalations_total.inc()
            except ImportError:
                pass

    is_fraud = len(violations) >= 2
    fraud_score = min(100, len(violations) * 30 + (10 if is_fraud else 0))
    status = "SUSPICIOUS" if is_fraud else "APPROVED"

    return status, violations, fraud_score
