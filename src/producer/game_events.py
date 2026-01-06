"""
=============================================================================
GAME EVENT PRODUCER
=============================================================================
This script simulates a video game generating real-time events.

WHY IS THIS A SEPARATE COMPONENT?
---------------------------------
In a real system, this would be your actual game server sending events.
By keeping it separate, we achieve:
  1. Decoupling: The game doesn't need to know about leaderboards
  2. Scalability: Multiple game servers can send to the same Kafka
  3. Testability: We can simulate any scenario we want

HOW TO RUN:
-----------
  python -m src.producer.game_events

=============================================================================
"""

import json
import random
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from kafka import KafkaProducer
from kafka.errors import KafkaError


# =============================================================================
# CONFIGURATION
# =============================================================================
# In production, these would come from environment variables or a config file

KAFKA_BOOTSTRAP_SERVERS = "localhost:9092"  # Where to find Kafka
TOPIC_NAME = "game-events"                   # Topic to send events to

# Simulation settings
EVENTS_PER_SECOND = 5          # How fast to generate events (adjust for testing)
SIMULATION_DURATION = None     # None = run forever, or set seconds like 60


# =============================================================================
# SAMPLE DATA - Fake players and games for simulation
# =============================================================================

PLAYERS = [
    {"id": "player_001", "name": "NightHawk"},
    {"id": "player_002", "name": "ShadowBlade"},
    {"id": "player_003", "name": "PhoenixRise"},
    {"id": "player_004", "name": "ThunderStrike"},
    {"id": "player_005", "name": "IceQueen"},
    {"id": "player_006", "name": "DragonSlayer"},
    {"id": "player_007", "name": "StormChaser"},
    {"id": "player_008", "name": "NeonNinja"},
    {"id": "player_009", "name": "CyberWolf"},
    {"id": "player_010", "name": "GhostRider"},
]

GAMES = ["game_alpha", "game_beta", "game_gamma"]

# Different scoring actions with their point values
SCORING_ACTIONS = [
    {"action": "kill", "points": 100},
    {"action": "headshot", "points": 150},
    {"action": "assist", "points": 50},
    {"action": "objective_capture", "points": 200},
    {"action": "flag_carry", "points": 75},
    {"action": "healing", "points": 25},
    {"action": "revive", "points": 80},
]

ACHIEVEMENTS = [
    {"name": "First Blood", "rarity": "common"},
    {"name": "Double Kill", "rarity": "common"},
    {"name": "Triple Kill", "rarity": "uncommon"},
    {"name": "Unstoppable", "rarity": "rare"},
    {"name": "Godlike", "rarity": "epic"},
    {"name": "Ace", "rarity": "legendary"},
]


# =============================================================================
# EVENT GENERATORS
# =============================================================================
# Each function creates a specific type of event with all required fields


def generate_base_event(event_type: str) -> dict:
    """
    Create the base fields that ALL events must have.
    
    WHY THESE FIELDS?
    -----------------
    - event_id: Unique identifier for deduplication and tracking
    - event_type: Tells processors how to handle this event
    - timestamp: When it happened (critical for ordering and windowing)
    """
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def generate_player_scored_event() -> dict:
    """
    Generate a scoring event - the main event type for our leaderboard!
    
    This simulates a player earning points through various actions.
    """
    player = random.choice(PLAYERS)
    action = random.choice(SCORING_ACTIONS)
    
    event = generate_base_event("player_scored")
    event.update({
        "player_id": player["id"],
        "player_name": player["name"],
        "points": action["points"],
        "game_id": random.choice(GAMES),
        "action": action["action"],
    })
    return event


def generate_player_joined_event() -> dict:
    """
    Generate an event when a player joins a game.
    
    Useful for tracking active players and session analytics.
    """
    player = random.choice(PLAYERS)
    
    event = generate_base_event("player_joined")
    event.update({
        "player_id": player["id"],
        "player_name": player["name"],
        "game_id": random.choice(GAMES),
    })
    return event


def generate_achievement_event() -> dict:
    """
    Generate an achievement unlock event.
    
    These are rarer events - we'll make them ~10% probability.
    """
    player = random.choice(PLAYERS)
    achievement = random.choice(ACHIEVEMENTS)
    
    event = generate_base_event("achievement_unlocked")
    event.update({
        "player_id": player["id"],
        "player_name": player["name"],
        "achievement_name": achievement["name"],
        "achievement_rarity": achievement["rarity"],
    })
    return event


def generate_random_event() -> dict:
    """
    Generate a random event based on probability distribution.
    
    Distribution:
    - 70% player_scored (most common - it's a game!)
    - 20% player_joined  
    - 10% achievement (rare and exciting)
    """
    rand = random.random()
    
    if rand < 0.70:
        return generate_player_scored_event()
    elif rand < 0.90:
        return generate_player_joined_event()
    else:
        return generate_achievement_event()


# =============================================================================
# KAFKA PRODUCER
# =============================================================================

def create_producer() -> KafkaProducer:
    """
    Create and configure a Kafka producer.
    
    KEY CONFIGURATIONS EXPLAINED:
    -----------------------------
    
    bootstrap_servers: 
        Initial connection point(s) to the Kafka cluster.
        The producer will discover other brokers automatically.
    
    value_serializer: 
        How to convert Python objects to bytes for Kafka.
        We use JSON for human-readability and debugging.
        In production, you might use Avro or Protobuf for efficiency.
    
    acks: 
        How many brokers must confirm receipt before considering success.
        - 0: Don't wait (fastest, but might lose data)
        - 1: Wait for leader only (good balance)
        - 'all': Wait for all replicas (safest, slowest)
    
    retries:
        How many times to retry on failure.
        Kafka is distributed, so transient failures happen!
    
    linger_ms:
        How long to wait before sending a batch.
        Higher = better throughput, worse latency.
        0 = send immediately (good for our demo)
    """
    
    print("🔌 Connecting to Kafka...")
    
    producer = KafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        value_serializer=lambda v: json.dumps(v).encode('utf-8'),
        acks='all',           # Wait for all replicas (safety first!)
        retries=3,            # Retry up to 3 times on failure
        linger_ms=0,          # Send immediately (low latency for demo)
    )
    
    print("✅ Connected to Kafka successfully!")
    return producer


def on_send_success(record_metadata):
    """
    Callback when a message is successfully sent.
    
    record_metadata contains:
    - topic: Which topic it was sent to
    - partition: Which partition within the topic
    - offset: The message's position in that partition
    """
    print(f"   ✓ Sent to {record_metadata.topic} "
          f"[partition={record_metadata.partition}, "
          f"offset={record_metadata.offset}]")


def on_send_error(exception):
    """
    Callback when a message fails to send.
    
    In production, you'd want to:
    - Log the error with full details
    - Maybe retry with backoff
    - Alert if errors exceed threshold
    """
    print(f"   ✗ Error sending message: {exception}")


# =============================================================================
# MAIN SIMULATION LOOP
# =============================================================================

def run_simulation(
    events_per_second: int = EVENTS_PER_SECOND,
    duration_seconds: Optional[int] = SIMULATION_DURATION
):
    """
    Run the game event simulation.
    
    This is the main loop that:
    1. Generates random game events
    2. Sends them to Kafka
    3. Handles errors gracefully
    4. Provides visual feedback
    """
    
    producer = create_producer()
    
    print(f"\n🎮 Starting Game Event Simulation")
    print(f"   Topic: {TOPIC_NAME}")
    print(f"   Rate: {events_per_second} events/second")
    print(f"   Duration: {'Forever (Ctrl+C to stop)' if duration_seconds is None else f'{duration_seconds}s'}")
    print("-" * 50)
    
    events_sent = 0
    start_time = time.time()
    sleep_interval = 1.0 / events_per_second  # Time between events
    
    try:
        while True:
            # Check if we've exceeded our duration
            if duration_seconds and (time.time() - start_time) >= duration_seconds:
                print(f"\n⏱️  Duration reached. Stopping simulation.")
                break
            
            # Generate a random event
            event = generate_random_event()
            
            # Send to Kafka asynchronously
            # .send() returns a Future - the message is queued, not sent yet
            # .add_callback() and .add_errback() handle the result
            future = producer.send(TOPIC_NAME, value=event)
            future.add_callback(on_send_success)
            future.add_errback(on_send_error)
            
            # Pretty print the event
            events_sent += 1
            emoji = {
                "player_scored": "🎯",
                "player_joined": "👋", 
                "achievement_unlocked": "🏆"
            }.get(event["event_type"], "📨")
            
            print(f"\n{emoji} Event #{events_sent}: {event['event_type']}")
            print(f"   Player: {event.get('player_name', 'N/A')}")
            
            if event["event_type"] == "player_scored":
                print(f"   Action: {event['action']} (+{event['points']} pts)")
            elif event["event_type"] == "achievement_unlocked":
                print(f"   Achievement: {event['achievement_name']} ({event['achievement_rarity']})")
            
            # Wait before next event
            time.sleep(sleep_interval)
            
    except KeyboardInterrupt:
        print(f"\n\n🛑 Simulation stopped by user")
    
    finally:
        # IMPORTANT: Flush ensures all queued messages are sent before exit
        print(f"\n📤 Flushing remaining messages...")
        producer.flush()
        producer.close()
        
        elapsed = time.time() - start_time
        print(f"\n📊 Summary:")
        print(f"   Events sent: {events_sent}")
        print(f"   Duration: {elapsed:.1f}s")
        print(f"   Actual rate: {events_sent/elapsed:.1f} events/sec")


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    run_simulation()