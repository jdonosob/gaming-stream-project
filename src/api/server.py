"""
=============================================================================
REAL-TIME LEADERBOARD API
=============================================================================
This server provides:
  1. REST API endpoints for querying the leaderboard
  2. WebSocket connections for real-time updates

WHY FASTAPI?
------------
- Modern, fast, and async-first
- Built-in WebSocket support
- Automatic API documentation (Swagger UI)
- Great developer experience

HOW TO RUN:
-----------
  python -m src.api.server

Then open:
  - Dashboard: http://localhost:8000
  - API Docs: http://localhost:8000/docs

=============================================================================
"""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Optional

import redis.asyncio as redis  # Async Redis client!
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


# =============================================================================
# CONFIGURATION
# =============================================================================

REDIS_HOST = "localhost"
REDIS_PORT = 6379

LEADERBOARD_KEY = "leaderboard:global"
ACHIEVEMENTS_KEY = "achievements:recent"
PLAYER_STATS_PREFIX = "player:stats:"

# How often to push updates to WebSocket clients (seconds)
UPDATE_INTERVAL = 1.0


# =============================================================================
# DATA MODELS (Pydantic)
# =============================================================================
# These define the shape of our API responses

class PlayerScore(BaseModel):
    """A single player's leaderboard entry."""
    rank: int
    player_name: str
    score: int


class LeaderboardResponse(BaseModel):
    """Full leaderboard response."""
    updated_at: str
    total_players: int
    top_players: List[PlayerScore]


class Achievement(BaseModel):
    """A single achievement record."""
    player: str
    achievement: str
    rarity: str
    timestamp: str


class PlayerStats(BaseModel):
    """Detailed stats for a single player."""
    player_name: str
    total_score: int
    rank: Optional[int]
    events_count: int
    games_joined: int


# =============================================================================
# CONNECTION MANAGER (WebSocket)
# =============================================================================

class ConnectionManager:
    """
    Manages all active WebSocket connections.
    
    WHY DO WE NEED THIS?
    --------------------
    When a leaderboard update happens, we need to notify ALL connected clients.
    This manager keeps track of who's connected and provides a broadcast method.
    
    PATTERN: Pub/Sub at the application level
    """
    
    def __init__(self):
        # Set of active WebSocket connections
        self.active_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        """Accept a new WebSocket connection and add to our list."""
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"🔌 Client connected. Total connections: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection from our list."""
        self.active_connections.remove(websocket)
        print(f"🔌 Client disconnected. Total connections: {len(self.active_connections)}")
    
    async def broadcast(self, message: dict):
        """
        Send a message to ALL connected clients.
        
        This is the key method - when the leaderboard changes,
        we call this to push updates to everyone watching.
        """
        if not self.active_connections:
            return
        
        # Convert to JSON once
        message_json = json.dumps(message)
        
        # Send to all clients (handle disconnected ones gracefully)
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message_json)
            except Exception:
                disconnected.append(connection)
        
        # Clean up any broken connections
        for conn in disconnected:
            self.active_connections.remove(conn)


# Global connection manager
manager = ConnectionManager()


# =============================================================================
# REDIS CLIENT (Async)
# =============================================================================

# Global Redis connection (initialized on startup)
redis_client: Optional[redis.Redis] = None


async def get_redis() -> redis.Redis:
    """Get the Redis client (creates connection if needed)."""
    global redis_client
    if redis_client is None:
        redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=True,
        )
    return redis_client


# =============================================================================
# LEADERBOARD FUNCTIONS
# =============================================================================

async def fetch_leaderboard(top_n: int = 10) -> LeaderboardResponse:
    """
    Fetch the current leaderboard from Redis.
    
    REDIS COMMANDS:
    ---------------
    ZREVRANGE key start stop WITHSCORES
        - Gets members sorted by score (highest first)
    
    ZCARD key
        - Gets total number of members in the sorted set
    """
    r = await get_redis()
    
    # Get top N players with scores
    leaders = await r.zrevrange(LEADERBOARD_KEY, 0, top_n - 1, withscores=True)
    
    # Get total player count
    total = await r.zcard(LEADERBOARD_KEY)
    
    # Build response
    top_players = [
        PlayerScore(rank=i + 1, player_name=name, score=int(score))
        for i, (name, score) in enumerate(leaders)
    ]
    
    return LeaderboardResponse(
        updated_at=datetime.utcnow().isoformat(),
        total_players=total,
        top_players=top_players,
    )


async def fetch_recent_achievements(limit: int = 10) -> List[Achievement]:
    """
    Fetch recent achievements from Redis.
    
    REDIS COMMAND:
    --------------
    LRANGE key start stop
        - Gets elements from a list (0 to limit-1 for most recent)
    """
    r = await get_redis()
    
    # Get recent achievements (stored as JSON strings)
    raw_achievements = await r.lrange(ACHIEVEMENTS_KEY, 0, limit - 1)
    
    achievements = []
    for raw in raw_achievements:
        try:
            data = json.loads(raw)
            achievements.append(Achievement(**data))
        except (json.JSONDecodeError, KeyError):
            continue
    
    return achievements


async def fetch_player_stats(player_id: str) -> Optional[PlayerStats]:
    """Fetch detailed stats for a specific player."""
    r = await get_redis()
    
    stats_key = f"{PLAYER_STATS_PREFIX}{player_id}"
    stats = await r.hgetall(stats_key)
    
    if not stats:
        return None
    
    # Get player's rank
    player_name = stats.get("player_name", "Unknown")
    rank = await r.zrevrank(LEADERBOARD_KEY, player_name)
    
    return PlayerStats(
        player_name=player_name,
        total_score=int(stats.get("total_score", 0)),
        rank=rank + 1 if rank is not None else None,
        events_count=int(stats.get("events_count", 0)),
        games_joined=int(stats.get("games_joined", 0)),
    )


# =============================================================================
# BACKGROUND TASK: Push Updates
# =============================================================================

async def leaderboard_broadcaster():
    """
    Background task that periodically pushes leaderboard updates to all clients.
    
    WHY PERIODIC PUSH INSTEAD OF EVENT-DRIVEN?
    ------------------------------------------
    Option 1: Push on every event
      - Pros: Truly real-time
      - Cons: Could flood clients with updates (100 events/sec = 100 pushes/sec)
    
    Option 2: Push periodically (our choice)
      - Pros: Controlled update rate, less bandwidth
      - Cons: Slight delay (but 1 second is still "real-time" feeling)
    
    In production, you might use Redis Pub/Sub to trigger updates only when
    the leaderboard actually changes.
    """
    print("📡 Starting leaderboard broadcaster...")
    
    last_leaderboard = None
    
    while True:
        try:
            # Fetch current leaderboard
            leaderboard = await fetch_leaderboard(top_n=10)
            achievements = await fetch_recent_achievements(limit=5)
            
            # Only broadcast if something changed (optimization)
            current_state = json.dumps(leaderboard.model_dump())
            
            if current_state != last_leaderboard:
                await manager.broadcast({
                    "type": "leaderboard_update",
                    "data": {
                        "leaderboard": leaderboard.model_dump(),
                        "recent_achievements": [a.model_dump() for a in achievements],
                    }
                })
                last_leaderboard = current_state
            
        except Exception as e:
            print(f"❌ Broadcaster error: {e}")
        
        # Wait before next update
        await asyncio.sleep(UPDATE_INTERVAL)


# =============================================================================
# FASTAPI APP
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager - runs on startup and shutdown.
    
    We use this to:
    - Start the background broadcaster task on startup
    - Clean up connections on shutdown
    """
    # Startup
    print("🚀 Starting API server...")
    broadcaster_task = asyncio.create_task(leaderboard_broadcaster())
    
    yield  # Server runs here
    
    # Shutdown
    print("🛑 Shutting down...")
    broadcaster_task.cancel()
    if redis_client:
        await redis_client.close()


app = FastAPI(
    title="Gaming Leaderboard API",
    description="Real-time gaming leaderboard with WebSocket support",
    version="1.0.0",
    lifespan=lifespan,
)

# Allow CORS (for development)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# REST API ENDPOINTS
# =============================================================================

@app.get("/api/leaderboard", response_model=LeaderboardResponse)
async def get_leaderboard(top: int = 10):
    """
    Get the current leaderboard.
    
    Query Parameters:
    - top: Number of players to return (default: 10)
    """
    return await fetch_leaderboard(top_n=min(top, 100))


@app.get("/api/achievements", response_model=List[Achievement])
async def get_achievements(limit: int = 10):
    """Get recent achievements."""
    return await fetch_recent_achievements(limit=min(limit, 50))


@app.get("/api/player/{player_id}", response_model=PlayerStats)
async def get_player(player_id: str):
    """Get detailed stats for a specific player."""
    stats = await fetch_player_stats(player_id)
    if not stats:
        return {"error": "Player not found"}
    return stats


# =============================================================================
# WEBSOCKET ENDPOINT
# =============================================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time updates.
    
    HOW IT WORKS:
    -------------
    1. Client connects to ws://localhost:8000/ws
    2. Server accepts and adds to connection list
    3. Background task broadcasts updates to all connections
    4. When client disconnects, we clean up
    
    PROTOCOL:
    ---------
    Server sends JSON messages:
    {
        "type": "leaderboard_update",
        "data": {
            "leaderboard": {...},
            "recent_achievements": [...]
        }
    }
    """
    await manager.connect(websocket)
    
    # Send initial data immediately
    leaderboard = await fetch_leaderboard(top_n=10)
    achievements = await fetch_recent_achievements(limit=5)
    
    await websocket.send_json({
        "type": "leaderboard_update",
        "data": {
            "leaderboard": leaderboard.model_dump(),
            "recent_achievements": [a.model_dump() for a in achievements],
        }
    })
    
    try:
        # Keep connection alive and handle incoming messages
        while True:
            # We don't expect messages from client, but we need to keep
            # the connection alive and detect disconnects
            data = await websocket.receive_text()
            # Could handle client messages here (e.g., "subscribe to player X")
            
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# =============================================================================
# DASHBOARD (Simple HTML Page)
# =============================================================================

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """
    Serve a simple HTML dashboard.
    
    In production, you'd use a proper frontend framework (React, Vue, etc.)
    but this demonstrates the WebSocket integration.
    """
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🎮 Real-Time Leaderboard</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', system-ui, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            min-height: 100vh;
            color: #fff;
            padding: 20px;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        
        header {
            text-align: center;
            margin-bottom: 30px;
        }
        
        h1 {
            font-size: 2.5rem;
            margin-bottom: 10px;
            background: linear-gradient(90deg, #00d4ff, #7b2cbf);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        
        .status {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 8px 16px;
            background: rgba(255,255,255,0.1);
            border-radius: 20px;
            font-size: 0.9rem;
        }
        
        .status-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: #ef4444;
        }
        
        .status-dot.connected {
            background: #22c55e;
            animation: pulse 2s infinite;
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        
        .grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }
        
        @media (max-width: 768px) {
            .grid { grid-template-columns: 1fr; }
        }
        
        .card {
            background: rgba(255,255,255,0.05);
            border-radius: 16px;
            padding: 24px;
            border: 1px solid rgba(255,255,255,0.1);
        }
        
        .card h2 {
            font-size: 1.3rem;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .leaderboard-item {
            display: flex;
            align-items: center;
            padding: 12px;
            margin-bottom: 8px;
            background: rgba(255,255,255,0.05);
            border-radius: 10px;
            transition: transform 0.3s, background 0.3s;
        }
        
        .leaderboard-item:hover {
            transform: translateX(5px);
            background: rgba(255,255,255,0.1);
        }
        
        .leaderboard-item.top-1 {
            background: linear-gradient(90deg, rgba(255,215,0,0.2), transparent);
            border-left: 3px solid #ffd700;
        }
        
        .leaderboard-item.top-2 {
            background: linear-gradient(90deg, rgba(192,192,192,0.2), transparent);
            border-left: 3px solid #c0c0c0;
        }
        
        .leaderboard-item.top-3 {
            background: linear-gradient(90deg, rgba(205,127,50,0.2), transparent);
            border-left: 3px solid #cd7f32;
        }
        
        .rank {
            width: 40px;
            font-weight: bold;
            font-size: 1.2rem;
            color: #888;
        }
        
        .rank.gold { color: #ffd700; }
        .rank.silver { color: #c0c0c0; }
        .rank.bronze { color: #cd7f32; }
        
        .player-name {
            flex: 1;
            font-weight: 500;
        }
        
        .score {
            font-weight: bold;
            color: #00d4ff;
            font-size: 1.1rem;
        }
        
        .achievement-item {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 12px;
            margin-bottom: 8px;
            background: rgba(255,255,255,0.05);
            border-radius: 10px;
        }
        
        .achievement-icon {
            font-size: 1.5rem;
        }
        
        .achievement-info {
            flex: 1;
        }
        
        .achievement-name {
            font-weight: 500;
        }
        
        .achievement-player {
            font-size: 0.85rem;
            color: #888;
        }
        
        .rarity {
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 0.75rem;
            font-weight: bold;
            text-transform: uppercase;
        }
        
        .rarity.common { background: #4b5563; }
        .rarity.uncommon { background: #22c55e; }
        .rarity.rare { background: #3b82f6; }
        .rarity.epic { background: #a855f7; }
        .rarity.legendary { background: linear-gradient(90deg, #f59e0b, #ef4444); }
        
        .stats-bar {
            margin-top: 20px;
            padding-top: 20px;
            border-top: 1px solid rgba(255,255,255,0.1);
            display: flex;
            justify-content: space-around;
            text-align: center;
        }
        
        .stat-value {
            font-size: 1.5rem;
            font-weight: bold;
            color: #00d4ff;
        }
        
        .stat-label {
            font-size: 0.8rem;
            color: #888;
        }
        
        .empty-state {
            text-align: center;
            padding: 40px;
            color: #666;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🎮 Real-Time Leaderboard</h1>
            <div class="status">
                <span class="status-dot" id="statusDot"></span>
                <span id="statusText">Connecting...</span>
            </div>
        </header>
        
        <div class="grid">
            <div class="card">
                <h2>🏆 Top Players</h2>
                <div id="leaderboard">
                    <div class="empty-state">Waiting for data...</div>
                </div>
                <div class="stats-bar">
                    <div>
                        <div class="stat-value" id="totalPlayers">0</div>
                        <div class="stat-label">Total Players</div>
                    </div>
                    <div>
                        <div class="stat-value" id="lastUpdate">--:--:--</div>
                        <div class="stat-label">Last Update</div>
                    </div>
                </div>
            </div>
            
            <div class="card">
                <h2>⭐ Recent Achievements</h2>
                <div id="achievements">
                    <div class="empty-state">Waiting for achievements...</div>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        // WebSocket connection
        let ws;
        let reconnectInterval;
        
        function connect() {
            // Determine WebSocket URL based on current location
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${protocol}//${window.location.host}/ws`;
            
            ws = new WebSocket(wsUrl);
            
            ws.onopen = function() {
                console.log('✅ WebSocket connected');
                document.getElementById('statusDot').classList.add('connected');
                document.getElementById('statusText').textContent = 'Live';
                
                // Clear any reconnection interval
                if (reconnectInterval) {
                    clearInterval(reconnectInterval);
                    reconnectInterval = null;
                }
            };
            
            ws.onmessage = function(event) {
                const message = JSON.parse(event.data);
                
                if (message.type === 'leaderboard_update') {
                    updateLeaderboard(message.data.leaderboard);
                    updateAchievements(message.data.recent_achievements);
                }
            };
            
            ws.onclose = function() {
                console.log('❌ WebSocket disconnected');
                document.getElementById('statusDot').classList.remove('connected');
                document.getElementById('statusText').textContent = 'Reconnecting...';
                
                // Try to reconnect every 3 seconds
                if (!reconnectInterval) {
                    reconnectInterval = setInterval(connect, 3000);
                }
            };
            
            ws.onerror = function(error) {
                console.error('WebSocket error:', error);
            };
        }
        
        function updateLeaderboard(data) {
            const container = document.getElementById('leaderboard');
            const totalPlayers = document.getElementById('totalPlayers');
            const lastUpdate = document.getElementById('lastUpdate');
            
            totalPlayers.textContent = data.total_players;
            lastUpdate.textContent = new Date().toLocaleTimeString();
            
            if (!data.top_players || data.top_players.length === 0) {
                container.innerHTML = '<div class="empty-state">No players yet. Start the game!</div>';
                return;
            }
            
            container.innerHTML = data.top_players.map((player, index) => {
                const rankClass = index === 0 ? 'gold' : index === 1 ? 'silver' : index === 2 ? 'bronze' : '';
                const itemClass = index < 3 ? `top-${index + 1}` : '';
                const medal = index === 0 ? '🥇' : index === 1 ? '🥈' : index === 2 ? '🥉' : `#${player.rank}`;
                
                return `
                    <div class="leaderboard-item ${itemClass}">
                        <div class="rank ${rankClass}">${medal}</div>
                        <div class="player-name">${escapeHtml(player.player_name)}</div>
                        <div class="score">${player.score.toLocaleString()} pts</div>
                    </div>
                `;
            }).join('');
        }
        
        function updateAchievements(achievements) {
            const container = document.getElementById('achievements');
            
            if (!achievements || achievements.length === 0) {
                container.innerHTML = '<div class="empty-state">No achievements yet...</div>';
                return;
            }
            
            const rarityIcons = {
                'common': '⭐',
                'uncommon': '⭐⭐',
                'rare': '💎',
                'epic': '👑',
                'legendary': '🏆'
            };
            
            container.innerHTML = achievements.map(achievement => `
                <div class="achievement-item">
                    <div class="achievement-icon">${rarityIcons[achievement.rarity] || '⭐'}</div>
                    <div class="achievement-info">
                        <div class="achievement-name">${escapeHtml(achievement.achievement)}</div>
                        <div class="achievement-player">${escapeHtml(achievement.player)}</div>
                    </div>
                    <div class="rarity ${achievement.rarity}">${achievement.rarity}</div>
                </div>
            `).join('');
        }
        
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        // Start connection when page loads
        connect();
    </script>
</body>
</html>
    """


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    
    print("=" * 50)
    print("🎮 GAMING LEADERBOARD API")
    print("=" * 50)
    print("Dashboard: http://localhost:8000")
    print("API Docs:  http://localhost:8000/docs")
    print("WebSocket: ws://localhost:8000/ws")
    print("=" * 50)
    
    uvicorn.run(
        "src.api.server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,  # Auto-reload on code changes (dev only!)
    )