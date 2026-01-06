# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a real-time gaming leaderboard system built on a streaming data architecture. The system processes game events through Kafka and maintains leaderboards in Redis for low-latency queries.

**Tech Stack**: Python 3.9+, Apache Kafka, Redis, Docker Compose

**Status**: Core producer and processor components are implemented and tested.

## Architecture

The system follows a streaming pipeline pattern with three main components:

**Producer** (`src/producer/game_events.py`) - **IMPLEMENTED**
- Simulates game events: player_scored (70%), player_joined (20%), achievement_unlocked (10%)
- Publishes to Kafka topic `game-events`
- Configurable event rate (default: 5 events/second)
- Uses kafka-python with JSON serialization
- Run with: `python -m src.producer.game_events`

**Processor** (`src/processor/leaderboard_processor.py`) - **IMPLEMENTED**
- Consumes from Kafka topic `game-events` (consumer group: `leaderboard-processor`)
- Updates Redis sorted set `leaderboard:global` for rankings
- Stores detailed player stats in hashes `player:stats:{player_id}`
- Implements idempotency using `processed:events` set for deduplication
- Manual offset commits with at-least-once delivery semantics
- Displays leaderboard every 20 events
- Run with: `python -m src.processor.leaderboard_processor`

**API** (`src/api/`) - **NOT IMPLEMENTED YET**
- Planned: FastAPI-based REST API for querying leaderboards
- Will read from Redis for fast responses
- Endpoints for rankings, player stats, etc.

## Infrastructure Services

All services are orchestrated via Docker Compose:

**Kafka** (port 9092)
- Message broker for event streaming
- 7-day message retention window
- Auto-creates topics on first message
- Internal listener on 9093 for container-to-container communication

**Zookeeper** (port 2181)
- Coordination service for Kafka
- Manages broker metadata and topic configurations

**Redis** (port 6379)
- In-memory state store for leaderboards
- Uses sorted sets (ZADD, ZRANK, ZREVRANGE operations)
- Persists to `./data/redis` via append-only file

**Kafka UI** (port 8080)
- Web interface at http://localhost:8080
- Monitor topics, messages, and consumer lag

## Development Commands

### Infrastructure Setup

Start all infrastructure services:
```bash
docker-compose up -d
```

Stop all services:
```bash
docker-compose down
```

Stop and remove volumes (clean slate):
```bash
docker-compose down -v
```

View service logs:
```bash
docker-compose logs -f [service_name]  # e.g., kafka, redis, zookeeper
```

Check service health:
```bash
docker-compose ps
```

### Python Environment Setup

Install dependencies:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Running the Application

**IMPORTANT**: Run these commands from the project root, not from within the src/ directory.

1. Start infrastructure (if not already running):
```bash
docker-compose up -d
```

2. Run the producer (generates game events):
```bash
python -m src.producer.game_events
```

3. In a separate terminal, run the processor (updates leaderboard):
```bash
python -m src.processor.leaderboard_processor
```

Both processes should run simultaneously. The producer generates events, and the processor consumes them in real-time.

### Debugging and Inspection

Access Redis CLI:
```bash
docker exec -it redis redis-cli
```

Useful Redis commands:
```redis
# View leaderboard
ZREVRANGE leaderboard:global 0 -1 WITHSCORES

# View player stats
HGETALL player:stats:player_001

# Check recent achievements
LRANGE achievements:recent 0 9

# Count processed events
SCARD processed:events
```

Access Kafka container:
```bash
docker exec -it kafka bash
```

List Kafka topics:
```bash
docker exec -it kafka kafka-topics --bootstrap-server localhost:9093 --list
```

Describe a topic:
```bash
docker exec -it kafka kafka-topics --bootstrap-server localhost:9093 --describe --topic game-events
```

View consumer groups:
```bash
docker exec -it kafka kafka-consumer-groups --bootstrap-server localhost:9093 --list
```

Check consumer group lag:
```bash
docker exec -it kafka kafka-consumer-groups --bootstrap-server localhost:9093 --describe --group leaderboard-processor
```

## Kafka Connection Details

When writing producers/consumers:
- **Bootstrap servers**: `localhost:9092`
- **From within Docker containers**: Use `kafka:9093` and `INTERNAL` listener
- **From host machine (Python/Node/etc.)**: Use `localhost:9092` and `EXTERNAL` listener

## Redis Data Structures

**Current Implementation**:

`leaderboard:global` (Sorted Set)
- Members: player names
- Scores: total points accumulated
- Used for: Global rankings (ZREVRANGE, ZREVRANK, ZINCRBY)

`player:stats:{player_id}` (Hash)
- Fields: `total_score`, `events_count`, `player_name`, `last_active`, `games_joined`, `action:{action_type}`, etc.
- Used for: Detailed player statistics

`achievements:recent` (List)
- Max 100 entries (LTRIM keeps recent only)
- JSON-encoded achievement records

`processed:events` (Set)
- Event IDs for idempotency/deduplication
- Prevents duplicate event processing

**Future Extensions**:
- Add time-windowed leaderboards: `leaderboard:daily`, `leaderboard:weekly`
- Game-specific leaderboards: `leaderboard:{game_id}`
- Implement TTL cleanup for processed events set

## Event Types and Schemas

**player_scored** (70% of events)
```json
{
  "event_id": "uuid",
  "event_type": "player_scored",
  "timestamp": "ISO 8601",
  "player_id": "player_001",
  "player_name": "NightHawk",
  "points": 100,
  "game_id": "game_alpha",
  "action": "kill"  // kill, headshot, assist, objective_capture, etc.
}
```

**player_joined** (20% of events)
```json
{
  "event_id": "uuid",
  "event_type": "player_joined",
  "timestamp": "ISO 8601",
  "player_id": "player_001",
  "player_name": "NightHawk",
  "game_id": "game_alpha"
}
```

**achievement_unlocked** (10% of events)
```json
{
  "event_id": "uuid",
  "event_type": "achievement_unlocked",
  "timestamp": "ISO 8601",
  "player_id": "player_001",
  "player_name": "NightHawk",
  "achievement_name": "Double Kill",
  "achievement_rarity": "common"  // common, uncommon, rare, epic, legendary
}
```

## Data Persistence

- **Kafka**: Message retention set to 7 days (604800000 ms)
- **Redis**: Append-only file persisted to `./data/redis/`
- The `data/` directory is git-ignored to prevent committing runtime state

## Key Implementation Details

**Producer Configuration** (src/producer/game_events.py:222-228):
- `acks='all'`: Wait for all replicas before confirming send
- `retries=3`: Retry up to 3 times on failure
- `linger_ms=0`: Send immediately (low latency)
- JSON serialization for human-readable debugging

**Consumer Configuration** (src/processor/leaderboard_processor.py:151-158):
- `auto_offset_reset='earliest'`: Start from beginning on first run
- `enable_auto_commit=False`: Manual commits for reliability
- Consumer group: `leaderboard-processor` (allows horizontal scaling)
- At-least-once delivery semantics with idempotency

**Idempotency Pattern**:
- Every event has unique `event_id` (UUID)
- Processor checks `processed:events` set before processing
- Prevents duplicate scoring even if event is redelivered
- Critical for at-least-once delivery correctness

## Troubleshooting

**Zookeeper unhealthy errors**:
- The Zookeeper healthcheck uses `CMD-SHELL` format with netcat
- If healthcheck fails, check logs: `docker-compose logs zookeeper`
- Ensure `start_period: 10s` allows enough initialization time
- Try clean restart: `docker-compose down -v && docker-compose up -d`

**Kafka won't start**:
- Kafka waits for Zookeeper to be healthy
- Check Zookeeper is running: `docker-compose ps zookeeper`
- Verify network connectivity: `docker network ls | grep gaming-network`

**Port conflicts**:
- Check if ports 2181, 6379, 8080, 9092, 9093 are already in use
- On macOS/Linux: `lsof -i :9092` or `netstat -an | grep 9092`

**Redis connection issues**:
- Verify Redis is running: `docker exec -it redis redis-cli ping`
- Should return `PONG`
- Check append-only file permissions in `./data/redis/`

**Consumer lag monitoring**:
- Use Kafka UI at http://localhost:8080 to monitor consumer groups
- Check topic partitions and offset positions
- Review consumer group status via: `docker exec -it kafka kafka-consumer-groups --bootstrap-server localhost:9093 --list`
