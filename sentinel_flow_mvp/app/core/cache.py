"""
Global DB Version Cache — Hash-Based Invalidation System.

Beginner Note:
    This module provides a simple but powerful cache invalidation mechanism.

    How it works:
        1. We store a single integer in Redis called "global_db_version".
        2. Every RAG response is cached with a key like:
           "rag_cache:{query_hash}:{global_db_version}"
        3. When the database changes (e.g., a drug gets reclassified by
           the government scraper), we INCREMENT the version number.
        4. Boom — all cached responses become invalid because their
           cache key includes the old version number.

    Think of it like changing the locks on your house:
        - Old keys (old version) no longer open the door.
        - Only new keys (new version) can open the door.
        - You don't need to go find and delete every old key —
          they simply stop working because the lock changed.

    This is called "Hash-Based Cache Invalidation" because:
        - The cache key is a HASH of the user's query.
        - The version number acts as a GLOBAL counter.
        - When any data changes, the counter increments.
"""

import json
import logging
import os

logger = logging.getLogger(__name__)

# The Redis key name for the global version counter.
# We hardcode this string so both the setter and getter use the exact same key.
GLOBAL_DB_VERSION_KEY = "global_db_version"

# Default version when no version has been set yet.
# We start at '1' instead of '0' because Redis INCR starts at 1.
DEFAULT_VERSION = "1"

# TTL for cached RAG responses: 7 days in seconds.
# 7 days = 7 * 24 * 60 * 60 = 604800 seconds.
CACHE_TTL_SECONDS = 604800


async def get_global_db_version(redis_client) -> str:
    """
    Fetch the current global database version from Redis.

    If the key has never been set (e.g., first deployment), we default to '1'.

    Args:
        redis_client: An active Redis async client instance.

    Returns:
        A string representation of the current version number.
        Example: "1", "2", "3", etc.
    """
    # Attempt to fetch the version string from Redis.
    # If the key does NOT exist, Redis.get() returns None.
    version_bytes = await redis_client.get(GLOBAL_DB_VERSION_KEY)

    if version_bytes is None:
        # No version has been set yet. This is the first deployment.
        # We set it to '1' so that future INCR calls work correctly.
        logger.info(
            "Global DB version not found in Redis. "
            f"Initializing to {DEFAULT_VERSION}."
        )
        await redis_client.set(GLOBAL_DB_VERSION_KEY, DEFAULT_VERSION)
        return DEFAULT_VERSION

    # Redis stores everything as strings by default.
    # We return the raw string so it can be used directly in cache keys.
    return str(version_bytes)


async def increment_global_db_version(redis_client) -> str:
    """
    Atomically increment the global database version using Redis INCR.

    Beginner Note:
        Redis INCR is ATOMIC — it guarantees that even if two scrapers
        run at the exact same time, the version number will increment
        by exactly 2 (not 1). This prevents race conditions.

    When to call this:
        - After a successful regulatory change (government scraper).
        - After any direct database mutation that affects drug safety data.
        - NOT for simple inventory changes (those don't affect clinical data).

    Returns:
        The NEW version number as a string.
    """
    new_version = await redis_client.incr(GLOBAL_DB_VERSION_KEY)
    new_version_str = str(new_version)

    logger.info(
        f"Global DB version incremented to {new_version_str}. "
        "All cached RAG responses are now invalid."
    )

    return new_version_str


# ---------------------------------------------------------------------------
# SYNCHRONOUS VERSION (for scripts that do not use asyncio)
# ---------------------------------------------------------------------------
# Beginner Note: The mock_government_scraper.py runs as a standalone script,
# not inside FastAPI's async event loop. It cannot call async functions.
# We provide a synchronous wrapper that connects to Redis directly using
# the regular (non-async) redis library, increments the version, and
# disconnects. This ensures the scraper can flush the cache without
# needing to understand asyncio.


def increment_global_db_version_sync() -> str:
    """
    Synchronous version of increment_global_db_version().

    Connects to Redis, increments the global_db_version counter, and
    disconnects. Suitable for use in standalone scripts like the
    mock government scraper.

    Returns:
        The NEW version number as a string.
    """
    import redis as sync_redis

    # Read the Redis URL from the environment, matching the default in
    # redis_client.py so we connect to the same Redis instance.
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # Create a synchronous Redis connection.
    # We do NOT use a connection pool here because this function is
    # called once per scraper run, not thousands of times per second.
    sync_client = sync_redis.from_url(redis_url, decode_responses=True)

    try:
        # Atomically increment the version counter.
        # Redis INCR is thread-safe and process-safe.
        new_version = sync_client.incr(GLOBAL_DB_VERSION_KEY)
        new_version_str = str(new_version)

        logger.info(
            f"[SYNC] Global DB version incremented to {new_version_str}. "
            "All cached RAG responses are now invalid."
        )

        return new_version_str

    finally:
        # Always close the connection, even if an error occurred.
        sync_client.close()
