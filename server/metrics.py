from prometheus_client import Counter, Gauge, Histogram

# Active WebSocket connections at any point in time
ACTIVE_CONNECTIONS = Gauge(
    "ws_active_connections_total",
    "Number of currently open WebSocket connections",
)

# How many DB change notifications have been picked up by the asyncpg listener
DB_NOTIFICATIONS_RECEIVED = Counter(
    "db_notifications_received_total",
    "Total NOTIFY events received from PostgreSQL",
    ["event_type"],   # INSERT | UPDATE | DELETE
)

# How many messages have been published to Redis (one per DB notification)
REDIS_PUBLISHES = Counter(
    "redis_publishes_total",
    "Total messages published to Redis pub/sub channel",
)

# How many WebSocket broadcast calls were made
WS_BROADCASTS = Counter(
    "ws_broadcasts_total",
    "Total broadcast calls sent to connected WebSocket clients",
)

# Latency from DB NOTIFY to WebSocket delivery (measured in the broadcast step)
BROADCAST_LATENCY = Histogram(
    "ws_broadcast_latency_seconds",
    "Time from DB NOTIFY to WebSocket message delivered (seconds)",
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
)
