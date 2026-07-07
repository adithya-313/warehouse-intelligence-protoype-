import json
import logging
from aiokafka import AIOKafkaProducer
from app.domain.schemas import MedicationSoldEvent
from app.core.config import get_application_settings

logger = logging.getLogger(__name__)

# Global producer instance
_producer: AIOKafkaProducer = None

async def start_kafka_producer():
    """
    Initializes the Kafka producer. Called when FastAPI starts up.
    Beginner Note: We connect to Redpanda (running on port 9092).
    """
    global _producer
    try:
        settings = get_application_settings()
        _producer = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode('utf-8')
        )
        await _producer.start()
        logger.info("Kafka Producer started successfully.")
    except Exception as e:
        logger.error(f"Failed to start Kafka Producer: {e}")

async def stop_kafka_producer():
    """Cleanly shuts down the Kafka producer."""
    global _producer
    if _producer:
        await _producer.stop()
        logger.info("Kafka Producer stopped.")

async def publish_medication_sold(event: MedicationSoldEvent):
    """
    Publishes a POS event to the 'medication-sales' Kafka topic.
    Beginner Note: This is 'fire-and-forget'. The API responds instantly to the POS system,
    while background consumers process the database updates concurrently.
    """
    if not _producer:
        logger.warning("Kafka producer not initialized. Event dropped.")
        return
        
    # Convert the Pydantic model to a dictionary, handling datetime serialization
    event_dict = event.model_dump(mode='json')
    
    # Publish to the topic
    await _producer.send_and_wait("medication-sales", event_dict)
    logger.info(f"Published MedicationSoldEvent for batch {event.batch_id}")
