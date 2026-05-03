import asyncio
import json
import logging
from aiokafka import AIOKafkaProducer
from .config import settings

logger = logging.getLogger(__name__)

_producer: AIOKafkaProducer | None = None


async def get_kafka_producer() -> AIOKafkaProducer:
    global _producer
    if _producer is None:
        _producer = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
        )
        for attempt in range(10):
            try:
                await _producer.start()
                logger.info("Kafka producer started.")
                return _producer
            except Exception as exc:
                logger.warning(f"Kafka not ready (attempt {attempt + 1}/10): {exc}")
                await asyncio.sleep(3)
        raise RuntimeError("Could not connect to Kafka after 10 attempts.")
    return _producer


async def send_transaction(transaction_data: dict) -> None:
    producer = await get_kafka_producer()
    await producer.send_and_wait(settings.KAFKA_TRANSACTIONS_TOPIC, transaction_data)
    logger.debug(f"Sent transaction {transaction_data.get('id')} to Kafka")


async def stop_producer() -> None:
    global _producer
    if _producer:
        await _producer.stop()
        _producer = None
