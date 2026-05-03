"""
Worker Service — Fraud Detection Worker
Consumes raw transactions from Kafka "transactions" topic,
runs hybrid anomaly detection (rules + Isolation Forest ML),
updates the DB, then publishes results to:
  1. Kafka "processed_transactions" topic  (primary — satisfies async notification requirement)
  2. Redis pub/sub "transaction_events"    (secondary — low-latency WebSocket fan-out)

Observability
-------------
- Prometheus metrics exposed on port 9091 (/metrics)
- Kafka consumer lag polled every 30 s and exported as a gauge
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone

import redis.asyncio as aioredis
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.admin import AIOKafkaAdminClient

from .config import settings
from .database import wait_for_db, update_transaction_status
from .anomaly_detector import detect
from .metrics import (
    start_metrics_server,
    transactions_processed_total,
    transactions_approved_total,
    transactions_suspicious_total,
    violation_velocity_total,
    violation_amount_total,
    violation_location_total,
    processing_latency_seconds,
    kafka_consumer_lag,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ── Infrastructure helpers ────────────────────────────────────────────────────

async def get_redis() -> aioredis.Redis:
    for attempt in range(15):
        try:
            r = aioredis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
            await r.ping()
            logger.info("Redis connected.")
            return r
        except Exception as exc:
            logger.warning(f"Redis not ready ({attempt + 1}/15): {exc}")
            await asyncio.sleep(2)
    raise RuntimeError("Redis unavailable.")


async def get_consumer() -> AIOKafkaConsumer:
    for attempt in range(20):
        try:
            consumer = AIOKafkaConsumer(
                settings.KAFKA_TRANSACTIONS_TOPIC,
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                group_id=settings.KAFKA_GROUP_ID,
                value_deserializer=lambda v: json.loads(v.decode("utf-8")),
                auto_offset_reset="earliest",
                enable_auto_commit=True,
            )
            await consumer.start()
            logger.info("Kafka consumer started (topic: %s).", settings.KAFKA_TRANSACTIONS_TOPIC)
            return consumer
        except Exception as exc:
            logger.warning(f"Kafka not ready ({attempt + 1}/20): {exc}")
            await asyncio.sleep(3)
    raise RuntimeError("Kafka unavailable.")


async def get_producer() -> AIOKafkaProducer:
    for attempt in range(20):
        try:
            producer = AIOKafkaProducer(
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
            )
            await producer.start()
            logger.info("Kafka producer started (topic: %s).", settings.KAFKA_PROCESSED_TOPIC)
            return producer
        except Exception as exc:
            logger.warning(f"Kafka producer not ready ({attempt + 1}/20): {exc}")
            await asyncio.sleep(3)
    raise RuntimeError("Kafka producer unavailable.")


# ── Kafka consumer lag monitor ────────────────────────────────────────────────

async def kafka_lag_monitor(consumer: AIOKafkaConsumer) -> None:
    """
    Background task: every 30 s, compute how many messages are waiting
    in the 'transactions' topic that this consumer group has not yet read.

    Algorithm:
      lag(partition) = end_offset(partition) - committed_offset(partition)

    The result is published as a Prometheus gauge so Grafana can alert
    when the worker falls behind (e.g. during a traffic spike).
    """
    LAG_INTERVAL_SECONDS = 30
    LAG_ALERT_THRESHOLD = 100

    while True:
        await asyncio.sleep(LAG_INTERVAL_SECONDS)
        try:
            partitions = consumer.assignment()
            if not partitions:
                continue

            # Latest offsets available on the broker
            end_offsets = await consumer.end_offsets(list(partitions))

            total_lag = 0
            for tp, end_offset in end_offsets.items():
                committed = await consumer.committed(tp)
                committed_offset = committed if committed is not None else 0
                lag = max(0, end_offset - committed_offset)
                total_lag += lag
                kafka_consumer_lag.labels(
                    topic=tp.topic,
                    partition=str(tp.partition),
                ).set(lag)

            if total_lag > LAG_ALERT_THRESHOLD:
                logger.warning(
                    "Kafka consumer lag ALERT: %d messages behind "
                    "(threshold=%d). Worker may be overloaded.",
                    total_lag,
                    LAG_ALERT_THRESHOLD,
                )
            else:
                logger.debug("Kafka consumer lag: %d messages.", total_lag)

        except Exception as exc:
            logger.warning("Could not compute Kafka consumer lag: %s", exc)


# ── Core processing ───────────────────────────────────────────────────────────

async def process_transaction(
    tx: dict,
    redis: aioredis.Redis,
    producer: AIOKafkaProducer,
) -> None:
    tx_id = tx["id"]
    t_start = time.perf_counter()
    try:
        status, reasons, score = await detect(redis, tx)
        processed_at = datetime.now(timezone.utc)

        # ── Prometheus counters ────────────────────────────────────────────────
        transactions_processed_total.inc()
        if status == "SUSPICIOUS":
            transactions_suspicious_total.inc()
        else:
            transactions_approved_total.inc()

        if "velocity_exceeded" in reasons:
            violation_velocity_total.inc()
        if "amount_exceeded" in reasons:
            violation_amount_total.inc()
        if "impossible_travel" in reasons:
            violation_location_total.inc()

        # 1. Persist result to PostgreSQL
        await update_transaction_status(
            tx_id=tx_id,
            status=status,
            fraud_score=score,
            fraud_reasons=reasons,
            processed_at=processed_at,
        )

        # 2. Build event payload
        event = {
            "type": "transaction",
            "data": {
                **tx,
                "status": status,
                "fraud_score": score,
                "fraud_reasons": reasons,
                "processed_at": processed_at.isoformat(),
            },
        }

        # 3. Publish to Kafka "processed_transactions" topic
        #    → API service consumes this and fans out to WebSocket clients
        await producer.send_and_wait(settings.KAFKA_PROCESSED_TOPIC, event)

        # 4. Also publish to Redis pub/sub for low-latency fan-out
        await redis.publish("transaction_events", json.dumps(event, default=str))

        # 5. Additional fraud alert message for SUSPICIOUS transactions
        if status == "SUSPICIOUS":
            alert = {
                "type": "alert",
                "data": {
                    "id": tx_id,
                    "user_id": tx["user_id"],
                    "amount": tx["amount"],
                    "location": tx["location"],
                    "fraud_reasons": reasons,
                    "fraud_score": score,
                    "timestamp": processed_at.isoformat(),
                    "message": (
                        f"Suspicious transaction detected for user {tx['user_id']} "
                        f"(reasons: {', '.join(reasons)})"
                    ),
                },
            }
            await producer.send_and_wait(settings.KAFKA_PROCESSED_TOPIC, alert)
            await redis.publish("transaction_events", json.dumps(alert, default=str))

        elapsed = time.perf_counter() - t_start
        processing_latency_seconds.observe(elapsed)
        logger.info(f"Processed {tx_id}: {status} (score={score}, reasons={reasons}, latency={elapsed*1000:.1f}ms)")

    except Exception as exc:
        logger.exception(f"Error processing transaction {tx_id}: {exc}")


# ── Entry point ───────────────────────────────────────────────────────────────

async def run():
    # Start Prometheus metrics HTTP server (port 9091)
    start_metrics_server(port=9091)

    await wait_for_db()
    redis = await get_redis()
    consumer = await get_consumer()
    producer = await get_producer()

    logger.info("Worker is running. Waiting for transactions...")

    # Start Kafka lag monitor as a background task
    lag_task = asyncio.create_task(kafka_lag_monitor(consumer))

    try:
        async for msg in consumer:
            tx = msg.value
            await process_transaction(tx, redis, producer)
    finally:
        lag_task.cancel()
        await consumer.stop()
        await producer.stop()
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(run())
