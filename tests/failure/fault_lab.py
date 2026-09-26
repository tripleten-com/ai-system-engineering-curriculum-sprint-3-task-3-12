"""Coldline.

===================

File:              tests/failure/fault_lab.py
Component:         Failure tools — Fault lab
Purpose:           Run one catalog fault for its window, recover, and write the lab evidence file.
Interacts With:    The catalog, the API, LocalStack SQS, Docker Compose, Jaeger, Alertmanager
Sprint/Task:       Sprint 3 — Project 3
Concepts:          Bounded fault, detection latency, correlation, idempotent recovery, evidence
Tools:             Python 3.12, boto3, httpx, Docker Compose

``poe fault-lab --fault <id>`` is the whole exercise for one catalog fault. In order, it

1. refuses an id that is not in ``infra/faults/catalog.yaml``, lifts any fault an interrupted
   run left applied, and refuses a stack whose ``/health/ready`` is not 200;
2. applies the chosen fault inside the worker container through the supplied controls
   (``adapters.model.faults`` for ``provider_outage``, ``adapters.queue.faults`` for
   ``queue_unavailable``) and prints when it did;
3. submits a fixed set of readings while the fault is active, one a second, printing each
   exception id, and samples both queue depths, every reading's state, and the alert every
   two seconds for the whole window;
4. lifts the fault when the catalog's ``duration_seconds`` have passed (in ``finally``: an
   interrupted run never leaves a fault applied), then polls until every reading is terminal
   and both queues are at zero, redriving anything that reaches the dead-letter queue the way
   ``redrive_and_verify.py`` does;
5. looks up one Jaeger trace per reading, reads the alert once more, measures the four
   baseline fields, and writes ``docs/student/faults/<id>-lab.json`` with a generator marker
   and a content digest that ``poe fault-runbook-contract`` recomputes.

The file records what the tooling saw. Your own notes from the window record what a person
would have seen; the runbook entry is written from both. Never edit the file: rerun instead,
and the new file replaces the old one. Exit 0 means the platform returned to baseline and at
least one trace was found.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from tests.failure.fault_catalog import (
    ALERT_NAME,
    CATALOG_PATH,
    GENERATOR,
    LAB_SCHEMA,
    TASK_ROOT,
    TERMINAL_STATES,
    CatalogError,
    CatalogFault,
    PlatformProbe,
    at_baseline,
    baseline_sample,
    digest,
    jaeger_base_url,
    lab_path,
    load_catalog,
)

COMPOSE_PROFILES = ("--profile", "observability", "--profile", "localstack")
# The container that hosts both fault controls: the worker loop, its provider emulator,
# and its queue client all run there.
FAULT_HOST_SERVICE = "worker"
# Catalog id to the control module that applies it inside the worker container. The
# catalog stays the only list of ids a student sees; this maps each to its mechanism.
FAULT_CONTROLS = {
    "provider_outage": "adapters.model.faults",
    "queue_unavailable": "adapters.queue.faults",
}
READING_COUNT = 5
SUBMIT_INTERVAL_SECONDS = 1.0
SAMPLE_INTERVAL_SECONDS = 2.0
TICK_SECONDS = 0.5
# Bounded recovery wait. A reading the provider fault turned back is redelivered after the
# queue's 30 s visibility timeout, and five readings drain in a few seconds once the worker
# can reach the queue again; the bound leaves room for one more redelivery on a slow host.
RECOVERY_TIMEOUT_SECONDS = 150.0
RECOVERY_POLL_SECONDS = 2.0
TRACE_SERVICE = "coldline-worker"
TRACE_WAIT_SECONDS = 30.0


class FaultLabError(RuntimeError):
    """Report one actionable failure of the lab without a stack trace."""


@dataclass
class LabReading:
    """One reading the lab submitted, and what its record showed."""

    exception_id: str
    reading_id: str
    submitted_at: float
    state_during_window: str | None = None
    state: str | None = None
    failure_reason: str | None = None
    terminal_at: float | None = None


def _stamp(moment: float) -> str:
    """Render one wall-clock instant as an ISO-8601 UTC timestamp with milliseconds."""
    return datetime.fromtimestamp(moment, UTC).isoformat(timespec="milliseconds")


def _log(message: str) -> None:
    """Print one progress line; the evidence goes to the file."""
    print(message, flush=True)


def fault_control(module: str, *arguments: str) -> str:
    """Run one fault control inside the worker container and return what it printed."""
    result = subprocess.run(
        [
            "docker",
            "compose",
            *COMPOSE_PROFILES,
            "exec",
            "-T",
            FAULT_HOST_SERVICE,
            "python",
            "-m",
            module,
            *arguments,
        ],
        cwd=TASK_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no detail"
        raise FaultLabError(
            f"the fault control {module} failed in the {FAULT_HOST_SERVICE} container "
            f"({' '.join(arguments)}): {detail}"
        )
    return result.stdout.strip()


def lift_every_fault() -> list[str]:
    """Lift both catalog faults, whatever is applied; return the ids that were active."""
    active: list[str] = []
    for fault_id, module in FAULT_CONTROLS.items():
        if fault_control(module, "status") != "none":
            active.append(fault_id)
        fault_control(module, "lift")
    return active


def build_reading() -> dict[str, Any]:
    """Build one lab reading with a fresh identity per call.

    A fresh identity on every call keeps this lab's own runs, the earlier exercise scripts,
    and the automated checks from ever colliding on ``ReadingApplication``'s idempotent
    replay of the same ``reading_id``; see ``trigger_alert_load.py`` for why.
    """
    token = uuid.uuid4().hex[:12]
    return {
        "reading_id": f"reading-fault-lab-{token}",
        "shipment_id": f"shipment-fault-lab-{token}",
        "temperature_c": 11.4,
        "allowed_min_c": 2.0,
        "allowed_max_c": 8.0,
        "recorded_at": "2026-01-01T00:00:00Z",
        "context": "Sprint 3 Task 3.12 fault lab",
    }


def _refresh_states(probe: PlatformProbe, readings: list[LabReading], *, in_window: bool) -> None:
    """Read every non-terminal reading's record once and keep what it showed."""
    for reading in readings:
        if reading.state in TERMINAL_STATES:
            continue
        record = probe.reading_record(reading.exception_id)
        state = record.get("state") if record is not None else None
        if not isinstance(state, str):
            continue
        if in_window:
            reading.state_during_window = state
        if state in TERMINAL_STATES:
            reading.state = state
            reason = record.get("failure_reason") if record is not None else None
            reading.failure_reason = reason if isinstance(reason, str) else None
            reading.terminal_at = time.time()


def _sample(probe: PlatformProbe, phase: str) -> dict[str, Any]:
    """Take one depth sample and print it."""
    depths = probe.depths()
    sample = {
        "at": _stamp(time.time()),
        "phase": phase,
        "queue_depth": depths.queue_depth,
        "in_flight": depths.in_flight,
        "dead_letter_depth": depths.dead_letter_depth,
    }
    _log(
        f"{phase}: queue_depth={depths.queue_depth} in_flight={depths.in_flight} "
        f"dead_letter_depth={depths.dead_letter_depth}"
    )
    return sample


def _drive_window(
    fault: CatalogFault, probe: PlatformProbe, readings: list[LabReading]
) -> tuple[float, float, list[dict[str, Any]], str]:
    """Apply the fault, submit the readings inside its window, sample, and lift it.

    Returns the moments the fault was applied and lifted, the samples taken inside the
    window, and the last alert state seen inside it. The lift runs in ``finally``.
    """
    module = FAULT_CONTROLS[fault.id]
    samples: list[dict[str, Any]] = []
    alert_state = "absent"
    fault_control(module, "apply", fault.id)
    applied_at = time.time()
    _log(f"fault {fault.id} applied at {_stamp(applied_at)} for {fault.duration_seconds:.0f} s")
    try:
        pending = [build_reading() for _ in range(READING_COUNT)]
        next_submit = applied_at
        next_sample = applied_at + 1.0
        while True:
            now = time.time()
            if now >= applied_at + fault.duration_seconds:
                break
            if pending and now >= next_submit:
                reading = pending.pop(0)
                exception_id = probe.submit_reading(reading)
                readings.append(LabReading(exception_id, str(reading["reading_id"]), now))
                _log(f"submitted reading {reading['reading_id']} as exception {exception_id}")
                next_submit = now + SUBMIT_INTERVAL_SECONDS
            if now >= next_sample:
                samples.append(_sample(probe, "window"))
                _refresh_states(probe, readings, in_window=True)
                alert_state = probe.alert_state()
                next_sample = now + SAMPLE_INTERVAL_SECONDS
            time.sleep(TICK_SECONDS)
    finally:
        fault_control(module, "lift")
        lifted_at = time.time()
        _log(f"fault {fault.id} lifted at {_stamp(lifted_at)}")
    return applied_at, lifted_at, samples, alert_state


def _wait_for_recovery(
    probe: PlatformProbe, readings: list[LabReading]
) -> tuple[list[dict[str, Any]], int, float | None]:
    """Poll until every reading is terminal and both queues are at zero, or time runs out."""
    samples: list[dict[str, Any]] = []
    redriven = 0
    deadline = time.monotonic() + RECOVERY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        _refresh_states(probe, readings, in_window=False)
        sample = _sample(probe, "recovery")
        samples.append(sample)
        if sample["dead_letter_depth"] > 0:
            moved = probe.redrive_dead_letters()
            redriven += moved
            _log(f"redrove {moved} dead-lettered message(s)")
        terminal = sum(1 for reading in readings if reading.state in TERMINAL_STATES)
        _log(f"recovering: terminal={terminal}/{len(readings)}")
        if (
            terminal == len(readings)
            and sample["queue_depth"] == 0
            and sample["dead_letter_depth"] == 0
        ):
            return samples, redriven, time.time()
        time.sleep(RECOVERY_POLL_SECONDS)
    return samples, redriven, None


def find_trace(client: httpx.Client, exception_id: str, deadline: float) -> str | None:
    """Return the most recent worker trace carrying one exception's tag, waiting for export."""
    tags = quote(json.dumps({"coldline.exception_id": exception_id}, separators=(",", ":")))
    endpoint = f"/api/traces?service={TRACE_SERVICE}&tags={tags}&limit=20&lookback=1h"
    while True:
        try:
            response = client.get(endpoint)
            response.raise_for_status()
            traces = response.json().get("data", [])
        except (httpx.HTTPError, ValueError, AttributeError):
            traces = []
        candidates: list[tuple[int, str]] = []
        for trace in traces:
            if not isinstance(trace, dict):
                continue
            trace_id = trace.get("traceID")
            spans = trace.get("spans")
            if not isinstance(trace_id, str) or not isinstance(spans, list):
                continue
            start_times = [
                span["startTime"]
                for span in spans
                if isinstance(span, dict) and isinstance(span.get("startTime"), int)
            ]
            candidates.append((max(start_times, default=0), trace_id.lower().zfill(32)))
        if candidates:
            return max(candidates)[1]
        if time.time() >= deadline:
            return None
        time.sleep(1.0)


def sample_traces(readings: list[LabReading]) -> list[dict[str, str]]:
    """Look up one Jaeger trace per reading, skipping a reading whose trace is not exported."""
    jaeger = jaeger_base_url()
    deadline = time.time() + TRACE_WAIT_SECONDS
    sampled: list[dict[str, str]] = []
    with httpx.Client(base_url=jaeger, timeout=5.0) as client:
        for reading in readings:
            trace_id = find_trace(client, reading.exception_id, deadline)
            if trace_id is None:
                _log(f"no worker trace exported yet for {reading.exception_id}")
                continue
            sampled.append(
                {
                    "trace_id": trace_id,
                    "exception_id": reading.exception_id,
                    "jaeger_url": f"{jaeger}/trace/{trace_id}",
                }
            )
    return sampled


def _reading_document(reading: LabReading) -> dict[str, Any]:
    """Render one reading for the lab file."""
    return {
        "exception_id": reading.exception_id,
        "reading_id": reading.reading_id,
        "submitted_at": _stamp(reading.submitted_at),
        "state_during_window": reading.state_during_window,
        "state": reading.state,
        "failure_reason": reading.failure_reason,
        "terminal_at": None if reading.terminal_at is None else _stamp(reading.terminal_at),
    }


def run(fault: CatalogFault) -> tuple[dict[str, Any], Path]:
    """Run the whole lab for one catalog fault and return the document and where it was written."""
    probe = PlatformProbe()
    try:
        active = lift_every_fault()
        if active:
            _log(f"lifted a leftover fault before the run: {', '.join(active)}")
        readiness = probe.readiness_status()
        if readiness != 200:
            raise FaultLabError(
                f"the API answered {readiness} on /health/ready; run `poe start` and "
                "`poe ready` before `poe fault-lab`"
            )
        readings: list[LabReading] = []
        applied_at, lifted_at, window_samples, alert_in_window = _drive_window(
            fault, probe, readings
        )
        recovery_samples, redriven, recovered_at = _wait_for_recovery(probe, readings)
        traces = sample_traces(readings)
        alert_after = probe.alert_state()
        baseline = baseline_sample(probe, [reading.exception_id for reading in readings])
    finally:
        probe.close()
    returned = recovered_at is not None and at_baseline(baseline)
    document: dict[str, Any] = {
        "generator": GENERATOR,
        "schema": LAB_SCHEMA,
        "fault": fault.id,
        "duration_seconds": fault.duration_seconds,
        "recorded_at": _stamp(time.time()),
        "timeline": {
            "fault_applied_at": _stamp(applied_at),
            "fault_lifted_at": _stamp(lifted_at),
            "window_seconds": round(lifted_at - applied_at, 1),
            "recovered_at": None if recovered_at is None else _stamp(recovered_at),
            "recovery_seconds": (
                None if recovered_at is None else round(recovered_at - lifted_at, 1)
            ),
        },
        "readings": [_reading_document(reading) for reading in readings],
        "queue_samples": window_samples + recovery_samples,
        "trace_ids": [entry["trace_id"] for entry in traces],
        "traces": traces,
        "alert": {
            "name": ALERT_NAME,
            "during_window": alert_in_window,
            "after_recovery": alert_after,
        },
        "redriven_count": redriven,
        "baseline": baseline,
        "returned_to_baseline": returned,
    }
    document["digest"] = digest(document)
    path = lab_path(fault.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return document, path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the one option the lab takes."""
    parser = argparse.ArgumentParser(description="Run one catalog fault against the stack.")
    parser.add_argument("--fault", required=True, help="a fault id from infra/faults/catalog.yaml")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the lab for the chosen fault and print what it wrote."""
    args = parse_args(argv)
    try:
        catalog = load_catalog(CATALOG_PATH)
    except CatalogError as exc:
        print(f"fault lab failed: {exc}", file=sys.stderr)
        return 1
    chosen = next((fault for fault in catalog if fault.id == args.fault), None)
    if chosen is None or chosen.id not in FAULT_CONTROLS:
        ids = ", ".join(fault.id for fault in catalog)
        print(
            f"fault lab refused: {args.fault!r} is not in infra/faults/catalog.yaml "
            f"(catalog ids: {ids})",
            file=sys.stderr,
        )
        return 2
    try:
        document, path = run(chosen)
    except (FaultLabError, httpx.HTTPError) as exc:
        print(f"fault lab failed: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("fault lab interrupted; the fault was lifted, rerun when ready", file=sys.stderr)
        return 130
    print(json.dumps(document, indent=2, sort_keys=True))
    _log(
        f"wrote {path.relative_to(TASK_ROOT).as_posix()}: "
        f"returned_to_baseline={document['returned_to_baseline']}, "
        f"{len(document['trace_ids'])} trace id(s)"
    )
    if not document["returned_to_baseline"]:
        _log("the platform did not return to baseline; run the lab again once the stack is quiet")
        return 1
    if not document["trace_ids"]:
        _log("Jaeger exported no worker trace for the readings; check Jaeger is up and rerun")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
