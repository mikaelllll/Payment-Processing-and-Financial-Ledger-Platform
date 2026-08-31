import asyncio
import json
import logging
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import select

from .config import settings
from .database import SessionLocal
from .models import OutboxEvent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("ledgerflow.worker")


async def dispatch_batch(redis: Redis) -> int:
    async with SessionLocal() as session:
        events = (
            await session.scalars(
                select(OutboxEvent)
                .where(OutboxEvent.status == "pending")
                .order_by(OutboxEvent.created_at)
                .limit(50)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for event in events:
            event.attempts += 1
            await redis.xadd(
                "ledgerflow:events",
                {
                    "event_id": event.id,
                    "type": event.event_type,
                    "payload": json.dumps(event.payload),
                },
                maxlen=10_000,
            )
            event.status = "delivered"
            event.processed_at = datetime.now(UTC)
        await session.commit()
        return len(events)


async def run() -> None:
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    while True:
        try:
            delivered = await dispatch_batch(redis)
            if delivered:
                logger.info("Dispatched %s transactional outbox events", delivered)
        except Exception:
            logger.exception("Outbox dispatch failed; pending events remain safe for retry")
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(run())
