import os


class Settings:
    # PostgreSQL
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:password@localhost:5432/ordersdb",
    )
    PG_NOTIFY_CHANNEL: str = "order_changes"

    # Redis
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379")
    REDIS_CHANNEL: str = "order_changes"

    # Server
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # How often (seconds) the listener pings PG to prevent idle disconnects
    PG_KEEPALIVE_INTERVAL: int = 30


settings = Settings()
