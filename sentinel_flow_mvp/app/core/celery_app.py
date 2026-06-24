"""Celery Application Configuration.

Initializes the distributed worker queue using Redis to handle long-running data ingestion tasks.
"""

import os
from datetime import timedelta

from celery import Celery

REDIS_URI = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_application = Celery(
    "sentinel_flow_worker",
    broker=REDIS_URI,
    backend=REDIS_URI,
)

celery_application.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    imports=["app.services.worker_tasks", "app.workers.audit_worker", "app.services.lora_training_worker", "app.workers.embedding_tasks"],
    beat_schedule={
        "run-drift-analysis-every-5-minutes": {
            "task": "run_drift_analysis",
            "schedule": timedelta(seconds=300),  # 5 minutes = 300 seconds
        },
    },
)

# --- TASK ROUTING CONFIGURATION ---
# We separate CPU-heavy AI tasks from fast database updates to prevent system lockups.
# The 'embeddings' queue will handle the ONNX-quantized PubMedBERT model.
celery_application.conf.task_routes = {
    'app.workers.embedding_tasks.*': {'queue': 'embeddings'},
    '*': {'queue': 'celery'}
}
