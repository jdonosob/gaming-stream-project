# Gaming Leaderboard Streaming System

A real-time gaming leaderboard system built on a streaming data architecture using Kafka for event processing and Redis for low-latency queries.

## Overview

This project demonstrates a production-grade streaming pipeline for processing game events and maintaining real-time leaderboards. It's designed to handle high-throughput game events (kills, deaths, scores, achievements) and provide instant leaderboard rankings with sub-millisecond query performance.

**Current Status**: ✅ Producer and Processor are fully implemented and tested. API layer is planned for future development.

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

**API** (`src/api/`) ⏳ Planned
- FastAPI-based REST API for querying leaderboards and player statistics
- WebSocket support for real-time leaderboard updates
- Endpoints: top players, player rankings, historical stats, achievements

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

7. Access Kafka UI to monitor the system:
```
http://localhost:8080
```

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
│   └── api/                              # REST API (⏳ planned)
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

**Completed**:
- [x] Docker Compose infrastructure setup (Kafka, Zookeeper, Redis, Kafka UI)
- [x] Game event producer with realistic event simulation
- [x] Stream processor with real-time leaderboard updates
- [x] Idempotency pattern for duplicate event handling
- [x] Player statistics tracking (scores, actions, games joined)
- [x] Achievement feed with recent achievements

**In Progress**:
- [ ] REST API with FastAPI
  - [ ] GET /leaderboard/global (top N players)
  - [ ] GET /player/{player_id}/stats (detailed player stats)
  - [ ] GET /achievements/recent (recent achievements feed)
  - [ ] WebSocket endpoint for real-time updates

**Planned**:
- [ ] Time-windowed leaderboards (hourly, daily, weekly, monthly)
- [ ] Game-specific leaderboards (per game_id)
- [ ] Advanced statistics (KDA ratios, win rates, streaks)
- [ ] Frontend dashboard for leaderboard visualization
- [ ] Authentication and rate limiting
- [ ] Prometheus metrics and Grafana dashboards
- [ ] Horizontal scaling with multiple processor instances
- [ ] Data backup and recovery strategies
- [ ] Event schema validation with Avro/Protobuf
- [ ] CI/CD pipeline with GitHub Actions

## Contributing

Contributions are welcome! Please feel free to submit pull requests or open issues for bugs and feature requests.

## License

This project is open source and available under the [MIT License](LICENSE).

## Acknowledgments

Built with:
- [Apache Kafka](https://kafka.apache.org/) - Distributed event streaming
- [Redis](https://redis.io/) - In-memory data structure store
- [Kafka UI](https://github.com/provectus/kafka-ui) - Kafka management interface
