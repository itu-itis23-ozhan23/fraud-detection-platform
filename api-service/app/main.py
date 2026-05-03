import asyncio
import json
import logging
from contextlib import asynccontextmanager

from aiokafka import AIOKafkaConsumer
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import make_asgi_app

from .config import settings
from .database import init_db
from .kafka_producer import get_kafka_producer, stop_producer
from .redis_client import get_redis_client
from .websocket_manager import WebSocketManager
from .routers import transactions, users, frauds
from .metrics import (
    websocket_connections_active,
    websocket_messages_broadcast_total,
    kafka_messages_consumed_total,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ws_manager = WebSocketManager()


async def kafka_processed_listener():
    """
    Consume from the 'processed_transactions' Kafka topic and broadcast
    each event to all connected WebSocket clients.

    This is the PRIMARY notification path: Worker → Kafka → API → WebSocket.
    Kafka provides durability and replayability for post-anomaly notifications.
    """
    for attempt in range(20):
        try:
            consumer = AIOKafkaConsumer(
                settings.KAFKA_PROCESSED_TOPIC,
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                group_id="api-ws-broadcaster",
                value_deserializer=lambda v: json.loads(v.decode("utf-8")),
                auto_offset_reset="latest",   # only new messages after startup
                enable_auto_commit=True,
            )
            await consumer.start()
            logger.info(
                "Kafka processed_transactions consumer started (topic: %s).",
                settings.KAFKA_PROCESSED_TOPIC,
            )
            try:
                async for msg in consumer:
                    event = msg.value
                    kafka_messages_consumed_total.inc()
                    await ws_manager.broadcast(json.dumps(event, default=str))
                    websocket_messages_broadcast_total.inc()
            finally:
                await consumer.stop()
            return
        except Exception as exc:
            logger.warning(f"Kafka consumer not ready ({attempt + 1}/20): {exc}")
            await asyncio.sleep(3)


async def redis_pubsub_listener():
    """
    SECONDARY notification path: Worker → Redis pub/sub → API → WebSocket.
    Provides lower latency (~1 ms) as a complement to the Kafka consumer.
    Deduplication is handled client-side (React upserts by transaction ID).
    """
    redis = await get_redis_client()
    pubsub = redis.pubsub()
    await pubsub.subscribe("transaction_events")
    logger.info("Redis pub/sub subscriber started on channel 'transaction_events'.")

    async for message in pubsub.listen():
        if message["type"] == "message":
            try:
                await ws_manager.broadcast(message["data"])
            except Exception as exc:
                logger.error(f"WS broadcast error: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up API Service...")
    await init_db()
    await get_kafka_producer()

    # Start both listeners as background tasks
    kafka_task = asyncio.create_task(kafka_processed_listener())
    redis_task = asyncio.create_task(redis_pubsub_listener())

    yield

    logger.info("Shutting down API Service...")
    kafka_task.cancel()
    redis_task.cancel()
    await stop_producer()


app = FastAPI(
    title="Fraud Detection Platform — API Service",
    version="1.0.0",
    description="Real-time e-commerce fraud detection REST API with WebSocket support",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prometheus: auto-instrument all HTTP endpoints + expose /metrics
Instrumentator().instrument(app).expose(app, include_in_schema=False)

# Also mount the full prometheus_client ASGI app at /metrics (richer output)
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

app.include_router(transactions.router, prefix="/api/v1/transactions", tags=["Transactions"])
app.include_router(users.router, prefix="/api/v1/users", tags=["Users"])
app.include_router(frauds.router, prefix="/api/v1/frauds", tags=["Frauds"])


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    websocket_connections_active.inc()
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
        websocket_connections_active.dec()


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "healthy", "service": "api-service"}
