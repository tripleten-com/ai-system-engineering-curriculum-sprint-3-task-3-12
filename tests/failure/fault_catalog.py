"""Coldline.

===================

File:              tests/failure/fault_catalog.py
Component:         Failure tools — Fault catalog and baseline helpers
Purpose:           Read the fault catalog, name the lab output, and sample the platform's baseline.
Interacts With:    infra/faults/catalog.yaml, the API, LocalStack SQS, Alertmanager
Sprint/Task:       Sprint 3 — Project 3
Concepts:          Fault catalog, baseline, generated evidence, content digest
Tools:             Python 3.12, boto3, httpx, PyYAML

Shared by ``fault_lab.py`` (which writes the lab file) and ``baseline_check.py`` (which
proves baseline on its own). The four baseline fields are defined here once, so the lab's
``baseline`` block and the check's printed output are the same measurement: every reading
the tooling knows about is terminal, the main queue and the dead-letter queue are both at
zero, and the API answers readiness with 200.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml

from tests.failure.force_dlq_arrival import DEAD_LETTER_NAME, QUEUE_NAME
from tests.failure.queue_client import client, queue_url
from tests.runtime_config import host_port

TASK_ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = TASK_ROOT / "infra/faults/catalog.yaml"
LAB_DIR = TASK_ROOT / "docs/student/faults"
GENERATOR = "poe fault-lab"
LAB_SCHEMA = "coldline-fault-lab/1"
ALERT_NAME = "ColdlineDeadLetterQueueBacklog"
TERMINAL_STATES = frozenset({"COMPLETED", "FAILED"})
BASELINE_FIELDS = (
    "all_readings_terminal",
    "queue_depth",
    "dead_letter_depth",
    "readiness_status",
)
CATALOG_KEYS = frozenset({"id", "description", "duration_seconds"})
MAIN_QUEUE_ATTRIBUTES = ("ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible")


class CatalogError(ValueError):
    """Report one reason the fault catalog cannot be used."""


@dataclass(frozen=True)
class CatalogFault:
    """One catalog entry: the id the lab takes, what it breaks, and its bounded window."""

    id: str
    description: str
    duration_seconds: float


def load_catalog(path: Path = CATALOG_PATH) -> list[CatalogFault]:
    """Return every catalog entry, in file order, after checking the catalog's shape."""
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise CatalogError(f"{_display(path)} is unreadable: {exc}") from exc
    entries = document.get("faults") if isinstance(document, dict) else None
    if not isinstance(entries, list) or not entries:
        raise CatalogError(f"{_display(path)} must list its faults under `faults`")
    faults: list[CatalogFault] = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != CATALOG_KEYS:
            raise CatalogError(
                f"{_display(path)}: every fault has exactly the keys "
                f"{', '.join(sorted(CATALOG_KEYS))}"
            )
        fault_id, description, duration = (
            entry["id"],
            entry["description"],
            entry["duration_seconds"],
        )
        if not isinstance(fault_id, str) or not fault_id.strip():
            raise CatalogError(f"{_display(path)}: a fault id must be a non-empty string")
        if not isinstance(description, str) or not description.strip():
            raise CatalogError(f"{_display(path)}: {fault_id} needs a one-line description")
        if isinstance(duration, bool) or not isinstance(duration, int | float) or duration <= 0:
            raise CatalogError(f"{_display(path)}: {fault_id} needs a positive duration_seconds")
        if any(fault.id == fault_id for fault in faults):
            raise CatalogError(f"{_display(path)}: fault id {fault_id!r} appears twice")
        faults.append(CatalogFault(fault_id, description.strip(), float(duration)))
    return faults


def catalog_ids(path: Path = CATALOG_PATH) -> list[str]:
    """Return the catalog's fault ids, in file order."""
    return [fault.id for fault in load_catalog(path)]


def lab_path(fault_id: str) -> Path:
    """Return where the lab writes one fault's output."""
    return LAB_DIR / f"{fault_id}-lab.json"


def digest(document: dict[str, Any]) -> str:
    """Return the content digest of a lab file, over everything but the digest itself.

    ``tests/contract/fault_contract.py`` recomputes this from the file exactly the same
    way; the two must stay identical.
    """
    body = {key: value for key, value in document.items() if key != "digest"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def api_base_url() -> str:
    """Return the API's host-reachable base URL."""
    return f"http://localhost:{host_port('COLDLINE_API_HOST_PORT', 8000)}"


def alertmanager_base_url() -> str:
    """Return Alertmanager's host-reachable base URL."""
    return f"http://localhost:{host_port('COLDLINE_ALERTMANAGER_HOST_PORT', 9093)}"


def jaeger_base_url() -> str:
    """Return Jaeger's host-reachable base URL."""
    return f"http://localhost:{host_port('COLDLINE_JAEGER_HOST_PORT', 16686)}"


@dataclass(frozen=True)
class QueueDepths:
    """One sample of both queues, as SQS reports them from the host."""

    queue_depth: int
    in_flight: int
    dead_letter_depth: int


class PlatformProbe:
    """Host-side handles to the API, both queues, and Alertmanager.

    One instance per run: the lab and the baseline check both read the platform through
    it, so the baseline block the lab writes and the fields the check prints come from the
    same calls.
    """

    def __init__(self) -> None:
        """Open the API client and resolve both queue URLs from the host."""
        self._api = httpx.Client(base_url=api_base_url(), timeout=10.0)
        self._sqs = client()
        self._main_url = queue_url(self._sqs, name=QUEUE_NAME)
        self._dlq_url = queue_url(self._sqs, name=DEAD_LETTER_NAME)

    def close(self) -> None:
        """Release the API client."""
        self._api.close()

    def depths(self) -> QueueDepths:
        """Return the main queue's visible and in-flight counts and the dead-letter depth."""
        main = self._sqs.get_queue_attributes(
            QueueUrl=self._main_url, AttributeNames=list(MAIN_QUEUE_ATTRIBUTES)
        )["Attributes"]
        dead = self._sqs.get_queue_attributes(
            QueueUrl=self._dlq_url, AttributeNames=["ApproximateNumberOfMessages"]
        )["Attributes"]
        return QueueDepths(
            queue_depth=int(main["ApproximateNumberOfMessages"]),
            in_flight=int(main["ApproximateNumberOfMessagesNotVisible"]),
            dead_letter_depth=int(dead["ApproximateNumberOfMessages"]),
        )

    def submit_reading(self, reading: dict[str, Any]) -> str:
        """Submit one reading and return the exception id the API accepted it under."""
        accepted = self._api.post("/api/v1/readings", json=reading)
        accepted.raise_for_status()
        return str(accepted.json()["exception_id"])

    def reading_record(self, exception_id: str) -> dict[str, Any] | None:
        """Return one exception's durable record, or None when the API cannot answer."""
        try:
            response = self._api.get(f"/api/v1/exceptions/{exception_id}")
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError):
            return None
        return body if isinstance(body, dict) else None

    def reading_absent(self, exception_id: str) -> bool:
        """Return whether the API answers 404: this stack has never stored the reading."""
        try:
            return self._api.get(f"/api/v1/exceptions/{exception_id}").status_code == 404
        except httpx.HTTPError:
            return False

    def readiness_status(self) -> int | None:
        """Return the status code `/health/ready` answers, or None when it does not answer."""
        try:
            return self._api.get("/health/ready").status_code
        except httpx.HTTPError:
            return None

    def alert_state(self) -> str:
        """Return the supplied alert's Alertmanager state, `absent`, or `unavailable`."""
        try:
            response = httpx.get(f"{alertmanager_base_url()}/api/v2/alerts", timeout=5.0)
            response.raise_for_status()
            alerts = response.json()
        except (httpx.HTTPError, ValueError):
            return "unavailable"
        for alert in alerts if isinstance(alerts, list) else []:
            if isinstance(alert, dict) and alert.get("labels", {}).get("alertname") == ALERT_NAME:
                return str(alert.get("status", {}).get("state") or "unknown")
        return "absent"

    def redrive_dead_letters(self) -> int:
        """Move every dead-lettered message back to the main queue; return how many moved.

        The same receive/send/delete shape as ``redrive_and_verify.py``. A redriven message
        carries the same exception identity, so the worker treats a delivery for an
        already-terminal record as a safe replay.
        """
        moved = 0
        while True:
            response = self._sqs.receive_message(
                QueueUrl=self._dlq_url, MaxNumberOfMessages=10, WaitTimeSeconds=1
            )
            messages = response.get("Messages") or []
            if not messages:
                return moved
            for message in messages:
                self._sqs.send_message(QueueUrl=self._main_url, MessageBody=message["Body"])
                self._sqs.delete_message(
                    QueueUrl=self._dlq_url, ReceiptHandle=message["ReceiptHandle"]
                )
                moved += 1


def baseline_sample(
    probe: PlatformProbe, exception_ids: list[str], *, skip_absent: bool = False
) -> dict[str, Any]:
    """Measure the four baseline fields once, over the readings the caller knows about.

    With ``skip_absent``, a reading this stack has never stored (the API answers 404) is not
    counted: a fresh stack, such as a CI runner or a rebuilt machine, holds none of the
    readings a committed lab file lists, and they are not pending there. A reading the stack
    does hold must still be terminal, and a reading the API cannot answer for is not.
    """
    terminal = True
    for exception_id in exception_ids:
        record = probe.reading_record(exception_id)
        if record is None and skip_absent and probe.reading_absent(exception_id):
            continue
        if record is None or record.get("state") not in TERMINAL_STATES:
            terminal = False
    depths = probe.depths()
    return {
        "all_readings_terminal": terminal,
        "queue_depth": depths.queue_depth,
        "dead_letter_depth": depths.dead_letter_depth,
        "readiness_status": probe.readiness_status(),
    }


def at_baseline(sample: dict[str, Any]) -> bool:
    """Return whether one sample is the platform's steady state."""
    return (
        sample.get("all_readings_terminal") is True
        and sample.get("queue_depth") == 0
        and sample.get("dead_letter_depth") == 0
        and sample.get("readiness_status") == 200
    )


def _display(path: Path) -> str:
    """Name a path relative to the Task root when it lives there, else as given."""
    try:
        return path.relative_to(TASK_ROOT).as_posix()
    except ValueError:
        return path.as_posix()
