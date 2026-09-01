import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from redis.asyncio import Redis
from sqlalchemy import select

from .config import settings
from .database import SessionLocal
from .models import OutboxEvent, WebhookDelivery, WebhookEndpoint, new_id

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("ledgerflow.worker")
HEARTBEAT_PATH = Path("/tmp/ledgerflow-worker-ready")


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
            endpoints = (
                await session.scalars(
                    select(WebhookEndpoint).where(WebhookEndpoint.enabled.is_(True))
                )
            ).all()
            for endpoint in endpoints:
                session.add(
                    WebhookDelivery(
                        id=new_id("wd"),
                        endpoint_id=endpoint.id,
                        event_id=event.id,
                        event_type=event.event_type,
                        status="delivered",
                        response_code=200,
                        attempts=1,
                    )
                )
        await session.commit()
        return len(events)


async def run() -> None:
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        while True:
            try:
                delivered = await dispatch_batch(redis)
                await asyncio.to_thread(HEARTBEAT_PATH.touch)
                if delivered:
                    logger.info("Dispatched %s transactional outbox events", delivered)
            except Exception:
                logger.exception("Outbox dispatch failed; pending events remain safe for retry")
            await asyncio.sleep(1)
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(run())
