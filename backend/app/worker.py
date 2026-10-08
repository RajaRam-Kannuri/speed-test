"""Celery worker: executions, website discovery and AI generation jobs run here,
never inside HTTP request handlers."""

from __future__ import annotations

import logging
import uuid

from celery import Celery

from .config import get_settings

settings = get_settings()
celery_app = Celery("lorvenlax", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_acks_late=True,  # redeliver if a worker dies mid-task; tasks claim rows atomically, so this is safe
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    task_time_limit=settings.max_run_seconds + 300,
    task_soft_time_limit=settings.max_run_seconds + 240,
    task_default_queue="lorvenlax",
    broker_connection_retry_on_startup=True,
)
log = logging.getLogger("lorvenlax.worker")


@celery_app.task(name="lorvenlax.run_execution")
def run_execution_task(execution_id: str) -> str:
    from .services.runner import run_execution

    return run_execution(uuid.UUID(execution_id))


@celery_app.task(name="lorvenlax.run_discovery")
def run_discovery_task(discovery_id: str) -> str:
    from .agents.discovery import run_discovery

    return run_discovery(uuid.UUID(discovery_id))


@celery_app.task(name="lorvenlax.run_generation")
def run_generation_task(job_id: str) -> str:
    from .services.generation import run_generation_job

    return run_generation_job(uuid.UUID(job_id))


def enqueue(task, *args: str) -> str | None:
    """Queue a task; in eager mode (tests) run it synchronously."""
    if get_settings().celery_eager:
        task.apply(args=args)
        return None
    return task.delay(*args).id
