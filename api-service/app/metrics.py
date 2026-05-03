"""
Prometheus metrics for the API Service
=======================================
Custom counters and gauges exposed at /metrics alongside the
auto-instrumented FastAPI request metrics.
"""

from prometheus_client import Counter, Gauge, Histogram

# ── Transaction counters ───────────────────────────────────────────────────────

transactions_received_total = Counter(
    "fraud_api_transactions_received_total",
    "Total number of transactions submitted via the REST API",
)

transactions_approved_total = Counter(
    "fraud_api_transactions_approved_total",
    "Total number of transactions that were approved by the fraud engine",
)

transactions_suspicious_total = Counter(
    "fraud_api_transactions_suspicious_total",
    "Total number of transactions flagged as suspicious by the fraud engine",
)

# ── WebSocket metrics ──────────────────────────────────────────────────────────

websocket_connections_active = Gauge(
    "fraud_api_websocket_connections_active",
    "Number of currently connected WebSocket clients",
)

websocket_messages_broadcast_total = Counter(
    "fraud_api_websocket_messages_broadcast_total",
    "Total number of messages broadcast to WebSocket clients",
)

# ── Kafka consumer metrics ─────────────────────────────────────────────────────

kafka_consumer_lag = Gauge(
    "fraud_api_kafka_consumer_lag",
    "Estimated Kafka consumer lag for the api-ws-broadcaster group",
    labelnames=["topic"],
)

kafka_messages_consumed_total = Counter(
    "fraud_api_kafka_messages_consumed_total",
    "Total messages consumed from Kafka processed_transactions topic",
)

# ── Latency histograms ─────────────────────────────────────────────────────────

transaction_processing_latency_seconds = Histogram(
    "fraud_api_transaction_processing_latency_seconds",
    "End-to-end latency from transaction submission to WebSocket broadcast",
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)
