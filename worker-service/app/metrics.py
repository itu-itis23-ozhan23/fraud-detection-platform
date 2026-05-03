"""
Prometheus metrics for the Worker Service
==========================================
Exposed on a separate HTTP port (9091) via a simple prometheus_client
server so Prometheus can scrape the worker independently.
"""

from prometheus_client import Counter, Histogram, Gauge, start_http_server
import logging

logger = logging.getLogger(__name__)

# ── Transaction processing counters ───────────────────────────────────────────

transactions_processed_total = Counter(
    "fraud_worker_transactions_processed_total",
    "Total transactions processed by the anomaly detection engine",
)

transactions_approved_total = Counter(
    "fraud_worker_transactions_approved_total",
    "Total transactions that passed fraud checks",
)

transactions_suspicious_total = Counter(
    "fraud_worker_transactions_suspicious_total",
    "Total transactions flagged as suspicious",
)

# ── Violation counters ─────────────────────────────────────────────────────────

violation_velocity_total = Counter(
    "fraud_worker_violation_velocity_total",
    "Number of times the velocity rule was triggered",
)

violation_amount_total = Counter(
    "fraud_worker_violation_amount_total",
    "Number of times the amount threshold rule was triggered",
)

violation_location_total = Counter(
    "fraud_worker_violation_location_total",
    "Number of times the impossible-travel rule was triggered",
)

# ── ML model metrics ───────────────────────────────────────────────────────────

ml_escalations_total = Counter(
    "fraud_worker_ml_escalations_total",
    "Borderline transactions escalated to SUSPICIOUS by the Isolation Forest model",
)

ml_model_training_total = Counter(
    "fraud_worker_ml_model_training_total",
    "Number of times the Isolation Forest model was retrained",
)

ml_training_samples = Gauge(
    "fraud_worker_ml_training_samples",
    "Number of samples used in the most recent model training run",
)

# ── Processing latency ─────────────────────────────────────────────────────────

processing_latency_seconds = Histogram(
    "fraud_worker_processing_latency_seconds",
    "Time taken to process a single transaction (anomaly detection + DB write)",
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
)

# ── Kafka consumer lag ─────────────────────────────────────────────────────────

kafka_consumer_lag = Gauge(
    "fraud_worker_kafka_consumer_lag",
    "Current Kafka consumer lag for the fraud-worker-group",
    labelnames=["topic", "partition"],
)


def start_metrics_server(port: int = 9091) -> None:
    """Start the prometheus_client HTTP server on the given port."""
    try:
        start_http_server(port)
        logger.info("Prometheus metrics server started on port %d.", port)
    except Exception as exc:
        logger.warning("Could not start Prometheus metrics server: %s", exc)
