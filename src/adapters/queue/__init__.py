"""Coldline.

===================

File:              src/adapters/queue/__init__.py
Component:         Queue adapters — Package exports
Purpose:           Expose active JobQueue adapters and the worker's queue endpoint fault controls.
Interacts With:    Domain contracts, ports, and local providers
Sprint/Task:       Sprint 3 — Project 3
Concepts:          Boundary translation, deterministic infrastructure, dead-letter redrive
Tools:             Python 3.12, Redis, boto3, LocalStack
"""

from adapters.queue.faults import FaultableSqsClient, QueueFaultControls
from adapters.queue.redis_streams import RedisJobQueue, decode_job, encode_job
from adapters.queue.sqs import (
    SqsJobQueue,
    create_sqs_client,
    ensure_queue,
    ensure_queue_when_ready,
)

__all__ = [
    "FaultableSqsClient",
    "QueueFaultControls",
    "RedisJobQueue",
    "SqsJobQueue",
    "create_sqs_client",
    "decode_job",
    "encode_job",
    "ensure_queue",
    "ensure_queue_when_ready",
]
