# 🛡️ Real-Time E-Commerce Anomaly & Fraud Detection Platform

A microservice-based platform that ingests, analyzes, and visualizes e-commerce payment transactions in real time — and exposes fraud intelligence to AI agents via Model Context Protocol (MCP).

---

## Table of Contents

1. [About the Project](#about-the-project)
2. [System Architecture](#system-architecture)
3. [Technology Choices & Rationale](#technology-choices--rationale)
4. [Anomaly Detection Logic](#anomaly-detection-logic)
5. [Architecture Decision Records](#architecture-decision-records)
6. [Observability](#observability)
7. [Running Tests](#running-tests)
8. [Prerequisites](#prerequisites)
9. [Getting Started](#getting-started)
10. [Usage Guide](#usage-guide)
11. [API Documentation](#api-documentation)
12. [MCP Documentation](#mcp-documentation)
13. [Script Reference](#script-reference)
14. [Frontend Guide](#frontend-guide)
15. [Troubleshooting](#troubleshooting)

---

## About the Project

This platform monitors payment transactions on an e-commerce system and detects fraudulent activity in real time.

**What it does:**

- Transactions are ingested via a REST API
- Each transaction is published to an Apache Kafka queue and processed asynchronously by the Worker service
- The Worker runs three independent anomaly checks per transaction using per-user Redis state
- Suspicious transactions are pushed to the frontend instantly over WebSocket
- All historical data is persisted in PostgreSQL
- AI agents can query the system through an MCP Server

---

## System Architecture

### Data Flow

```
[Client / Script]
       │
       │  POST /api/v1/transactions/
       ▼
┌─────────────────┐
│   API Service   │  ── saves transaction to DB as PENDING
│   (FastAPI)     │  ── publishes to Kafka "transactions" topic
│   Port: 8000    │  ── listens to Redis pub/sub for processed results
│   /ws           │  ── manages WebSocket connections (push to frontend)
└────────┬────────┘
         │ Kafka "transactions" topic
         ▼
┌─────────────────┐
│ Worker Service  │  ── consumes messages from Kafka
│   (Python)      │  ── runs 3 anomaly checks against Redis state (<5ms)
│                 │  ── updates transaction status: APPROVED / SUSPICIOUS
│                 │  ── publishes result to Redis pub/sub channel
└────────┬────────┘
         │ Redis Pub/Sub "transaction_events"
         ▼
┌─────────────────┐
│   API Service   │  ── broadcasts result to all connected WS clients
│   WebSocket     │
└────────┬────────┘
         │ WebSocket
         ▼
┌─────────────────┐
│    Frontend     │  ── live stream, charts, and alert panel update instantly
│    (React)      │
│    Port: 3000   │
└─────────────────┘

Additionally:
┌─────────────────┐
│   MCP Server    │  ── exposes get_recent_frauds and check_user_status tools
│   Port: 8080    │  ── reads directly from PostgreSQL
└─────────────────┘
```

### Services

| Service | Port | Responsibility |
|---------|------|----------------|
| `api-service` | 8000 | REST API, WebSocket hub, Kafka producer/consumer |
| `worker-service` | 9091 | Kafka consumer, anomaly engine (rules + ML), DB updater, metrics |
| `mcp-server` | 8080 | MCP tools for AI agents |
| `frontend` | 3000 | React dashboard |
| `postgresql` | 5432 | Primary data store |
| `redis` | 6379 | Per-user state cache + pub/sub + ML feature store |
| `kafka` | 9094 | Async message queue |
| `zookeeper` | 2181 | Kafka coordination |
| `prometheus` | 9090 | Metrics collection |
| `grafana` | 3001 | Metrics visualization (admin / fraud123) |

---

## Technology Choices & Rationale

### Backend: Python + FastAPI

FastAPI was chosen primarily for its **native async support**. Kafka, Redis, and PostgreSQL connections all run non-blocking with `async/await`, enabling high concurrency in a single process. Pydantic v2 enforces strict type validation at API boundaries, and Swagger UI is auto-generated at `/docs`.

### Message Queue: Apache Kafka

Kafka's key advantage over alternatives is **message durability and replayability**. Once a transaction is queued, it survives Worker restarts — the Worker picks up exactly where it left off. Kafka's partition model also enables horizontal scaling: multiple Worker instances can process different messages in parallel without code changes.

Compared to RabbitMQ: RabbitMQ offers simpler setup, but Kafka's high throughput and durability guarantees are better suited for financial event pipelines.

### Database: PostgreSQL

Financial transaction data requires **ACID guarantees** — PostgreSQL provides this out of the box. Its native `ARRAY` type stores `fraud_reasons` without a separate join table. Full async support is provided by the `asyncpg` driver.

### Cache / State Management: Redis

Redis is the heart of the anomaly detection engine. Three key types are maintained per user:

| Key Pattern | Type | Purpose | TTL |
|-------------|------|---------|-----|
| `user:{id}:velocity` | Sorted Set | Transaction count in the last 60s | 5 min |
| `user:{id}:amounts` | Sorted Set | Amount history over the last 24h | 25 h |
| `user:{id}:last_location` | String (JSON) | Previous location and timestamp | 48 h |

**Why Sorted Sets?** `ZREMRANGEBYSCORE` prunes out-of-window entries in O(log N) time. This means no PostgreSQL queries during anomaly checks — all three decisions are made in **~5 ms** from Redis alone.

### Inter-service Messaging: Redis Pub/Sub

Instead of opening a second Kafka consumer from the API service, Redis Pub/Sub was used for Worker → API result delivery. The Worker already writes to Redis; adding a separate Kafka topic would introduce unnecessary complexity. For this lightweight, unidirectional notification pattern, Pub/Sub is the right tool.

### Frontend: React + Recharts

Recharts is React-native, so it integrates directly with component state — no adapters needed. `AreaChart` handles the live time-series view, and `BarChart` covers the per-location breakdown. WebSocket messages flow straight into React state for zero-latency updates.

---

## Anomaly Detection Logic

A transaction is marked **SUSPICIOUS** when **at least 2 out of 3 criteria** are violated.

### Criterion 1: Velocity Check ⚡

**Rule:** The same user makes more than 5 transactions within the last 60 seconds.

**How it works:**
```
1. Current transaction's timestamp is added to a Redis ZSET
2. Entries older than 60s are removed with ZREMRANGEBYSCORE
3. ZCARD returns the count of remaining entries
4. If count > 5 → violation
```

### Criterion 2: Amount Check 💰

**Rule:** Transaction amount exceeds 3× the user's 24-hour average.

**How it works:**
```
1. Each transaction (id + amount) is stored as JSON in a Redis ZSET, scored by timestamp
2. Entries older than 24h are pruned automatically
3. Average is computed from all entries except the current transaction
4. If amount > 3 × average → violation
5. If the user has no prior history, this criterion is skipped (avoids false positives)
```

### Criterion 3: Impossible Travel Check ✈️

**Rule:** The speed required to travel between two consecutive transaction locations exceeds 800 km/h.

**How it works:**
```
1. User's previous transaction location and timestamp are fetched from Redis
2. Haversine formula calculates the great-circle distance between the two points
3. Required speed = distance / elapsed time (in hours)
4. If speed > 800 km/h → violation
5. If distance < 10 km → skipped (same-area movement is not suspicious)
```

**Haversine Formula** (accounts for Earth's curvature):
```
d = 2R × arcsin( √( sin²(Δlat/2) + cos(lat1)·cos(lat2)·sin²(Δlon/2) ) )
```
*where R = 6371 km*

### Criterion 4: ML Tiebreaker (Isolation Forest) 🤖

When exactly **one rule** fires, the transaction is in a gray zone — the rule-based system is uncertain. In this case, an **Isolation Forest** model is consulted.

**How it works:**

Every transaction is converted to a 4-dimensional feature vector:

```
[amount_ratio, velocity_count, distance_km, elapsed_hours]
```

- `amount_ratio` = `current_amount / 24h_avg` (1.0 if no history)
- `velocity_count` = transactions in last 60s
- `distance_km` = great-circle distance from previous transaction
- `elapsed_hours` = time since last transaction (capped at 24h)

Vectors are stored in a Redis ZSET (rolling window of the last 500 transactions). The model retrains every 50 new samples using `sklearn.ensemble.IsolationForest` with `contamination=0.08` (expected 8% fraud rate).

If the model's `score_samples()` output is below `−0.05`, the transaction is an outlier and gets escalated to **SUSPICIOUS** (reason: `ml_isolation_forest`).

**Why this design?**

Rule-based systems catch known patterns but miss subtle combinations. Isolation Forest excels at detecting multivariate outliers without labeled training data — it learns "normal" behavior and flags deviations. The hybrid approach avoids both:
- False negatives from rules alone (single-criterion fraud)
- False positives from ML alone (overly sensitive thresholds)

### Fraud Score

| Violations | Score | Status |
|-----------|-------|--------|
| 0 | 0 | APPROVED |
| 1 | 30 | APPROVED (unless ML escalates) |
| 2 | 70 | SUSPICIOUS |
| 3+ | 100 | SUSPICIOUS |

---

## Architecture Decision Records

ADRs document the key decisions made during the design of this system, including the trade-offs considered and alternatives rejected.

---

### ADR-001: Kafka + Redis dual-path for post-anomaly notifications

**Status:** Accepted

**Context:** After the Worker processes a transaction, the result needs to reach the API service and be broadcast to WebSocket clients. Two options were considered:

- **Option A: Kafka only** — Worker publishes to `processed_transactions` topic, API consumes it
- **Option B: Redis Pub/Sub only** — Worker publishes to Redis channel, API subscribes
- **Option C: Both** — Worker publishes to both; API uses whichever arrives first

**Decision:** Option C (both paths).

**Rationale:**

Kafka is durable and replayable — if the API restarts, it can replay missed messages from `processed_transactions`. However, Kafka adds ~50–100 ms of broker latency. Redis Pub/Sub delivers in ~1 ms but is ephemeral (messages lost if the subscriber is disconnected). Using both paths gets durability from Kafka and low latency from Redis. The React frontend deduplicates by transaction ID, so double-delivery is harmless.

**Consequences:** Two fewer lines of complexity in the Worker, slightly more network traffic. The deduplication logic lives client-side, which is already a standard pattern in UI state management.

---

### ADR-002: Redis Sorted Sets for time-window state management

**Status:** Accepted

**Context:** Three anomaly checks require maintaining per-user state over time windows (60s for velocity, 24h for amounts). Options:

- **Option A: Store in PostgreSQL** — use SQL WHERE timestamp > now()-interval
- **Option B: Redis with TTL keys** — simple key expiry
- **Option C: Redis Sorted Sets** with `ZREMRANGEBYSCORE`

**Decision:** Option C.

**Rationale:**

PostgreSQL queries during the hot path would add 5–20 ms of I/O per transaction. TTL keys can only expire the whole key, not individual entries — you'd need a background cleanup job to prune old entries. Sorted Sets prune old entries in-place with `ZREMRANGEBYSCORE` in **O(log N)** time, and `ZADD + ZCARD` counts the window contents atomically with Redis pipelining. The result: all three anomaly decisions are made in **~5 ms** with no disk I/O.

**Consequences:** Redis becomes a critical path dependency. The `restart: on-failure` Docker policy and Redis `healthcheck` mitigate availability risk.

---

### ADR-003: The 800 km/h travel speed threshold

**Status:** Accepted

**Context:** Impossible travel detection requires a maximum speed threshold. The threshold must be high enough to avoid false positives (e.g. a user who flies between cities) but low enough to catch fraud (e.g. card credentials shared with someone in another country).

**Decision:** 800 km/h — slightly above commercial aircraft cruising speed (~870 km/h) at sea level.

**Rationale:**

At 800 km/h, a user transacting in Istanbul and then Ankara 30 minutes later (~350 km / 0.5h = 700 km/h) would **not** be flagged — they could plausibly be on a plane. However, Istanbul to New York in 10 minutes (9000 km / 0.17h ≈ 53,000 km/h) would trigger the check. The 10 km dead-zone further eliminates noise from GPS drift or nearby locations with different city-name mappings.

**Alternatives rejected:** 300 km/h (too low — generates false positives for domestic flights), 2000 km/h (too high — misses intercontinental fraud).

---

### ADR-004: Hybrid ML layer with Isolation Forest

**Status:** Accepted

**Context:** Rule-based systems miss fraud that subtly violates only one criterion (e.g. a 2.9× amount spike — just below the 3× threshold — combined with slightly elevated velocity). A pure ML approach would require labeled data and an offline training pipeline.

**Decision:** Isolation Forest as an unsupervised online tiebreaker for single-violation transactions.

**Rationale:**

Isolation Forest is particularly well-suited here because:
1. It requires no labeled data — it learns "normal" unsupervised
2. It handles high-dimensional feature interactions that rules cannot
3. It is computationally lightweight — inference is O(n × depth) ≈ microseconds
4. It can be retrained incrementally as new transactions arrive

The model is trained on a 500-sample rolling window stored in Redis, which keeps memory usage bounded and ensures the model adapts to evolving transaction patterns. Contamination is set to 8%, reflecting a reasonable estimated fraud rate.

**Consequences:** Worker service requires `scikit-learn` and `numpy` in its Docker image (+~150 MB). The model is not persisted across restarts — it rebuilds from Redis data after 30 samples. False positives from the ML layer are logged with `reason: ml_isolation_forest` so they can be audited separately.

---

### ADR-005: Why a standalone MCP Server instead of embedding in the API

**Status:** Accepted

**Context:** The MCP tools (`get_recent_frauds`, `check_user_status`) could have been added as routes to the existing API service.

**Decision:** Separate `mcp-server` service.

**Rationale:**

MCP and REST serve different consumers with different transport requirements. REST serves the frontend with JSON over HTTP. MCP uses Server-Sent Events (SSE) transport and the MCP protocol — mixing these into one FastAPI app would require the SSE stream to stay open for AI agent connections, which would complicate the event loop and connection management. Separation also allows independent scaling: if AI agent traffic grows, only the MCP server needs more replicas.

---

## Observability

The platform ships with a pre-configured Prometheus + Grafana stack.

### Access

| Service | URL | Credentials |
|---------|-----|-------------|
| Grafana | http://localhost:3001 | admin / fraud123 |
| Prometheus | http://localhost:9090 | — |
| Worker metrics | http://localhost:9091/metrics | — |
| API metrics | http://localhost:8000/metrics | — |

### Pre-built Dashboard

Open Grafana → **Fraud Detection** folder → **Fraud Detection Platform** dashboard.

Panels included:
- Transactions/min and Suspicious Rate (stat panels)
- ML escalations and Kafka consumer lag
- Active WebSocket client count
- Transaction throughput over time (Approved vs Suspicious)
- Processing latency percentiles (p50 / p95 / p99)
- Violation breakdown by type (velocity / amount / location / ML)
- Kafka consumer lag per partition over time

### Key metrics

| Metric | Service | Description |
|--------|---------|-------------|
| `fraud_worker_transactions_processed_total` | Worker | Total processed |
| `fraud_worker_transactions_suspicious_total` | Worker | Total flagged |
| `fraud_worker_ml_escalations_total` | Worker | ML tiebreaker escalations |
| `fraud_worker_processing_latency_seconds` | Worker | Histogram (p50/p95/p99) |
| `fraud_worker_kafka_consumer_lag` | Worker | Per-partition lag gauge |
| `fraud_api_websocket_connections_active` | API | Live WS clients |
| `fraud_api_transactions_received_total` | API | REST submissions |

---

## Running Tests

The Worker service has a full unit test suite for the anomaly detection engine using `fakeredis` (no real Redis required).

```bash
cd worker-service

# Install test dependencies
pip install -r tests/requirements-test.txt

# Also install service dependencies
pip install -r requirements.txt

# Run all tests with verbose output
pytest tests/ -v
```

**Test coverage:**

| Module | Tests |
|--------|-------|
| `_haversine_km` | Same point, known distances, symmetry |
| `_coords_for` | Explicit coords, city lookup, case insensitivity, unknown city |
| `check_velocity` | Single tx, threshold boundary, window expiry, user isolation |
| `check_amount` | First tx (no history), average accuracy, self-exclusion, 24h expiry |
| `check_location` | No previous, same city, nearby coords, impossible travel, reasonable travel |
| `detect()` | Clean transaction, single violation (APPROVED), dual violation (SUSPICIOUS), scoring |

---

## Prerequisites

- **Docker Desktop** ≥ 24.0 ([download here](https://www.docker.com/products/docker-desktop/))
- **Docker Compose** v2 (bundled with Docker Desktop)
- At least **4 GB free RAM** (Kafka + ZooKeeper are memory-hungry)
- Available ports: `3000`, `3001`, `8000`, `8080`, `5432`, `6379`, `9090`, `9091`, `9094`

---

## Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/fraud-detection-platform.git
cd fraud-detection-platform
```

### 2. Start Docker Desktop

Open the application and wait for the whale icon in the menu bar to stop animating (~30s).

### 3. Start everything with one command

```bash
docker compose up --build
```

On the first run, Docker pulls images (~500 MB), installs Python dependencies, and builds the frontend. This takes **5–10 minutes**.

### 4. Wait for readiness

Watch for these lines in the terminal:

```
fraud_api     | INFO: Application startup complete.
fraud_worker  | Worker is running. Waiting for transactions...
fraud_mcp     | Starting MCP Server on 0.0.0.0:8080
```

> Kafka takes ~30–60 seconds to initialize. The API and Worker services retry automatically.

### 5. Access points

| Service | URL |
|---------|-----|
| 🖥️ Dashboard | http://localhost:3000 |
| 📚 API Docs (Swagger) | http://localhost:8000/docs |
| 🤖 MCP Server | http://localhost:8080/sse |
| 📊 Grafana | http://localhost:3001 (admin / fraud123) |
| 🔬 Prometheus | http://localhost:9090 |

---

## Usage Guide

### Quick test

1. Open `http://localhost:3000`
2. Wait for the green **"Live"** indicator in the top-right corner
3. In the **Anomaly Simulator** panel, click **🔥 Full Combo**
4. Within a few seconds:
   - Red 🚨 Suspicious entries appear in the live stream
   - Alert Panel shows new notifications (score 70 and 100)
   - Transaction Rate chart shows a spike
   - Fraud Rate in the header updates

### Test with scripts

```bash
# Single transaction
./scripts/manual-input.sh user_001 500.00 Istanbul 41.0082 28.9784

# Automated load test (60s, 3 req/s, 30% anomaly chance)
./scripts/auto-test.sh --duration=60 --rate=3 --anomaly-chance=30
```

---

## API Documentation

Full interactive Swagger UI: **http://localhost:8000/docs**

### `POST /api/v1/transactions/`

Ingest a new transaction. Saved as PENDING and published to Kafka for async processing.

**Request body:**
```json
{
  "user_id": "user_001",
  "amount": 499.99,
  "location": "Istanbul",
  "latitude": 41.0082,
  "longitude": 28.9784
}
```

> `latitude` and `longitude` are optional. If omitted, coordinates are looked up by city name.

**Response `201 Created`:**
```json
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "user_id": "user_001",
  "amount": 499.99,
  "location": "Istanbul",
  "status": "PENDING",
  "fraud_score": 0,
  "fraud_reasons": [],
  "processed_at": null,
  "created_at": "2024-01-15T14:30:00Z"
}
```

After the Worker processes it, `status` updates to `APPROVED` or `SUSPICIOUS` and the result is pushed via WebSocket.

---

### `GET /api/v1/users/{user_id}/status`

Returns transaction history and risk level for a specific user.

**Response:**
```json
{
  "user_id": "user_001",
  "total_transactions": 42,
  "suspicious_transactions": 8,
  "risk_level": "MEDIUM",
  "recent_transactions": [...]
}
```

**Risk levels:**

| Level | Condition |
|-------|-----------|
| `LOW` | Suspicious rate < 20% |
| `MEDIUM` | Suspicious rate 20–49% |
| `HIGH` | Suspicious rate ≥ 50% |

---

### `GET /api/v1/frauds/`

List suspicious transactions within a time range.

**Query parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `start` | Last 24h | ISO-8601 start datetime |
| `end` | Now | ISO-8601 end datetime |
| `limit` | 50 | Max results (up to 500) |
| `offset` | 0 | Pagination offset |

---

### `WebSocket /ws`

Real-time stream of transaction updates and fraud alerts.

**Connect:** `ws://localhost:8000/ws`

**Message types:**

```json
// Every processed transaction
{
  "type": "transaction",
  "data": {
    "id": "abc-123",
    "user_id": "user_001",
    "status": "SUSPICIOUS",
    "fraud_score": 70,
    "fraud_reasons": ["velocity_exceeded", "impossible_travel"]
  }
}

// Additional alert for SUSPICIOUS transactions only
{
  "type": "alert",
  "data": {
    "user_id": "user_001",
    "amount": 9500.00,
    "location": "Istanbul",
    "fraud_score": 70,
    "fraud_reasons": ["velocity_exceeded", "impossible_travel"],
    "message": "Suspicious transaction detected for user user_001"
  }
}
```

---

## MCP Documentation

The MCP Server exposes two tools so AI agents can query the fraud detection system directly.

### Connecting to Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "fraud-detection": {
      "url": "http://localhost:8080/sse"
    }
  }
}
```

### Testing with MCP CLI

```bash
pip install mcp[cli]
mcp dev http://localhost:8080/sse
```

---

### Tool: `get_recent_frauds`

Retrieve recent suspicious transactions.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `time_range_minutes` | 60 | Look-back window in minutes |
| `limit` | 20 | Max results (up to 100) |

**Example response:**
```json
{
  "time_range_minutes": 30,
  "total_found": 3,
  "frauds": [
    {
      "user_id": "user_007",
      "amount": 9500.00,
      "fraud_score": 100,
      "fraud_reasons": ["velocity_exceeded", "amount_exceeded", "impossible_travel"]
    }
  ]
}
```

---

### Tool: `check_user_status`

Get the fraud risk profile of a specific user.

| Parameter | Description |
|-----------|-------------|
| `user_id` | User identifier to look up |

**Example response:**
```json
{
  "user_id": "user_007",
  "risk_level": "HIGH",
  "total_transactions": 20,
  "suspicious_transactions": 12,
  "fraud_rate_pct": 60.0,
  "recent_transactions": [...]
}
```

---

## Script Reference

### `manual-input.sh`

Submit a single transaction manually.

```bash
./scripts/manual-input.sh <user_id> <amount> <location> [latitude] [longitude]

# Examples:
./scripts/manual-input.sh user_001 500.00 Istanbul 41.0082 28.9784
./scripts/manual-input.sh user_002 12500.00 Ankara
./scripts/manual-input.sh user_001 9999.99 Antalya 36.8969 30.7133
```

---

### `auto-test.sh`

Automated load and anomaly scenario generator.

```bash
./scripts/auto-test.sh [options]

Options:
  --duration=<seconds>        How long to run (default: 60)
  --rate=<req/second>         Transactions per second (default: 2)
  --anomaly-chance=<0-100>    Anomaly probability in % (default: 20)
  --users=<count>             Simulated user pool size (default: 10)
  --api-url=<url>             API base URL (default: http://localhost:8000)

# Examples:
./scripts/auto-test.sh
./scripts/auto-test.sh --duration=120 --rate=5 --anomaly-chance=40
./scripts/auto-test.sh --anomaly-chance=100   # all anomalies
```

**Generated anomaly scenarios:**

| Scenario | Criterion triggered |
|----------|-------------------|
| Velocity Burst | 8 transactions in ~5 seconds |
| Giant Amount | 5 normal transactions, then a 5× spike |
| Impossible Travel | Istanbul → Antalya within 1 second |

---

## Frontend Guide

### Anomaly Simulator

Located in the top-right panel of the dashboard. Fires real API requests to test fraud detection end-to-end. Change the `Target User ID` field to test against different users.

| Scenario | Criteria triggered | Expected score |
|----------|--------------------|---------------|
| ⚡ Velocity Burst | Velocity | 30 (APPROVED, needs 2nd criterion) |
| 💰 Giant Amount | Amount | 30 (APPROVED, needs 2nd criterion) |
| ✈️ Impossible Travel | Location | 30 (APPROVED, needs 2nd criterion) |
| 🔥 Full Combo | All three | 100 (SUSPICIOUS) |

> Note: A single criterion violation results in APPROVED. At least two must be violated for SUSPICIOUS.

### Browser Notifications

Click **🔔 Enable alerts** in the Alert Panel. After granting permission, a desktop notification fires for every SUSPICIOUS transaction — even when the tab is in the background.

### CSV Export

When alerts are present, click **↓ CSV** in the Alert Panel. Downloads `fraud-alerts-YYYY-MM-DD.csv` with columns: `timestamp, user_id, amount, location, fraud_score, fraud_reasons`.

---

## Troubleshooting

**"Docker daemon is not running"**
→ Open Docker Desktop and wait for the whale icon to stop animating.

**Services keep restarting**
→ Kafka takes 30–60s to initialize; API and Worker retry automatically. Follow logs:
```bash
docker compose logs -f worker-service
```

**Dashboard shows "Reconnecting…"**
→ The API service is still starting. Wait for `startup complete` in the logs, then refresh.
```bash
docker compose logs api-service
```

**Transaction Rate chart stays at zero**
→ The chart is real-time only and does not load historical data on page load. Fire a scenario from the Anomaly Simulator to populate it.

**Port conflict**
→ Edit the `ports:` entry in `docker-compose.yml`:
```yaml
ports:
  - "8001:8000"   # use 8001 on host if 8000 is taken
```

**Reset all data**
```bash
docker compose down -v   # removes PostgreSQL volume
docker compose up -d
```

**Restart a single service**
```bash
docker compose restart api-service
docker compose restart worker-service
```

---

## Project Structure

```
fraud-detection-platform/
├── docker-compose.yml
├── .env.example
├── README.md
├── scripts/
│   ├── manual-input.sh
│   └── auto-test.sh
├── api-service/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py                  # FastAPI app, lifespan, WebSocket endpoint
│       ├── config.py
│       ├── database.py
│       ├── models.py                # SQLAlchemy ORM model
│       ├── schemas.py               # Pydantic request/response schemas
│       ├── kafka_producer.py
│       ├── redis_client.py
│       ├── websocket_manager.py
│       └── routers/
│           ├── transactions.py
│           ├── users.py
│           └── frauds.py
├── worker-service/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py                  # Kafka consumer loop
│       ├── config.py                # Anomaly thresholds and all config
│       ├── database.py
│       └── anomaly_detector.py      # Velocity + Amount + Location checks
├── mcp-server/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       └── main.py                  # FastMCP: get_recent_frauds + check_user_status
└── frontend/
    ├── Dockerfile
    ├── nginx.conf                   # Reverse proxy for /api and /ws
    ├── package.json
    ├── vite.config.js
    ├── tailwind.config.js
    └── src/
        ├── App.jsx                  # Root layout, WebSocket init, tab navigation
        ├── index.css
        ├── main.jsx
        ├── components/
        │   ├── Header.jsx           # Stats pills, connection indicator
        │   ├── TransactionStream.jsx
        │   ├── FraudChart.jsx       # Area chart (time series) + Bar chart (location)
        │   ├── AlertPanel.jsx       # Fraud alerts, CSV export, browser notifications
        │   ├── UserDetail.jsx       # Per-user risk analysis
        │   └── AnomalySimulator.jsx # One-click fraud scenario panel
        └── services/
            ├── api.js
            └── websocket.js         # WS connection + browser push notifications
```
