# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a real-time gaming leaderboard system built on a streaming data architecture. The system processes game events through Kafka and maintains leaderboards in Redis for low-latency queries.

## Architecture

The system follows a streaming pipeline pattern with three main components:

**Producer** (`src/producer/`)
- Generates or ingests game events (kills, deaths, scores, etc.)
- Publishes events to Kafka topics
- Connects to Kafka on `localhost:9092` (external listener)

**Processor** (`src/processor/`)
- Consumes events from Kafka topics
- Performs aggregations and transformations
- Updates Redis sorted sets for leaderboard rankings
- Connects to Kafka on `localhost:9092` and Redis on `localhost:6379`

**API** (`src/api/`)
- REST API for querying leaderboards
- Reads from Redis for fast responses
- Exposes endpoints for rankings, player stats, etc.

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

Access Redis CLI:
```bash
docker exec -it redis redis-cli
```

Access Kafka container:
```bash
docker exec -it kafka bash
```

## Kafka Connection Details

When writing producers/consumers:
- **Bootstrap servers**: `localhost:9092`
- **From within Docker containers**: Use `kafka:9093` and `INTERNAL` listener
- **From host machine (Python/Node/etc.)**: Use `localhost:9092` and `EXTERNAL` listener

## Redis Usage

Leaderboard data structure pattern:
- Use Redis sorted sets with player IDs as members and scores as values
- Key naming convention should be established (e.g., `leaderboard:{game}:{metric}:{timewindow}`)
- Redis CLI available via: `docker exec -it redis redis-cli`

## Data Persistence

- **Kafka**: Message retention set to 7 days (604800000 ms)
- **Redis**: Append-only file persisted to `./data/redis/`
- The `data/` directory is git-ignored to prevent committing runtime state

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
