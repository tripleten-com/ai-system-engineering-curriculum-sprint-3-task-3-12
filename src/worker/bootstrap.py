"""Coldline.

===================

File:              src/worker/bootstrap.py
Component:         Worker — Bootstrap
Purpose:           Compose and run the SQS-backed Coldline worker, with both catalog fault controls.
Interacts With:    LocalStack SQS, domain, ports, adapters, infra/faults/catalog.yaml
Sprint/Task:       Sprint 3 — Project 3
Concepts:          Background processing, idempotency, bounded resilience, redrive, fault injection
Tools:             Python 3.12, PostgreSQL, boto3, OpenTelemetry, Prometheus
"""

import asyncio
import logging
import signal
from datetime import UTC, datetime

import asyncpg
from opentelemetry import trace
from prometheus_client import start_http_server

from adapters.logging import configure_json_logging
from adapters.model import (
    DeterministicModelProvider,
    ProviderFaultControls,
    ResilientModelProvider,
)
from adapters.persistence import PostgresExceptionRepository
from adapters.queue import (
    FaultableSqsClient,
    QueueFaultControls,
    SqsJobQueue,
    create_sqs_client,
)
from adapters.telemetry import configure_tracing
from worker.config import WorkerSettings
from worker.queue_monitor import poll_dead_letter_depth
from worker.runtime import run_loop
from worker.use_cases import WorkerApplication


async def run() -> None:
    """Compose the worker, run it, and release every owned resource.

    This is wiring only. Domain decisions stay in ``WorkerApplication`` and
    provider and transport behavior stay behind their ports. Signal handlers
    cancel both background tasks together, then the ``finally`` block closes
    PostgreSQL and the trace provider.

    Task 3.12 adds the two catalog fault controls here and nowhere else: the
    provider emulator consults its flag file on every call, and the queue client
    the loop and the dead-letter monitor share is wrapped so its calls fail as
    unreachable while the queue fault is applied. Both flags are set and cleared
    from outside the container with ``python -m adapters.model.faults`` and
    ``python -m adapters.queue.faults``; `poe fault-lab` runs them for you.
    """
    settings = WorkerSettings()  # type: ignore[call-arg]  # protected environment is the source
    configure_json_logging(settings.service_name)
    logging.getLogger(__name__).info("worker starting build_version=%s", settings.build_version)
    tracer_provider = configure_tracing(settings.service_name, settings.otel_endpoint)
    tracer = trace.get_tracer(__name__)
    pool = await asyncpg.create_pool(dsn=settings.database_url, min_size=1, max_size=4)
    raw_sqs_client = create_sqs_client(
        endpoint_url=settings.s3_endpoint,
        region_name=settings.s3_region,
        access_key_id=settings.s3_access_key_id,
        secret_access_key=settings.s3_secret_access_key,
    )
    # Startup resolves both queue URLs with the unwrapped client, so a fault flag left
    # behind by an interrupted lab never keeps the worker from starting.
    queue_url = await asyncio.to_thread(
        lambda: raw_sqs_client.get_queue_url(QueueName=settings.queue_name)["QueueUrl"]
    )
    # Task 3.4's own resolution, alongside the main queue's: the dead-letter
    # monitor polls this queue directly, never through JobQueue, since
    # SqsJobQueue is bound to the main queue only.
    dead_letter_queue_url = await asyncio.to_thread(
        lambda: raw_sqs_client.get_queue_url(QueueName=settings.dead_letter_name)["QueueUrl"]
    )
    sqs_client = FaultableSqsClient(
        raw_sqs_client, endpoint_url=settings.s3_endpoint, faults=QueueFaultControls()
    )
    queue = SqsJobQueue(sqs_client, queue_url=str(queue_url))
    start_http_server(settings.metrics_port)
    provider = ResilientModelProvider(
        DeterministicModelProvider(
            latency_ms=settings.model_latency_ms, faults=ProviderFaultControls()
        ),
        timeout_seconds=settings.model_timeout_ms / 1000,
        max_attempts=settings.model_provider_max_attempts,
        backoff_seconds=settings.model_retry_backoff_ms / 1000,
    )
    application = WorkerApplication(
        PostgresExceptionRepository(pool),
        provider,
        clock=lambda: datetime.now(UTC),
        maximum_attempts=settings.maximum_attempts,
    )
    worker_task = asyncio.create_task(
        run_loop(queue, application, tracer, stale_message_ms=settings.stale_message_ms)
    )
    monitor_task = asyncio.create_task(
        poll_dead_letter_depth(sqs_client, str(dead_letter_queue_url))
    )

    def cancel_both() -> None:
        worker_task.cancel()
        monitor_task.cancel()

    loop = asyncio.get_running_loop()
    for shutdown_signal in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(shutdown_signal, cancel_both)
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    finally:
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass
        await pool.close()
        tracer_provider.shutdown()


if __name__ == "__main__":
    asyncio.run(run())
