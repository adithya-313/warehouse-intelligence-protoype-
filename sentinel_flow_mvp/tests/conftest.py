"""
Pytest shared fixtures and configuration for the Sentinel-Flow backend test suite.

Beginner Note: This file is automatically discovered by pytest and its fixtures
are available to ALL test files under tests/ without any explicit imports.
We set up three critical infrastructure mocks here:
  1. A mock database session (so tests never hit real PostgreSQL).
  2. Mock Redis transactional guards (so tests never need a real Redis server).
  3. A minimal FastAPI TestClient with overridden dependencies.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


# =========================================================================
# FIXTURE 1: Mock Database Session
# =========================================================================
# This replaces the real PostgreSQL session with a MagicMock that supports
# the chained query pattern used throughout our routes:
#   db.query(Model).filter(...).first()
#   db.add(obj), db.commit(), db.rollback()
#
# We set each method explicitly so that a junior developer can see exactly
# what a mock database session looks like.

@pytest.fixture
def mock_db_session():
    """Creates a mock SQLAlchemy ORM session that NEVER touches a real database.

    Arrange: Every chainable method (query, filter, order_by, etc.) returns
    another mock so that calls like:
        db.query(Patient).filter(...).first()
    do not raise AttributeError — they simply return another MagicMock.

    Action methods (add, flush, commit, rollback, close) are real MagicMocks
    that track whether they were called but do nothing.
    """
    session = MagicMock(spec=Session)

    # --- Query chain: db.query(X).filter(Y).first() returns None by default ---
    # This is the default "not found" behavior for patient lookup.
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.first.return_value = None
    mock_filter.with_for_update.return_value = mock_filter
    mock_query.filter.return_value = mock_filter
    session.query.return_value = mock_query

    # --- Transaction lifecycle methods ---
    session.add = MagicMock()
    session.flush = MagicMock()
    session.commit = MagicMock()
    session.rollback = MagicMock()
    session.close = MagicMock()

    return session


# =========================================================================
# FIXTURE 2: Mock Redis Transactional Guards (autouse)
# =========================================================================
# The POS checkout route calls 5 Redis functions before and after the DB
# transaction. This fixture patches ALL of them so tests do not need a
# running Redis server.
#
# We use autouse=True so every test automatically gets these mocks without
# having to declare the fixture explicitly.

@pytest.fixture(autouse=True)
def mock_redis_guards():
    """Patches all Redis transactional guard functions in the pos_router module.

    Beginner Note: The '@autouse=True' decorator means this fixture runs
    automatically before EVERY test in the entire tests/ directory. The
    'yield' gives the test control, and cleanup happens after.

    The patched functions return safe defaults:
      - is_duplicate_checkout_request → False (not a duplicate)
      - is_above_checkout_rate_limit  → False (not rate-limited)
      - verify_inventory_lock_exists  → True  (lock is valid)
      - mark_checkout_completed       → None  (no-op)
      - release_inventory_lock        → None  (no-op)
    """
    with patch("app.api.pos_router.is_duplicate_checkout_request", new_callable=AsyncMock) as mock_is_dup, \
         patch("app.api.pos_router.is_above_checkout_rate_limit", new_callable=AsyncMock) as mock_is_rate, \
         patch("app.api.pos_router.mark_checkout_completed", new_callable=AsyncMock) as mock_mark_complete, \
         patch("app.api.pos_router.try_acquire_inventory_lock", new_callable=AsyncMock) as mock_acquire_lock:

        # Default safe values for a "happy path" checkout
        mock_is_dup.return_value = False
        mock_is_rate.return_value = False
        mock_mark_complete.return_value = None
        mock_acquire_lock.return_value = True

        yield {
            "is_duplicate_checkout_request": mock_is_dup,
            "is_above_checkout_rate_limit": mock_is_rate,
            "mark_checkout_completed": mock_mark_complete,
            "try_acquire_inventory_lock": mock_acquire_lock,
        }


# =========================================================================
# FIXTURE 3: Minimal Test FastAPI Application
# =========================================================================
# Instead of importing the full main.create_application() (which would
# try to load Chronos, connect to PostgreSQL, and run the lifespan), we
# build a minimal FastAPI app with just the POS router and overridden
# dependencies. This keeps tests fast and isolated.

@pytest.fixture
def test_app(mock_db_session):
    """Creates a lightweight FastAPI instance with ONLY the POS router.

    We override the real database session and tenant dependencies with
    our mocks so the route handler thinks it has a real session but is
    actually talking to MagicMock objects.
    """
    from app.api.pos_router import router as pos_router
    from app.infrastructure.database import get_database_session
    from app.api.dependencies import get_current_tenant
    from app.services.kafka_producer import publish_medication_sold

    app = FastAPI()
    app.include_router(pos_router, prefix="/api/v1/pos")

    # --------------------------------------------------------------
    # Dependency Overrides: Swap real dependencies with test doubles
    # --------------------------------------------------------------
    # get_database_session: normally opens a PostgreSQL connection.
    # We replace it with a lambda that returns our MagicMock session.
    app.dependency_overrides[get_database_session] = lambda: mock_db_session

    # get_current_tenant: normally reads the X-Tenant-ID header.
    # We replace it with a fixed test tenant so we don't need to send
    # the header in every test request.
    app.dependency_overrides[get_current_tenant] = lambda: "test-tenant-001"

    return app


@pytest.fixture
def client(test_app):
    """FastAPI TestClient bound to our minimal test application.

    This is the object you use to send HTTP requests in tests:
        response = client.post("/api/v1/pos/checkout", json={...})
        assert response.status_code == 200
    """
    with TestClient(test_app) as c:
        yield c
