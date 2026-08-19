import json
import logging
from typing import Tuple, Optional, Callable, Awaitable
import aio_pika
from aio_pika.abc import AbstractExchange, AbstractIncomingMessage

from app.config import settings

logger = logging.getLogger("cogdrift.events")
EXCHANGE_NAME = "cogdrift.events"


async def get_rabbitmq_channel() -> Tuple[aio_pika.RobustConnection, aio_pika.RobustChannel, AbstractExchange]:
    connection = await aio_pika.connect_robust(settings.RABBITMQ_URL)
    channel = await connection.get_channel()
    exchange = await channel.declare_exchange(
        EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True
    )
    return connection, channel, exchange


async def publish_score_ingested(patient_id: str, played_at: str, session_id: Optional[str] = None):
    """Publishes score.ingested event to RabbitMQ fan-out/topic pipeline."""
    try:
        connection, channel, exchange = await get_rabbitmq_channel()
        routing_key = f"score.ingested.{patient_id}"
        message_body = {
            "event": "score.ingested",
            "patient_id": patient_id,
            "played_at": played_at,
            "session_id": session_id,
        }
        await exchange.publish(
            aio_pika.Message(
                body=json.dumps(message_body).encode("utf-8"),
                content_type="application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            ),
            routing_key=routing_key,
        )
        logger.info(f"Published score.ingested event for patient {patient_id}")
        await channel.close()
        await connection.close()
    except Exception as e:
        logger.warning(f"RabbitMQ publish skipped/failed (will be reconciled by nightly job): {e}")


async def consume_score_ingested_events(handler: Callable[[dict], Awaitable[None]]):
    """Consumes score.ingested events continuously in drift-worker."""
    connection = await aio_pika.connect_robust(settings.RABBITMQ_URL)
    channel = await connection.get_channel()
    exchange = await channel.declare_exchange(
        EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True
    )
    
    queue = await channel.declare_queue("cogdrift.drift_worker", durable=True)
    await queue.bind(exchange, routing_key="score.ingested.#")

    async with queue.iterator() as queue_iter:
        async for message in queue_iter:  # type: AbstractIncomingMessage
            async with message.process():
                data = json.loads(message.body.decode("utf-8"))
                await handler(data)
