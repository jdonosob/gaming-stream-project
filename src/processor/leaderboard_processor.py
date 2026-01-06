"""
=============================================================================
STREAM PROCESSOR - Leaderboard Engine
=============================================================================
This script reads game events from Kafka and maintains the leaderboard in Redis.

WHY IS THIS THE "HEART" OF STREAM PROCESSING?
----------------------------------------------
This is where we transform raw events into meaningful state:
  - Raw Event: "player_001 scored 100 points"
  - State: "player_001 total score is now 1,500 and ranked #3"

KEY CONCEPTS DEMONSTRATED:
--------------------------
  1. Consumer Groups: Multiple processors can share the workload
  2. Manual Offset Commits: We control when to mark messages as "done"
  3. Stateful Processing: We accumulate scores over time
  4. Idempotency: Processing the same event twice won't corrupt state

HOW TO RUN:
-----------
  python -m src.processor.leaderboard_processor

=============================================================================
"""

import json
import signal
import sys
from datetime import datetime
from typing import Optional

import redis
from kafka import KafkaConsumer
from kafka.errors import KafkaError


# =============================================================================
# CONFIGURATION
# =============================================================================

KAFKA_BOOTSTRAP_SERVERS = "localhost:9092"
KAFKA_TOPIC = "game-events"
KAFKA_CONSUMER_GROUP = "leaderboard-processor"  # Important! See explanation below

REDIS_HOST = "localhost"
REDIS_PORT = 6379

# Redis key names
LEADERBOARD_KEY = "leaderboard:global"           # Sorted set for rankings
PLAYER_STATS_PREFIX = "player:stats:"            # Hash for detailed stats
ACHIEVEMENTS_KEY = "achievements:recent"          # List for recent achievements
PROCESSED_EVENTS_KEY = "processed:events"         # Set for deduplication


# =============================================================================
# CONSUMER GROUP EXPLANATION
# =============================================================================
"""
WHAT IS A CONSUMER GROUP?
-------------------------
A consumer group is a set of consumers that work together to consume a topic.

Imagine you have 3 partitions in your topic:
  Partition 0: [event1, event4, event7, ...]
  Partition 1: [event2, event5, event8, ...]
  Partition 2: [event3, event6, event9, ...]

With ONE consumer in group "leaderboard-processor":
  Consumer A reads: Partition 0, 1, and 2 (all of them)

With THREE consumers in group "leaderboard-processor":
  Consumer A reads: Partition 0
  Consumer B reads: Partition 1
  Consumer C reads: Partition 2
  
This is how Kafka achieves PARALLELISM!

WHY DOES THE GROUP NAME MATTER?
-------------------------------
- Same group name = share the work (each event processed once)
- Different group name = each group gets ALL events

Example:
  - "leaderboard-processor" group: Updates leaderboard
  - "analytics-processor" group: Calculates statistics
  - Both read the SAME events independently!

This is the "multiple subscribers" concept you mentioned earlier.
"""


# =============================================================================
# REDIS CLIENT
# =============================================================================

def create_redis_client() -> redis.Redis:
    """
    Create a connection to Redis.
    
    We use a connection pool internally (handled by redis-py).
    """
    print("🔌 Connecting to Redis...")
    
    client = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        decode_responses=True,  # Return strings instead of bytes
    )
    
    # Test connection
    client.ping()
    print("✅ Connected to Redis!")
    
    return client


# =============================================================================
# KAFKA CONSUMER
# =============================================================================

def create_consumer() -> KafkaConsumer:
    """
    Create a Kafka consumer with specific configurations.
    
    KEY CONFIGURATIONS EXPLAINED:
    -----------------------------
    
    group_id:
        The consumer group this consumer belongs to.
        All consumers with the same group_id share the work.
    
    auto_offset_reset:
        What to do when there's no saved offset (first time running):
        - 'earliest': Start from the beginning (don't miss any events)
        - 'latest': Start from now (skip old events)
        We use 'earliest' to not miss anything!
    
    enable_auto_commit:
        If True: Kafka automatically saves your position periodically
        If False: YOU control when to save (safer!)
        We use False for reliability.
    
    value_deserializer:
        How to convert bytes back to Python objects.
        Mirror of the producer's serializer.
    """
    
    print("🔌 Connecting to Kafka...")
    
    consumer = KafkaConsumer(
        KAFKA_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        group_id=KAFKA_CONSUMER_GROUP,
        auto_offset_reset='earliest',      # Don't miss old events
        enable_auto_commit=False,          # We'll commit manually!
        value_deserializer=lambda m: json.loads(m.decode('utf-8')),
    )
    
    print(f"✅ Connected to Kafka!")
    print(f"   Topic: {KAFKA_TOPIC}")
    print(f"   Consumer Group: {KAFKA_CONSUMER_GROUP}")
    
    return consumer


# =============================================================================
# EVENT HANDLERS
# =============================================================================

def is_event_processed(redis_client: redis.Redis, event_id: str) -> bool:
    """
    Check if we've already processed this event.
    
    WHY DO WE NEED THIS? (Idempotency)
    -----------------------------------
    In distributed systems, the same event might be delivered more than once:
    - Network timeout after processing but before commit
    - Consumer restart
    - Kafka rebalancing
    
    Without deduplication:
      Event "player_001 +100" processed twice = +200 (WRONG!)
    
    With deduplication:
      Event "player_001 +100" processed twice = +100 (CORRECT!)
    
    We use a Redis SET to track processed event IDs.
    """
    return redis_client.sismember(PROCESSED_EVENTS_KEY, event_id)


def mark_event_processed(redis_client: redis.Redis, event_id: str):
    """
    Mark an event as processed.
    
    We also set an expiration (24 hours) to avoid infinite growth.
    In production, you might use a Bloom filter for better efficiency.
    """
    redis_client.sadd(PROCESSED_EVENTS_KEY, event_id)
    # Note: In production, implement TTL cleanup for this set


def handle_player_scored(redis_client: redis.Redis, event: dict):
    """
    Process a scoring event - update the leaderboard!
    
    REDIS COMMANDS USED:
    --------------------
    ZINCRBY key increment member
        - Increments the score of 'member' in sorted set 'key' by 'increment'
        - If member doesn't exist, it's added with the increment as score
        - Returns the new score
    
    HINCRBY key field increment
        - Increments a field in a hash
        - Used for detailed player statistics
    
    WHY ZINCRBY IS PERFECT:
    -----------------------
    It's atomic! Even with multiple processors running, scores stay correct.
    No race conditions, no locks needed.
    """
    player_id = event["player_id"]
    player_name = event["player_name"]
    points = event["points"]
    action = event.get("action", "unknown")
    
    # Update leaderboard (sorted set)
    # We use player_name for display, but player_id would be safer for production
    new_score = redis_client.zincrby(LEADERBOARD_KEY, points, player_name)
    
    # Update detailed player stats (hash)
    stats_key = f"{PLAYER_STATS_PREFIX}{player_id}"
    redis_client.hincrby(stats_key, "total_score", points)
    redis_client.hincrby(stats_key, "events_count", 1)
    redis_client.hincrby(stats_key, f"action:{action}", 1)
    redis_client.hset(stats_key, "player_name", player_name)
    redis_client.hset(stats_key, "last_active", event["timestamp"])
    
    # Get current rank
    rank = redis_client.zrevrank(LEADERBOARD_KEY, player_name)
    rank_display = rank + 1 if rank is not None else "?"
    
    print(f"   🎯 {player_name}: +{points} pts ({action})")
    print(f"      New Score: {int(new_score)} | Rank: #{rank_display}")


def handle_player_joined(redis_client: redis.Redis, event: dict):
    """
    Process a player join event.
    
    For now, we just track it in player stats.
    You could extend this to track online players, sessions, etc.
    """
    player_id = event["player_id"]
    player_name = event["player_name"]
    game_id = event["game_id"]
    
    # Initialize player stats if new
    stats_key = f"{PLAYER_STATS_PREFIX}{player_id}"
    redis_client.hsetnx(stats_key, "total_score", 0)  # Set only if not exists
    redis_client.hset(stats_key, "player_name", player_name)
    redis_client.hincrby(stats_key, "games_joined", 1)
    redis_client.hset(stats_key, "last_game", game_id)
    
    print(f"   👋 {player_name} joined {game_id}")


def handle_achievement(redis_client: redis.Redis, event: dict):
    """
    Process an achievement unlock event.
    
    REDIS COMMANDS USED:
    --------------------
    LPUSH key value
        - Adds value to the LEFT (beginning) of a list
        - Newest achievements appear first
    
    LTRIM key start stop
        - Keeps only elements from start to stop
        - We use this to limit the list to recent achievements (avoid unbounded growth)
    """
    player_name = event["player_name"]
    achievement_name = event["achievement_name"]
    rarity = event["achievement_rarity"]
    timestamp = event["timestamp"]
    
    # Create achievement record
    achievement_record = json.dumps({
        "player": player_name,
        "achievement": achievement_name,
        "rarity": rarity,
        "timestamp": timestamp,
    })
    
    # Add to recent achievements list
    redis_client.lpush(ACHIEVEMENTS_KEY, achievement_record)
    redis_client.ltrim(ACHIEVEMENTS_KEY, 0, 99)  # Keep only last 100
    
    # Emoji based on rarity
    rarity_emoji = {
        "common": "⭐",
        "uncommon": "⭐⭐",
        "rare": "💎",
        "epic": "👑",
        "legendary": "🏆",
    }.get(rarity, "⭐")
    
    print(f"   {rarity_emoji} {player_name} unlocked: {achievement_name} ({rarity})")


def process_event(redis_client: redis.Redis, event: dict) -> bool:
    """
    Route and process a single event.
    
    Returns True if processed successfully, False otherwise.
    """
    event_id = event.get("event_id")
    event_type = event.get("event_type")
    
    # Validate event
    if not event_id or not event_type:
        print(f"   ⚠️  Invalid event (missing id or type): {event}")
        return False
    
    # Check for duplicate (idempotency)
    if is_event_processed(redis_client, event_id):
        print(f"   ⏭️  Skipping duplicate event: {event_id[:8]}...")
        return True  # Not an error, just skip
    
    # Route to appropriate handler
    try:
        if event_type == "player_scored":
            handle_player_scored(redis_client, event)
        elif event_type == "player_joined":
            handle_player_joined(redis_client, event)
        elif event_type == "achievement_unlocked":
            handle_achievement(redis_client, event)
        else:
            print(f"   ❓ Unknown event type: {event_type}")
            return False
        
        # Mark as processed (after successful handling)
        mark_event_processed(redis_client, event_id)
        return True
        
    except KeyError as e:
        print(f"   ❌ Missing field in event: {e}")
        return False
    except Exception as e:
        print(f"   ❌ Error processing event: {e}")
        return False


# =============================================================================
# LEADERBOARD DISPLAY
# =============================================================================

def display_leaderboard(redis_client: redis.Redis, top_n: int = 5):
    """
    Print the current leaderboard.
    
    REDIS COMMAND:
    --------------
    ZREVRANGE key start stop WITHSCORES
        - Returns members from highest to lowest score
        - WITHSCORES includes the scores in the result
    """
    print("\n" + "=" * 50)
    print("🏆 CURRENT LEADERBOARD")
    print("=" * 50)
    
    # Get top N players with scores
    leaders = redis_client.zrevrange(LEADERBOARD_KEY, 0, top_n - 1, withscores=True)
    
    if not leaders:
        print("   No players yet!")
    else:
        for i, (player, score) in enumerate(leaders, 1):
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, "  ")
            print(f"   {medal} #{i} {player}: {int(score)} pts")
    
    print("=" * 50 + "\n")


# =============================================================================
# MAIN PROCESSING LOOP
# =============================================================================

def run_processor():
    """
    Main processing loop.
    
    THE PROCESSING PATTERN:
    -----------------------
    1. Poll Kafka for new messages (with timeout)
    2. Process each message
    3. Commit offsets (tell Kafka we're done)
    4. Repeat
    
    MANUAL COMMIT STRATEGY:
    -----------------------
    We commit after processing each batch. This means:
    - If we crash BEFORE commit: Events will be reprocessed (safe due to idempotency)
    - If we crash AFTER commit: We continue from where we left off
    
    This is "at-least-once" delivery semantics.
    """
    
    redis_client = create_redis_client()
    consumer = create_consumer()
    
    # Track statistics
    events_processed = 0
    last_leaderboard_display = 0
    display_interval = 20  # Show leaderboard every N events
    
    # Graceful shutdown handling
    running = True
    
    def signal_handler(sig, frame):
        nonlocal running
        print("\n\n🛑 Shutdown signal received. Finishing current batch...")
        running = False
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print("\n" + "=" * 50)
    print("⚡ STREAM PROCESSOR STARTED")
    print("=" * 50)
    print("Waiting for events... (Ctrl+C to stop)\n")
    
    try:
        while running:
            # Poll for messages (timeout = 1 second)
            # Returns a dict: {TopicPartition: [messages]}
            message_batch = consumer.poll(timeout_ms=1000)
            
            if not message_batch:
                # No messages, just continue polling
                continue
            
            # Process each message
            for topic_partition, messages in message_batch.items():
                for message in messages:
                    events_processed += 1
                    
                    print(f"\n📨 Event #{events_processed} "
                          f"[partition={message.partition}, offset={message.offset}]")
                    
                    # Process the event
                    success = process_event(redis_client, message.value)
                    
                    if not success:
                        # In production, you might send to a dead-letter queue
                        print("   ⚠️  Event processing failed (logged for review)")
            
            # Commit offsets after processing the batch
            # This tells Kafka "I've processed everything up to here"
            consumer.commit()
            
            # Periodically show the leaderboard
            if events_processed - last_leaderboard_display >= display_interval:
                display_leaderboard(redis_client)
                last_leaderboard_display = events_processed
    
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        raise
    
    finally:
        # Final leaderboard
        display_leaderboard(redis_client, top_n=10)
        
        # Clean shutdown
        print("📊 Final Statistics:")
        print(f"   Events processed: {events_processed}")
        
        print("\n🔌 Closing connections...")
        consumer.close()
        redis_client.close()
        print("👋 Processor shut down cleanly.")


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    run_processor()