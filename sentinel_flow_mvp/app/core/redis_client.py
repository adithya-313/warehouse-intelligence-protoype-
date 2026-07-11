"""Redis client wrapper for distributed locking, idempotency, and rate limiting.

Beginner Note: This module provides a centralized Redis client that all
transactional features share. We use a single connection pool so the checkout
route, the FEFO lock system, and the velocity limiter all talk to Redis
without opening multiple connections.
"""

import logging
import os
from typing import Optional

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global connection pool — created once, reused across all requests.
# We read the REDIS_URL from the environment so it works both in Docker
# (redis://redis:6379/0) and during local development (redis://localhost:6379/0).
# ---------------------------------------------------------------------------
REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

_redis_pool: Optional[aioredis.Redis] = None


async def get_redis_client() -> aioredis.Redis:
    """
    Returns the shared Redis client, creating the connection pool on first call.

    Beginner Note: Instead of opening a new connection for every request (which
    is slow), we create ONE connection pool when the app starts and reuse it.
    """
    global _redis_pool
    if _redis_pool is None:
        logger.info("Creating Redis connection pool...")
        _redis_pool = aioredis.from_url(
            REDIS_URL,
            encoding="utf-8",
            decode_responses=True,  # Automatically decode bytes back to Python strings
        )
    return _redis_pool


async def close_redis_client() -> None:
    """
    Closes the Redis connection pool during application shutdown.
    """
    global _redis_pool
    if _redis_pool is not None:
        await _redis_pool.close()
        _redis_pool = None
        logger.info("Redis connection pool closed.")


# ---------------------------------------------------------------------------
# Idempotency Guard
# ---------------------------------------------------------------------------
async def is_duplicate_checkout_request(idempotency_key: str) -> bool:
    """
    Checks whether a checkout with this idempotency key has already been processed.

    Beginner Note: We use Redis SET NX (Set-if-Not-eXists) with a 24-hour TTL.
    If SET NX returns False, the key already exists → this is a duplicate request.
    If SET NX returns True, we just created the key → this is a new request.

    The 24-hour TTL means the idempotency window is 1 day — long enough to
    prevent double-charges from network retries, short enough to avoid
    filling Redis with stale keys forever.
    """
    redis_client = await get_redis_client()
    key_already_existed: bool = await redis_client.set(
        name=f"idempotency:{idempotency_key}",
        value="COMPLETED",
        nx=True,        # Only set if the key does NOT already exist
        ex=86400,       # Expire after 24 hours (in seconds)
    )
    # redis.set() with NX returns True if the key was SET, False if it already existed.
    # We invert the logic: if the key already existed → it's a duplicate.
    return not key_already_existed


async def mark_checkout_completed(idempotency_key: str) -> None:
    """
    Marks an idempotency key as completed *after* the checkout transaction
    commits successfully. This is a safety net — the initial check in
    is_duplicate_checkout_request already prevents most duplicates, but
    if the checkout succeeded and the server crashed before returning the
    response, the retry will hit this key and return a 409 Conflict.

    Beginner Note: Think of this as a "I already did this" sticky note
    that stays on the fridge for 24 hours.
    """
    redis_client = await get_redis_client()
    await redis_client.set(
        name=f"idempotency:{idempotency_key}",
        value="COMPLETED",
        ex=86400,
    )


# ---------------------------------------------------------------------------
# Velocity / Rate Limit Guard
# ---------------------------------------------------------------------------
async def is_above_checkout_rate_limit(tenant_id: str) -> bool:
    """
    Ensures a tenant cannot submit more than 2 checkout requests per second.

    Beginner Note: We use a Redis sorted-set sliding window. Every checkout
    adds a timestamped entry. Then we count how many entries exist within
    the last 1 second. If the count exceeds 2, we reject the request.

    The key expires 2 seconds after the last request so we don't accumulate
    stale data in Redis.
    """
    redis_client = await get_redis_client()
    rate_limit_key: str = f"ratelimit:checkout:{tenant_id}"

    # Add this request's timestamp to the sorted set
    current_timestamp_millis: int = int(__import__("time").time() * 1000)
    await redis_client.zadd(rate_limit_key, {str(current_timestamp_millis): current_timestamp_millis})

    # Remove entries older than 1 second
    one_second_ago_millis: int = current_timestamp_millis - 1000
    await redis_client.zremrangebyscore(rate_limit_key, 0, one_second_ago_millis)

    # Count how many entries remain in the 1-second window
    request_count_in_window: int = await redis_client.zcard(rate_limit_key)

    # Set TTL so the key auto-cleans up if no more requests come
    await redis_client.expire(rate_limit_key, 2)

    # If we already have 2+ requests in the sliding window, reject this one
    return request_count_in_window > 2


# ---------------------------------------------------------------------------
# Distributed FEFO Inventory Lock
# ---------------------------------------------------------------------------
async def try_acquire_inventory_lock(
    batch_id: str,
    quantity: int,
    ttl_seconds: int = 60,
) -> bool:
    """
    Attempts to lock a specific batch so no other checkout can reserve it.

    Beginner Note: When the pharmacist scans a batch (via the FEFO routing
    endpoint), we want to "reserve" that batch for 60 seconds. This prevents
    two checkout requests from grabbing the same physical box at the same time.

    We use SET NX (Set-if-Not-eXists) — if another checkout already has the
    lock, this returns False and the frontend must refresh the cart.
    """
    redis_client = await get_redis_client()
    lock_key: str = f"inventory_lock:{batch_id}"

    lock_acquired: bool = await redis_client.set(
        name=lock_key,
        value=str(quantity),
        nx=True,
        ex=ttl_seconds,
    )
    return lock_acquired


async def verify_inventory_lock_exists(batch_id: str, expected_quantity: int) -> bool:
    """
    Checks whether a valid inventory lock exists for this batch.

    Beginner Note: During checkout, we verify that the FEFO lock created
    during search is still valid. If the lock expired (60-second TTL), the
    batch might have been sold to someone else, and we must reject the checkout.
    """
    redis_client = await get_redis_client()
    lock_key: str = f"inventory_lock:{batch_id}"

    stored_quantity_str: Optional[str] = await redis_client.get(lock_key)
    if stored_quantity_str is None:
        # Lock never existed or expired
        return False

    stored_quantity: int = int(stored_quantity_str)
    return stored_quantity >= expected_quantity


async def release_inventory_lock(batch_id: str) -> None:
    """
    Releases the FEFO lock after checkout completes (success or failure).

    Beginner Note: We remove the Redis key so the next pharmacist can
    purchase this batch.
    """
    redis_client = await get_redis_client()
    await redis_client.delete(f"inventory_lock:{batch_id}")
