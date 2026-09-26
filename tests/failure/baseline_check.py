"""Coldline.

===================

File:              tests/failure/baseline_check.py
Component:         Failure tools — Baseline check
Purpose:           Prove the platform is back at baseline and print the four baseline fields.
Interacts With:    The API, LocalStack SQS, docs/student/faults/*-lab.json
Sprint/Task:       Sprint 3 — Project 3
Concepts:          Baseline, independent verification, evidence
Tools:             Python 3.12, boto3, httpx

``poe baseline-check`` is the independent proof of recovery: it does not read the lab
file's own ``baseline`` block, it measures the platform again. The readings it knows about
are the exception ids listed in every lab file under ``docs/student/faults/``; with no lab
file there are none, and the field holds vacuously. A listed reading this stack has never
stored (a fresh stack, as on a CI runner) is not counted; one it holds must be terminal.
It samples the four fields once a second
for a short settle window, prints the last sample as one JSON object on standard output, and
exits 0 only when that sample is baseline: every known reading terminal, both queues at
zero, and readiness 200.
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any

from tests.failure.fault_catalog import (
    LAB_DIR,
    PlatformProbe,
    at_baseline,
    baseline_sample,
)

SETTLE_SECONDS = 15.0
POLL_INTERVAL_SECONDS = 1.0


class BaselineCheckError(RuntimeError):
    """Report one reason the check could not measure the platform."""


def known_exception_ids() -> list[str]:
    """Return every exception id the committed lab files list, in file order."""
    if not LAB_DIR.is_dir():
        return []
    ids: list[str] = []
    for path in sorted(LAB_DIR.glob("*-lab.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise BaselineCheckError(f"{path.name} is not a readable lab file: {exc}") from exc
        readings = document.get("readings") if isinstance(document, dict) else None
        if not isinstance(readings, list):
            raise BaselineCheckError(f"{path.name} lists no readings")
        for reading in readings:
            exception_id = reading.get("exception_id") if isinstance(reading, dict) else None
            if isinstance(exception_id, str) and exception_id not in ids:
                ids.append(exception_id)
        print(f"reading {path.name}: {len(readings)} reading(s)", file=sys.stderr, flush=True)
    return ids


def main() -> int:
    """Measure the baseline fields, print them, and exit 0 only at baseline."""
    try:
        exception_ids = known_exception_ids()
        probe = PlatformProbe()
    except BaselineCheckError as exc:
        print(f"baseline check failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        # The queue endpoint or the API did not answer at all; say so without a trace.
        print(f"baseline check failed: the stack did not answer ({exc})", file=sys.stderr)
        return 1
    sample: dict[str, Any] = {}
    try:
        deadline = time.monotonic() + SETTLE_SECONDS
        while True:
            sample = baseline_sample(probe, exception_ids, skip_absent=True)
            if at_baseline(sample) or time.monotonic() >= deadline:
                break
            print(
                "not at baseline yet: "
                + ", ".join(f"{field}={sample[field]}" for field in sorted(sample)),
                file=sys.stderr,
                flush=True,
            )
            time.sleep(POLL_INTERVAL_SECONDS)
    finally:
        probe.close()
    print(json.dumps(sample, indent=2, sort_keys=True))
    if at_baseline(sample):
        print("baseline check passed: the platform is at baseline.", file=sys.stderr)
        return 0
    print("baseline check failed: the platform is not at baseline.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
