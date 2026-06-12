"""Temporal Velocity Rate Limiter Service.

This module implements the event velocity checking mechanism using Redis.
It prevents entity-level abuse by limiting the number of events of a specific
type that a single entity can submit within a rolling time window.

Domain-Driven Design context:
- Fraud often involves rapid-fire submissions from a single entity.
- Rate limiting at the entity+event_type level catches abuse patterns
  without blocking legitimate traffic from different entities.
- Redis TTL ensures memory is automatically reclaimed for inactive entities.
"""

import logging

import redis.asyncio as aioredis

from app.core.config import get_application_settings

logger = logging.getLogger(__name__)


class VelocityRateLimiter:
    """Redis-backed rate limiter for audit event submissions.

    Tracks event frequency per entity per event type and rejects submissions
    that exceed the configured limit within a sliding time window.
    """

    def __init__(self) -> None:
        """Initialize the rate limiter with a Redis connection.

        Loads the Redis URL from the application settings configuration.
        """
        application_settings = get_application_settings()
        self.redis_client = aioredis.from_url(application_settings.redis_url)
        logger.info("VelocityRateLimiter initialized with Redis connection.")

    async def check_velocity(
        self,
        entity_id: str,
        event_type: str,
        limit: int = 5,
        window_seconds: int = 60,
    ) -> bool:
        """Check if an entity has exceeded the event rate limit.

        Uses a Redis key in the format 'velocity:{entity_id}:{event_type}'.
        Increments the counter on each call. If this is the first event,
        sets the key's TTL to the configured window. If the counter exceeds
        the limit, the function raises HTTP 429 to block the submission.

        Args:
            entity_id: The supplier or user ID to check.
            event_type: The category of event being submitted.
            limit: Maximum allowed events in the time window (default: 5).
            window_seconds: Length of the time window in seconds (default: 60).

        Returns:
            True if the submission is within the rate limit.

        Raises:
            HTTPException 429: If the entity has exceeded the rate limit.
        """
        # Step 1: Build the Redis key for this entity+event_type combination
        redis_key = f"velocity:{entity_id}:{event_type}"

        # Step 2: Increment the counter for this key
        # INCR returns the new value after incrementing
        current_count = await self.redis_client.incr(redis_key)

        # Step 3: If this is the first event, set the key to expire
        # This prevents memory leaks by auto-cleanup after the window passes
        if current_count == 1:
            await self.redis_client.expire(redis_key, window_seconds)

        # Step 4: Check if the count exceeds the configured limit
        if current_count > limit:
            from fastapi import HTTPException, status

            error_message = (
                f"Rate limit exceeded for entity '{entity_id}' on "
                f"event type '{event_type}'. "
                f"Limit: {limit} events per {window_seconds} seconds."
            )
            logger.warning(
                f"Velocity limit hit: {entity_id} / {event_type} "
                f"({current_count} events in {window_seconds}s)"
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=error_message,
            )

        # Step 5: Submission is within the rate limit
        return True
