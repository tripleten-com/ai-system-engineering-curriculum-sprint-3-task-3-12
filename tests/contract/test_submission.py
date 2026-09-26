"""Coldline.

===================

File:              tests/contract/test_submission.py
Component:         Contract tests — Test Submission
Purpose:           Tests for the public answer and path checks for this Task's submission.
Interacts With:    Published interfaces and repository boundaries
Sprint/Task:       Sprint 3 — Project 3
Concepts:          Compatibility, ownership, export safety
Tools:             Python 3.12, pytest
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.contract.submission_validation import (
    SubmissionError,
    _load_one_document,
    main,
    validate_changed_paths,
    validate_submission,
)

ROOT = Path(__file__).parents[2]
SCHEMA = ROOT / "docs/contracts/submission.schema.json"
RUNBOOK = "docs/student/runbook.md"
LAB_FILE = "docs/student/faults/provider_outage-lab.json"
TRACE = "a" * 32


def _entry(reference: str, observation: str = "What it showed.") -> dict[str, str]:
    """Return one well-formed evidence entry."""
    return {"reference": reference, "observation": observation}


def _recovery(**overrides: Any) -> dict[str, Any]:
    """Return one well-formed recovery block."""
    block: dict[str, Any] = {
        "outcome": "recovered",
        "completed_count": 5,
        "failed_count": 0,
        "failure_reasons": [],
        "redriven_count": 0,
        "alert_state": "resolved",
        "baseline": {
            "all_readings_terminal": True,
            "queue_depth": 0,
            "dead_letter_depth": 0,
            "readiness_status": 200,
        },
    }
    block.update(overrides)
    return block


def valid_answers(**overrides: Any) -> dict[str, object]:
    """Return a complete answer sheet in the published shape."""
    answers: dict[str, Any] = {
        "fault_id": "provider_outage",
        "why_different": "The provider, not the worker, goes away; the queue query stays flat.",
        "evidence": {
            "trace": [_entry(TRACE, "Two summarize spans in error, then one that completed.")],
            "metric": [_entry("coldline_exception_jobs_total", "Flat for the whole window.")],
            "log": [_entry("2026-09-25T09:14:02+00:00 processed exception_id=exc-1 RETRY")],
            "queue": [_entry("09:14:03 queue_depth=0 in_flight=5 dead_letter_depth=0")],
        },
        "first_affected_component": "api",
        "detection_signal": "alert",
        "detection_signal_note": "Jaeger showed the first error span about 6 s after the fault.",
        "recovery": _recovery(),
        "notes": "The method held; Detection changed most. On-call can follow it.",
    }
    answers.update(overrides)
    return {"answers": answers}


def _task_root(tmp_path: Path, submission_text: str) -> Path:
    """Stage a minimal Task root the public verifier can validate."""
    (tmp_path / "docs/contracts").mkdir(parents=True)
    (tmp_path / "submission.yaml").write_text(submission_text, encoding="utf-8")
    (tmp_path / "submission-sample.yaml").write_text(
        (ROOT / "submission-sample.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "docs/contracts/submission.schema.json").write_text(
        SCHEMA.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return tmp_path


def test_a_complete_sheet_is_well_formed(tmp_path: Path) -> None:
    """The public schema accepts a complete sheet without judging its correctness."""
    root = _task_root(tmp_path, yaml.safe_dump(valid_answers()))

    validate_submission(root / "submission.yaml", SCHEMA)


def test_blank_template_fails_with_field_address(tmp_path: Path) -> None:
    """An untouched answer sheet must identify the first incomplete field."""
    root = _task_root(
        tmp_path, (ROOT / "tests/fixtures/submission-template.yaml").read_text(encoding="utf-8")
    )

    with pytest.raises(SubmissionError, match="answers.fault_id"):
        validate_submission(root / "submission.yaml", SCHEMA)


@pytest.mark.parametrize(
    "overrides,message",
    [
        ({"fault_id": "worker_outage"}, "fault_id"),
        ({"why_different": "x" * 401}, "why_different"),
        ({"first_affected_component": "database"}, "first_affected_component"),
        ({"detection_signal": "dashboard"}, "detection_signal"),
        ({"detection_signal_note": "n" * 301}, "detection_signal_note"),
        ({"notes": "x" * 601}, "notes"),
    ],
    ids=[
        "unknown-fault",
        "long-why-different",
        "unknown-component",
        "unknown-signal",
        "long-signal-note",
        "long-notes",
    ],
)
def test_values_outside_the_published_contract_are_rejected(
    tmp_path: Path, overrides: dict[str, Any], message: str
) -> None:
    """The public schema must name the field it rejected, and reject the right ones."""
    root = _task_root(tmp_path, yaml.safe_dump(valid_answers(**overrides)))

    with pytest.raises(SubmissionError, match=message):
        validate_submission(root / "submission.yaml", SCHEMA)


@pytest.mark.parametrize(
    "kind,entries,message",
    [
        ("trace", [], "evidence.trace"),
        ("trace", [_entry("ABCDEF" * 5 + "AB")], "evidence.trace"),
        ("trace", [_entry("abc123")], "evidence.trace"),
        ("metric", [_entry("")], "evidence.metric"),
        ("log", [{"reference": "a line"}], "evidence.log"),
        ("queue", [_entry("a sample", "")], "evidence.queue"),
    ],
    ids=[
        "no-trace",
        "uppercase-trace",
        "short-trace",
        "blank-reference",
        "missing-observation",
        "blank-observation",
    ],
)
def test_evidence_outside_the_published_contract_is_rejected(
    tmp_path: Path, kind: str, entries: list[dict[str, str]], message: str
) -> None:
    """Every evidence kind needs entries with a reference and an observation; traces are ids."""
    evidence = dict(valid_answers()["answers"]["evidence"])  # type: ignore[index]
    evidence[kind] = entries
    root = _task_root(tmp_path, yaml.safe_dump(valid_answers(evidence=evidence)))

    with pytest.raises(SubmissionError, match=message):
        validate_submission(root / "submission.yaml", SCHEMA)


@pytest.mark.parametrize(
    "overrides,message",
    [
        ({"outcome": "fixed"}, "recovery.outcome"),
        ({"completed_count": -1}, "recovery.completed_count"),
        ({"failed_count": "none"}, "recovery.failed_count"),
        ({"failure_reasons": "processing_attempts_exhausted"}, "recovery.failure_reasons"),
        ({"redriven_count": 1.5}, "recovery.redriven_count"),
        ({"alert_state": "firing"}, "recovery.alert_state"),
        (
            {"baseline": {"all_readings_terminal": "yes", "queue_depth": 0}},
            "recovery.baseline",
        ),
    ],
    ids=[
        "unknown-outcome",
        "negative-count",
        "prose-count",
        "prose-reasons",
        "fractional-redrive",
        "unknown-alert-state",
        "partial-baseline",
    ],
)
def test_recovery_outside_the_published_contract_is_rejected(
    tmp_path: Path, overrides: dict[str, Any], message: str
) -> None:
    """A nested recovery field cannot hide behind the top-level checks."""
    root = _task_root(tmp_path, yaml.safe_dump(valid_answers(recovery=_recovery(**overrides))))

    with pytest.raises(SubmissionError, match=message):
        validate_submission(root / "submission.yaml", SCHEMA)


def test_a_missing_evidence_kind_is_rejected(tmp_path: Path) -> None:
    """All four kinds are required; three of them is not a correlation."""
    evidence = dict(valid_answers()["answers"]["evidence"])  # type: ignore[index]
    del evidence["queue"]
    root = _task_root(tmp_path, yaml.safe_dump(valid_answers(evidence=evidence)))

    with pytest.raises(SubmissionError, match="queue"):
        validate_submission(root / "submission.yaml", SCHEMA)


@pytest.mark.parametrize(
    "field",
    ["lab_passed", "instructor_approved", "defense_recording_url", "runbook_reviewed"],
)
def test_no_self_attestation_or_recording_field_is_accepted(tmp_path: Path, field: str) -> None:
    """Reject a self-approval, a pass boolean, or a recording URL."""
    answers = valid_answers()
    mapping = answers["answers"]
    assert isinstance(mapping, dict)
    mapping[field] = True
    root = _task_root(tmp_path, yaml.safe_dump(answers))

    with pytest.raises(SubmissionError, match="Additional properties"):
        validate_submission(root / "submission.yaml", SCHEMA)


def test_exact_sample_copy_is_rejected(tmp_path: Path) -> None:
    """The published sample must not be accepted as a student submission."""
    root = _task_root(tmp_path, (ROOT / "submission-sample.yaml").read_text(encoding="utf-8"))

    with pytest.raises(SubmissionError, match="fictional sample"):
        validate_submission(
            root / "submission.yaml",
            SCHEMA,
            sample_path=root / "submission-sample.yaml",
        )


def test_only_the_permitted_paths_may_change() -> None:
    """The answer sheet, the runbook, and the chosen fault's lab file; nothing else."""
    validate_changed_paths(["submission.yaml", RUNBOOK, LAB_FILE])
    validate_changed_paths(["docs/student/faults/queue_unavailable-lab.json"])

    for protected in (
        "infra/faults/catalog.yaml",
        "tests/failure/fault_lab.py",
        "tests/failure/baseline_check.py",
        "src/adapters/model/faults.py",
        "src/adapters/queue/faults.py",
        "src/worker/bootstrap.py",
        "compose.yaml",
        "infra/observability/alerts.yml",
        "docs/student/faults/notes.json",
        "tests/fixtures/runbook-first-entry.md",
        "tests/contract/test_fault_contract.py",
        "tests/student/test_my_fault.py",
        ".github/workflows/task.yml",
        "docs/fidelity/JobQueue.md",
        "pyproject.toml",
        "README.md",
    ):
        with pytest.raises(SubmissionError, match="protected path changed"):
            validate_changed_paths([protected])


def test_public_entrypoint_reports_an_incomplete_answer_sheet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Catch a verifier entrypoint that skips the real submission contract."""
    root = _task_root(
        tmp_path, (ROOT / "tests/fixtures/submission-template.yaml").read_text(encoding="utf-8")
    )

    assert main(root, changed_paths=[]) == 1
    assert "answers.fault_id is incomplete" in capsys.readouterr().err


def test_public_entrypoint_accepts_a_completed_sheet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """With every field filled and the paths inside the boundary, the check passes."""
    root = _task_root(tmp_path, yaml.safe_dump(valid_answers()))

    assert main(root, changed_paths=["submission.yaml", RUNBOOK, LAB_FILE]) == 0
    assert "Task 3.12 answer verification passed" in capsys.readouterr().out


@pytest.mark.parametrize(
    "unsafe_text",
    [
        "answers: {value: first, value: second}\n",
        "answers: &answer {value: fictional}\n",
        "answers: *missing\n",
        "answers: {<<: {value: fictional}}\n",
        "answers: {value: 2026-09-04}\n",
        "answers: {value: !custom fictional}\n",
        "answers: {1: fictional}\n",
    ],
    ids=["duplicate-key", "anchor", "alias", "merge-key", "date", "custom-tag", "non-string-key"],
)
def test_non_json_yaml_constructs_are_rejected(tmp_path: Path, unsafe_text: str) -> None:
    """Reject restricted syntax before schema validation can mask a parser defect."""
    submission = tmp_path / "submission.yaml"
    submission.write_text(unsafe_text, encoding="utf-8")

    with pytest.raises(SubmissionError, match="restricted YAML"):
        _load_one_document(submission)


def test_multiple_yaml_documents_are_rejected(tmp_path: Path) -> None:
    """A second document cannot supply or replace the answer mapping."""
    submission = tmp_path / "submission.yaml"
    submission.write_text("answers: {}\n---\nanswers: {}\n", encoding="utf-8")

    with pytest.raises(SubmissionError, match="exactly one YAML mapping"):
        _load_one_document(submission)
