"""Local DuckDB warehouse (docs/architecture.md §7)."""

from engine.db.connection import connect, init_database
from engine.db.migrate import Migration, discover_migrations, migrate, pending_migrations

__all__ = [
    "Migration",
    "connect",
    "discover_migrations",
    "init_database",
    "migrate",
    "pending_migrations",
]
