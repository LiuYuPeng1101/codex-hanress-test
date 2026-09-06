"""Bounded PostgreSQL access shared by all repositories."""

from dataclasses import dataclass

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url


@dataclass(frozen=True)
class DatabasePolicy:
    connect_seconds: int = 3
    pool_seconds: float = 2
    statement_ms: int = 5000
    lock_ms: int = 1000

    def __post_init__(self):
        if min(self.connect_seconds, self.pool_seconds, self.statement_ms, self.lock_ms) <= 0:
            raise ValueError("Database deadlines must be positive")
        if self.lock_ms > self.statement_ms:
            raise ValueError("Lock deadline must not exceed statement deadline")


def database_engine(url: str, policy: DatabasePolicy | None = None) -> Engine:
    policy = policy or DatabasePolicy()
    if make_url(url).drivername != "postgresql+psycopg":
        raise ValueError("Only postgresql+psycopg is supported")
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=0,
        pool_timeout=policy.pool_seconds,
        connect_args={
            "connect_timeout": policy.connect_seconds,
            "tcp_user_timeout": policy.statement_ms,
            "keepalives": 1,
            "keepalives_idle": 5,
            "keepalives_interval": 2,
            "keepalives_count": 2,
            "options": (
                f"-c statement_timeout={policy.statement_ms} "
                f"-c lock_timeout={policy.lock_ms} "
                f"-c idle_in_transaction_session_timeout={policy.statement_ms * 2}"
            ),
        },
    )
