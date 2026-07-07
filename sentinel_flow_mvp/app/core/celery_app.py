"""Celery Application Configuration.

Initializes the distributed worker queue using Redis to handle long-running data ingestion tasks.
"""

import os
from datetime import timedelta

from celery import Celery
from celery.schedules import crontab

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
    imports=["app.services.worker_tasks", "app.workers.audit_worker", "app.services.lora_training_worker", "app.workers.embedding_tasks", "app.workers.adherence_tasks", "app.tasks.covariate_tasks"],
    beat_schedule={
        "run-drift-analysis-every-5-minutes": {
            "task": "run_drift_analysis",
            "schedule": timedelta(seconds=300),
        },
        "daily-adherence-sweep-8am": {
            "task": "app.workers.adherence_tasks.sweep_depletion_horizons",
            "schedule": crontab(hour=8, minute=0),
        },
        'fetch-covariates-every-6-hours': {
            'task': 'fetch_exogenous_covariates_task',
            'schedule': 21600.0, # 6 hours in seconds
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
