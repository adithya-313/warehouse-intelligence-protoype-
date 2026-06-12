"""Drop legacy warehouse tables from the PostgreSQL database."""

import logging

from sqlalchemy import text

from app.infrastructure.database import engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def drop_legacy_tables() -> None:
    """Drop the warehouse_nodes, warehouse_edges, and movement_telemetry tables."""
    logger.info("Dropping legacy warehouse tables...")
    with engine.begin() as conn:
        try:
            conn.execute(text("DROP TABLE IF EXISTS movement_telemetry CASCADE;"))
            logger.info("Dropped movement_telemetry.")
            conn.execute(text("DROP TABLE IF EXISTS warehouse_edges CASCADE;"))
            logger.info("Dropped warehouse_edges.")
            conn.execute(text("DROP TABLE IF EXISTS warehouse_nodes CASCADE;"))
            logger.info("Dropped warehouse_nodes.")
        except Exception as exc:
            logger.error("Error dropping legacy tables: %s", exc)
            raise
    logger.info("Legacy warehouse tables successfully dropped.")


if __name__ == "__main__":
    drop_legacy_tables()
