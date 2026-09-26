"""Coldline.

===================

File:              tests/contract/fault_contract.py
Component:         Contract tests — Fault variation helpers
Purpose:           Read the catalog, the lab file, the runbook, and the answer sheet for the checks.
Interacts With:    infra/faults/catalog.yaml, docs/student/faults/, the runbook, submission.yaml
Sprint/Task:       Sprint 3 — Project 3
Concepts:          Generated evidence, content digest, runbook structure, baseline
Tools:             Python 3.12, Docker Compose

The checks never import the lab. They read the file it wrote exactly as a student commits
it, recompute the content digest the same way the lab did, read the runbook and the answer
sheet beside it, and run `poe baseline-check` as a subprocess exactly as `poe` does, so what
they assert is what the files and the running stack show.
"""

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, TypeGuard, cast

import yaml

TASK_ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = TASK_ROOT / "infra/faults/catalog.yaml"
LAB_DIR = TASK_ROOT / "docs/student/faults"
RUNBOOK_PATH = TASK_ROOT / "docs/student/runbook.md"
# The supplied runbook, repeated byte for byte, so the first-entry check needs no git.
SUPPLIED_RUNBOOK_PATH = TASK_ROOT / "tests/fixtures/runbook-first-entry.md"
GENERATOR = "poe fault-lab"
LAB_SCHEMA = "coldline-fault-lab/1"
ALERT_NAME = "ColdlineDeadLetterQueueBacklog"
EVIDENCE_KINDS = ("trace", "metric", "log", "queue")
COMPONENTS = ("api", "worker", "model_provider", "queue", "dead_letter_queue")
SIGNALS = (
    "queue_depth",
    "dead_letter_depth",
    "alert",
    "worker_up",
    "trace_error",
    "log_error",
    "reading_state",
)
OUTCOMES = ("recovered", "recovered_with_failures", "not_recovered")
ALERT_STATES = ("active", "resolved", "absent")
# Exact, case-sensitive, whole-line headings, in this order, once per entry.
SECTION_HEADINGS = ("## Detection", "## Diagnosis", "## Recovery", "## Verification")
BASELINE_FIELDS = (
    "all_readings_terminal",
    "queue_depth",
    "dead_letter_depth",
    "readiness_status",
)
TERMINAL_STATES = frozenset({"COMPLETED", "FAILED"})
# The character limits the lesson states for the three free-text answers.
TEXT_LIMITS = {"why_different": 400, "detection_signal_note": 300, "notes": 600}
TRACE_ID = re.compile(r"^[0-9a-f]{32}$")
COMPOSE_PROFILES = ("--profile", "observability", "--profile", "localstack")
FAULT_HOST_SERVICE = "worker"
FAULT_CONTROL_MODULES = ("adapters.model.faults", "adapters.queue.faults")


class FaultCheckError(ValueError):
    """Report one actionable fault-evidence failure."""


def load_catalog() -> dict[str, dict[str, Any]]:
    """Return the catalog's faults keyed by id, as the supplied file lists them."""
    document = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))
    entries = document.get("faults") if isinstance(document, dict) else None
    if not isinstance(entries, list):
        raise FaultCheckError("infra/faults/catalog.yaml lists no faults")
    catalog: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if isinstance(entry, dict) and isinstance(entry.get("id"), str):
            catalog[str(entry["id"])] = entry
    return catalog


def load_answers() -> dict[str, Any]:
    """Load the recorded answers; a blank sheet still lets every check run and report."""
    document = yaml.safe_load((TASK_ROOT / "submission.yaml").read_text(encoding="utf-8"))
    recorded = document.get("answers") if isinstance(document, dict) else None
    return recorded if isinstance(recorded, dict) else {}


def mapping(container: dict[str, Any], key: str) -> dict[str, Any]:
    """Return one nested answers mapping, or an empty mapping when it is absent or not one."""
    value = container.get(key)
    return value if isinstance(value, dict) else {}


def text(value: object) -> str | None:
    """Return one answer as a non-blank string, or None when it is not one."""
    if isinstance(value, str) and value.strip():
        return value
    return None


def lab_path(fault_id: str) -> Path:
    """Return where `poe fault-lab` writes one fault's output."""
    return LAB_DIR / f"{fault_id}-lab.json"


def load_lab(fault_id: str) -> dict[str, Any] | None:
    """Return one fault's lab file as written, or None when it is missing or not JSON."""
    path = lab_path(fault_id)
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return cast(dict[str, Any], loaded) if isinstance(loaded, dict) else None


def committed_lab_files() -> list[str]:
    """Return the names of every lab file present under docs/student/faults."""
    if not LAB_DIR.is_dir():
        return []
    return sorted(path.name for path in LAB_DIR.glob("*-lab.json"))


def digest(document: dict[str, Any]) -> str:
    """Return the content digest of a lab file, over everything but the digest itself.

    Identical to ``tests/failure/fault_catalog.py``'s ``digest``; the two must stay the same,
    because a lab file whose digest no longer matches its content is one that was edited.
    """
    body = {key: value for key, value in document.items() if key != "digest"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _is_count(value: object) -> TypeGuard[int]:
    """Return whether one JSON value is a whole number of zero or more (a bool is not)."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def lab_problems(lab: dict[str, Any] | None, fault_id: str) -> list[str]:
    """Return every reason one lab file is not what `poe fault-lab` writes for that fault."""
    name = lab_path(fault_id).relative_to(TASK_ROOT).as_posix()
    if lab is None:
        return [
            f"{name} is missing or is not one JSON object; run `poe fault-lab --fault {fault_id}`"
        ]
    problems: list[str] = []
    if lab.get("generator") != GENERATOR:
        problems.append(f"{name} was not written by {GENERATOR}")
    if lab.get("schema") != LAB_SCHEMA:
        problems.append(f"{name} does not carry the lab file schema {LAB_SCHEMA}")
    if lab.get("fault") != fault_id:
        problems.append(f"{name} names fault {lab.get('fault')!r}, not {fault_id!r}")
    if lab.get("digest") != digest(lab):
        problems.append(f"{name} has been edited since {GENERATOR} wrote it (digest mismatch)")
    timeline = lab.get("timeline")
    if not isinstance(timeline, dict) or not all(
        isinstance(timeline.get(stamp), str) for stamp in ("fault_applied_at", "fault_lifted_at")
    ):
        problems.append(f"{name}: timeline must record when the fault was applied and lifted")
    readings = lab.get("readings")
    if not isinstance(readings, list) or not readings:
        problems.append(f"{name}: readings must list the readings the lab submitted")
    else:
        for reading in readings:
            exception_id = reading.get("exception_id") if isinstance(reading, dict) else None
            state = reading.get("state") if isinstance(reading, dict) else None
            if not isinstance(exception_id, str) or state not in TERMINAL_STATES:
                problems.append(
                    f"{name}: every reading must carry its exception id and a terminal state"
                )
                break
    samples = lab.get("queue_samples")
    inside = [
        entry
        for entry in (samples if isinstance(samples, list) else [])
        if isinstance(entry, dict) and entry.get("phase") == "window"
    ]
    if not inside or not all(
        _is_count(entry.get("queue_depth")) and _is_count(entry.get("dead_letter_depth"))
        for entry in inside
    ):
        problems.append(
            f"{name}: queue_samples must hold at least one depth sample inside the window"
        )
    trace_ids = lab.get("trace_ids")
    if (
        not isinstance(trace_ids, list)
        or not trace_ids
        or not all(isinstance(item, str) and TRACE_ID.match(item) for item in trace_ids)
    ):
        problems.append(f"{name}: trace_ids must list at least one 32-character Jaeger trace id")
    alert = lab.get("alert")
    if not isinstance(alert, dict) or not all(
        isinstance(alert.get(field), str) for field in ("during_window", "after_recovery")
    ):
        problems.append(f"{name}: alert must record the state seen inside the window and after")
    baseline = lab.get("baseline")
    if not isinstance(baseline, dict) or set(baseline) != set(BASELINE_FIELDS):
        problems.append(f"{name}: baseline must carry exactly {', '.join(BASELINE_FIELDS)}")
    if lab.get("returned_to_baseline") is not True:
        problems.append(f"{name} reports returned_to_baseline false; rerun once the stack is quiet")
    return problems


def lab_trace_ids(lab: dict[str, Any] | None) -> set[str]:
    """Return every trace id one lab file sampled."""
    trace_ids = lab.get("trace_ids") if lab is not None else None
    if not isinstance(trace_ids, list):
        return set()
    return {item for item in trace_ids if isinstance(item, str)}


def lab_reading_count(lab: dict[str, Any] | None) -> int | None:
    """Return how many readings one lab file lists, or None when it lists none."""
    readings = lab.get("readings") if lab is not None else None
    return len(readings) if isinstance(readings, list) and readings else None


def normalized(document: str) -> str:
    """Return one text with Windows line endings folded to LF; a checkout's eol is no change."""
    return document.replace("\r\n", "\n")


def supplied_runbook_text() -> str:
    """Return the supplied runbook text, the first entry the student must leave unchanged."""
    return normalized(SUPPLIED_RUNBOOK_PATH.read_text(encoding="utf-8"))


def runbook_text() -> str:
    """Return the student's runbook as it stands."""
    return normalized(RUNBOOK_PATH.read_text(encoding="utf-8"))


def first_entry_unchanged(runbook: str, supplied: str) -> bool:
    """Return whether the runbook still opens with the supplied text, byte for byte."""
    return runbook.startswith(supplied)


def top_level_entries(document: str) -> list[tuple[str, list[str]]]:
    """Split a runbook into its top-level entries: each `# ` heading with the lines under it.

    Lines inside fenced code blocks are never headings, so a shell comment quoted in a
    Recovery section does not start an entry. Text before the first heading is dropped.
    """
    entries: list[tuple[str, list[str]]] = []
    fenced = False
    for raw_line in document.splitlines():
        line = raw_line.rstrip()
        if line.startswith("```"):
            fenced = not fenced
        if not fenced and line.startswith("# "):
            entries.append((line, []))
        elif entries:
            entries[-1][1].append(line)
    return entries


def _next_section_index(lines: list[str], start: int) -> int:
    """Return the index of the next level-two heading after ``start``, or the end."""
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("## "):
            return index
    return len(lines)


def _section_problems(lines: list[str]) -> list[str]:
    """Return every reason one entry's lines lack the four sections, in order, with content."""
    positions: dict[str, list[int]] = {heading: [] for heading in SECTION_HEADINGS}
    fenced = False
    for index, line in enumerate(lines):
        if line.startswith("```"):
            fenced = not fenced
        if not fenced and line in positions:
            positions[line].append(index)
    problems: list[str] = []
    for heading in SECTION_HEADINGS:
        count = len(positions[heading])
        if count == 0:
            problems.append(f"the second entry lacks the heading {heading!r}")
        elif count > 1:
            problems.append(f"the second entry repeats the heading {heading!r}")
    if problems:
        return problems
    ordered = [positions[heading][0] for heading in SECTION_HEADINGS]
    if ordered != sorted(ordered):
        problems.append(
            "the second entry's sections are out of order; expected " + ", ".join(SECTION_HEADINGS)
        )
    for heading, start in zip(SECTION_HEADINGS, ordered, strict=True):
        end = _next_section_index(lines, start)
        body = [line for line in lines[start + 1 : end] if line.strip()]
        if not any(not line.startswith("#") for line in body):
            problems.append(f"the second entry's {heading!r} section has no content of its own")
    return problems


def second_entry_problems(document: str, fault_id: str) -> list[str]:
    """Return every reason the runbook lacks a complete second entry for one fault."""
    entries = top_level_entries(document)
    if len(entries) < 2:
        return [
            "docs/student/runbook.md holds no second top-level entry; add a `# ` heading after "
            "the existing entry naming the fault and its catalog id"
        ]
    heading, lines = entries[1]
    problems: list[str] = []
    if fault_id not in heading:
        problems.append(
            f"the second entry's heading {heading!r} does not name the catalog id {fault_id!r}"
        )
    problems.extend(_section_problems(lines))
    return problems


def run_baseline_check() -> tuple[int, dict[str, Any] | None, str]:
    """Run `poe baseline-check`'s module as `poe` does; return its exit, fields, and output."""
    result = subprocess.run(
        [sys.executable, "-m", "tests.failure.baseline_check"],
        cwd=TASK_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    fields: dict[str, Any] | None = None
    try:
        loaded = json.loads(result.stdout)
        if isinstance(loaded, dict):
            fields = cast(dict[str, Any], loaded)
    except ValueError:
        fields = None
    output = (result.stdout + result.stderr).strip()
    return result.returncode, fields, output


def fault_status(module: str) -> str:
    """Ask one fault control, inside the worker container, which fault is active."""
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
            "status",
        ],
        cwd=TASK_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise FaultCheckError(
            f"the fault control {module} did not answer in the {FAULT_HOST_SERVICE} container: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result.stdout.strip()
