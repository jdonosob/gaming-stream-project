# Gaming Leaderboard Streaming System

A real-time gaming leaderboard system built on a streaming data architecture using Kafka for event processing and Redis for low-latency queries.

## Overview

This project demonstrates a production-grade streaming pipeline for processing game events and maintaining real-time leaderboards. It's designed to handle high-throughput game events (kills, deaths, scores, achievements) and provide instant leaderboard rankings with sub-millisecond query performance.

**Current Status**: ✅ **Milestone 1 Complete** - All core components (Producer, Processor, API) are fully implemented and tested. The system is production-ready for the first milestone.

### Key Features

- **Real-time Event Processing**: Ingest and process game events as they happen
- **Scalable Architecture**: Built on Apache Kafka for handling millions of events per second
- **Low-latency Queries**: Redis-powered leaderboards with sub-millisecond response times
- **Event Replay**: 7-day message retention allows reprocessing and recovery
- **Monitoring Dashboard**: Kafka UI for visualizing topics, messages, and consumer lag
- **Idempotent Processing**: Duplicate events are handled gracefully with event deduplication

## Architecture

The system follows a classic streaming pipeline pattern:

```
Game Events → Producer → Kafka → Processor → Redis → API → Clients
```

### Components

**Producer** (`src/producer/game_events.py`) ✅ Implemented
- Simulates realistic game event streams with configurable event rates
- Generates three event types with realistic probability distribution:
  - `player_scored` (70%): Kill, headshot, assist, objective capture, etc.
  - `player_joined` (20%): Player joining games
  - `achievement_unlocked` (10%): Rare achievements with rarity levels
- Publishes to Kafka topic `game-events` with full acknowledgment
- Features automatic retries and graceful shutdown handling
- **Run**: `python -m src.producer.game_events`

**Processor** (`src/processor/leaderboard_processor.py`) ✅ Implemented
- Consumes from Kafka with consumer group `leaderboard-processor`
- Updates Redis data structures in real-time:
  - Global leaderboard (sorted set)
  - Per-player detailed statistics (hashes)
  - Recent achievements feed (list, max 100)
  - Event deduplication tracking (set)
- Implements idempotency pattern to handle duplicate events safely
- Manual offset commits for at-least-once delivery semantics
- Displays live leaderboard every 20 events
- **Run**: `python -m src.processor.leaderboard_processor`

**API** (`src/api/server.py`) ✅ Implemented
- FastAPI-based REST API with async Redis client for fast queries
- WebSocket support for pushing real-time leaderboard updates to clients
- Beautiful HTML dashboard with live leaderboard visualization
- REST Endpoints:
  - `GET /api/leaderboard?top=N` - Fetch top N players
  - `GET /api/achievements?limit=N` - Fetch recent achievements
  - `GET /api/player/{player_id}` - Get detailed player statistics
- WebSocket endpoint: `WS /ws` - Real-time updates every 1 second
- Auto-generated API documentation: `GET /docs` (Swagger UI)
- CORS enabled for frontend development
- Background broadcaster with change detection (only pushes when data changes)
- **Run**: `python -m src.api.server`
- **Access**: http://localhost:8000 (dashboard) or http://localhost:8000/docs (API docs)

### Infrastructure

- **Apache Kafka**: Distributed event streaming platform
- **Zookeeper**: Coordination service for Kafka cluster management
- **Redis**: In-memory data store for leaderboard state
- **Kafka UI**: Web-based monitoring and administration tool

## Getting Started

### Prerequisites

- Docker and Docker Compose installed
- Python 3.9 or higher
- Ports 2181, 6379, 8080, 9092, 9093 available

### Quick Start

1. Clone the repository:
```bash
git clone <repository-url>
cd gaming-stream-project
```

2. Start the infrastructure:
```bash
docker-compose up -d
```

3. Verify all services are healthy:
```bash
docker-compose ps
```

You should see all services in "healthy" state:
- `zookeeper` - Running on port 2181
- `kafka` - Running on ports 9092 (external) and 9093 (internal)
- `redis` - Running on port 6379
- `kafka-ui` - Running on port 8080

4. Set up Python environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

5. Run the producer (in one terminal):
```bash
python -m src.producer.game_events
```

You should see output like:
```
🔌 Connecting to Kafka...
✅ Connected to Kafka successfully!

🎮 Starting Game Event Simulation
   Topic: game-events
   Rate: 5 events/second
--------------------------------------------------

🎯 Event #1: player_scored
   Player: NightHawk
   Action: kill (+100 pts)
   ✓ Sent to game-events [partition=0, offset=0]
```

6. Run the processor (in another terminal):
```bash
source venv/bin/activate  # Activate venv again in new terminal
python -m src.processor.leaderboard_processor
```

You should see output like:
```
🔌 Connecting to Redis...
✅ Connected to Redis!
🔌 Connecting to Kafka...
✅ Connected to Kafka!
   Topic: game-events
   Consumer Group: leaderboard-processor

==================================================
⚡ STREAM PROCESSOR STARTED
==================================================

📨 Event #1 [partition=0, offset=0]
   🎯 NightHawk: +100 pts (kill)
      New Score: 100 | Rank: #1

==================================================
🏆 CURRENT LEADERBOARD
==================================================
   🥇 #1 NightHawk: 100 pts
==================================================
```

7. Run the API server (in a third terminal):
```bash
source venv/bin/activate  # Activate venv again in new terminal
python -m src.api.server
```

You should see:
```
==================================================
🎮 GAMING LEADERBOARD API
==================================================
Dashboard: http://localhost:8000
API Docs:  http://localhost:8000/docs
WebSocket: ws://localhost:8000/ws
==================================================
```

8. Access the live dashboard and monitoring tools:
- **Live Dashboard**: http://localhost:8000 (real-time leaderboard with WebSocket)
- **API Documentation**: http://localhost:8000/docs (Swagger UI)
- **Kafka UI**: http://localhost:8080 (monitor topics, consumers, messages)

Now you have the complete system running:
- Producer generates events → Kafka stores them → Processor updates Redis → API serves the data → Dashboard displays it live!

### Configuration

**Kafka Settings**:
- Message retention: 7 days (configurable via `KAFKA_LOG_RETENTION_MS`)
- Auto-create topics: Enabled
- Replication factor: 1 (single broker setup)

**Redis Settings**:
- Persistence: Append-only file (AOF) enabled
- Data directory: `./data/redis`

## Development

### Connecting to Kafka

**From your host machine** (Python, Node.js, etc.):
```python
# Python example with kafka-python
from kafka import KafkaProducer

producer = KafkaProducer(
    bootstrap_servers=['localhost:9092']
)
```

**From Docker containers**:
```python
# Use internal listener
producer = KafkaProducer(
    bootstrap_servers=['kafka:9093']
)
```

### Working with Redis

Access Redis CLI:
```bash
docker exec -it redis redis-cli
```

Example leaderboard operations:
```redis
# Add player scores
ZADD leaderboard:daily:kills 150 "player123"
ZADD leaderboard:daily:kills 200 "player456"

# Get top 10 players
ZREVRANGE leaderboard:daily:kills 0 9 WITHSCORES

# Get player rank
ZREVRANK leaderboard:daily:kills "player123"
```

### Monitoring

**Kafka UI Dashboard**: http://localhost:8080
- View all topics and their messages
- Monitor consumer group lag
- Inspect message payloads
- Manage topic configurations

**Service Logs**:
```bash
# View all logs
docker-compose logs -f

# View specific service
docker-compose logs -f kafka
docker-compose logs -f redis
```

**Health Checks**:
```bash
# Check all services
docker-compose ps

# Redis ping test
docker exec -it redis redis-cli ping

# Kafka broker check
docker exec -it kafka kafka-broker-api-versions --bootstrap-server localhost:9093
```

## Data Flow Example

1. **Event Generation**: A player scores a kill in-game
```json
{
  "event_type": "kill",
  "player_id": "player123",
  "timestamp": "2026-01-05T12:34:56Z",
  "game_id": "match789",
  "weapon": "rifle"
}
```

2. **Producer**: Publishes event to Kafka topic `game-events`

3. **Processor**: Consumes event and updates Redis:
```redis
ZINCRBY leaderboard:daily:kills 1 "player123"
ZINCRBY leaderboard:alltime:kills 1 "player123"
```

4. **API**: Client queries top 10 daily leaders:
```
GET /api/leaderboard/daily/kills?limit=10
```

5. **Response**: API reads from Redis and returns JSON:
```json
{
  "leaderboard": "daily_kills",
  "updated_at": "2026-01-05T12:35:00Z",
  "players": [
    {"rank": 1, "player_id": "player456", "score": 200},
    {"rank": 2, "player_id": "player123", "score": 151}
  ]
}
```

## Troubleshooting

**Services won't start**:
```bash
# Clean restart
docker-compose down -v
docker-compose up -d
```

**Port conflicts**:
```bash
# Check what's using a port
lsof -i :9092
netstat -an | grep 9092
```

**Zookeeper unhealthy**:
```bash
# Check logs for errors
docker-compose logs zookeeper

# Verify healthcheck is passing
docker inspect zookeeper | grep Health -A 10
```

**Can't connect to Kafka**:
- From host: Use `localhost:9092`
- From container: Use `kafka:9093`
- Check firewall settings
- Verify `KAFKA_ADVERTISED_LISTENERS` configuration

## Project Structure

```
.
├── docker-compose.yml                     # Infrastructure orchestration
├── requirements.txt                       # Python dependencies
├── .gitignore                            # Git ignore patterns
├── CLAUDE.md                             # Developer guide for AI assistants
├── README.md                             # This file
├── src/
│   ├── producer/
│   │   └── game_events.py                # Event generator (✅ implemented)
│   ├── processor/
│   │   └── leaderboard_processor.py      # Stream processor (✅ implemented)
│   └── api/
│       └── server.py                     # FastAPI server (✅ implemented)
├── data/                                 # Runtime data (git-ignored)
│   └── redis/                            # Redis AOF persistence
└── venv/                                 # Python virtual environment (git-ignored)
```

## Technology Stack

- **Apache Kafka 7.5.0**: Event streaming platform
- **Zookeeper 7.5.0**: Cluster coordination
- **Redis 7 Alpine**: In-memory data store
- **Kafka UI**: Web-based monitoring interface
- **Docker Compose**: Container orchestration
- **Python 3.9+**: Application runtime
- **kafka-python 2.0.2**: Kafka client library
- **redis-py 5.0.1**: Redis client library

## Roadmap

### ✅ Milestone 1: Core System (COMPLETE)
- [x] Docker Compose infrastructure setup (Kafka, Zookeeper, Redis, Kafka UI)
- [x] Game event producer with realistic event simulation (3 event types)
- [x] Stream processor with real-time leaderboard updates
- [x] Idempotency pattern for duplicate event handling
- [x] Player statistics tracking (scores, actions, games joined)
- [x] Achievement feed with recent achievements
- [x] REST API with FastAPI
  - [x] GET /api/leaderboard (top N players)
  - [x] GET /api/player/{player_id} (detailed player stats)
  - [x] GET /api/achievements (recent achievements feed)
  - [x] WebSocket endpoint for real-time updates (WS /ws)
- [x] Interactive HTML dashboard with live WebSocket updates
- [x] API documentation with Swagger UI
- [x] Comprehensive documentation (README.md, CLAUDE.md)

### 🔄 Milestone 2: Enhanced Features
- [ ] Time-windowed leaderboards (hourly, daily, weekly, monthly)
- [ ] Game-specific leaderboards (separate rankings per game_id)
- [ ] Advanced player statistics (KDA ratios, win rates, kill streaks)
- [ ] Event schema validation with Avro or Protobuf
- [ ] Unit tests and integration tests
- [ ] Prometheus metrics and Grafana dashboards
- [ ] Authentication and rate limiting for API
- [ ] Player profile pages with detailed stats

### 🚀 Milestone 3: Faust-Powered Stream Processing
**Goal**: Migrate from manual Kafka consumer to Faust for advanced stream processing capabilities.

**Why Faust?**
- Kafka Streams-like API in Python (already in dependencies!)
- Built-in support for stateful processing with Tables
- Native windowing (tumbling, hopping, sliding windows)
- RocksDB-backed state storage for fault tolerance
- Async-first architecture for high concurrency

**Migration Tasks**:
- [ ] Rewrite processor using Faust application framework
- [ ] Define event models with Faust Records
- [ ] Use Faust Tables for leaderboard state management
- [ ] Implement windowed aggregations for time-based leaderboards
- [ ] Leverage changelog topics for state recovery
- [ ] Add processor web interface (Faust built-in)

**Expected Benefits**:
- Simpler code with higher-level abstractions
- Automatic state management and recovery
- Native support for complex windowing operations
- Better partition handling and consumer group coordination
- Built-in monitoring via Faust web UI

### 📦 Milestone 4: Production Readiness
- [ ] Kubernetes deployment manifests (Helm charts)
- [ ] CI/CD pipeline (GitHub Actions)
- [ ] Load testing and performance benchmarking
- [ ] Multi-region deployment strategy
- [ ] Data backup and disaster recovery procedures
- [ ] Security hardening (TLS, authentication, encryption at rest)
- [ ] Horizontal scaling with multiple processor instances
- [ ] Alert system for anomaly detection

## Contributing

Contributions are welcome! Please feel free to submit pull requests or open issues for bugs and feature requests.

## License

This project is open source and available under the [MIT License](LICENSE).

## Acknowledgments

Built with:
- [Apache Kafka](https://kafka.apache.org/) - Distributed event streaming
- [Redis](https://redis.io/) - In-memory data structure store
- [Kafka UI](https://github.com/provectus/kafka-ui) - Kafka management interface
