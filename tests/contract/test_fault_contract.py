"""Coldline.

===================

File:              tests/contract/test_fault_contract.py
Component:         Contract tests — Fault variation
Purpose:           Check the lab file, the second runbook entry, and the answers recorded from them.
Interacts With:    docs/student/faults/, the runbook, submission.yaml, the running stack
Sprint/Task:       Sprint 3 — Project 3
Concepts:          Generated evidence, correlation by id, runbook structure, baseline
Tools:             Python 3.12, pytest, Docker Compose

Every check here reads the lab file `poe fault-lab` wrote, the runbook, the answer sheet, or
the running stack. None of them reruns the lab and none grades the prose of the runbook
entry: the entry is what the on-call engineer follows, and these are what the generated
evidence, the structure, and the answers have to show on their own. The two checks marked
`runtime` need the stack; the rest are static. `poe contract` skips this whole module
because it is marked `assessed`; `poe fault-checks`, `poe fault-runbook-contract`, and
`poe verify` run it.
"""

from typing import Any

import pytest

from tests.contract import fault_contract as faults

pytestmark = [pytest.mark.assessed]


@pytest.fixture(scope="module")
def answers() -> dict[str, Any]:
    """Load the recorded answers once."""
    return faults.load_answers()


@pytest.fixture(scope="module")
def catalog() -> dict[str, dict[str, Any]]:
    """Load the supplied catalog once."""
    return faults.load_catalog()


@pytest.fixture(scope="module")
def fault_id(answers: dict[str, Any]) -> str:
    """Return the recorded fault id as a string; a blank sheet gives an empty one."""
    return faults.text(answers.get("fault_id")) or ""


@pytest.fixture(scope="module")
def lab(fault_id: str) -> dict[str, Any] | None:
    """Load the lab file for the recorded fault once, as written."""
    return faults.load_lab(fault_id) if fault_id else None


def test_fault_id_is_one_of_the_catalog_ids(
    fault_id: str, catalog: dict[str, dict[str, Any]]
) -> None:
    """answers.fault_id names one of the ids infra/faults/catalog.yaml lists, exactly."""
    assert fault_id in catalog, (
        f"answers.fault_id must be one of the catalog ids ({', '.join(catalog)}), "
        f"character for character; got {fault_id!r}"
    )


def test_why_different_names_a_difference_within_its_limit(answers: dict[str, Any]) -> None:
    """answers.why_different is present and at most 400 characters."""
    value = faults.text(answers.get("why_different"))
    assert value is not None, (
        "answers.why_different must say which component your fault takes away and which "
        "part of the existing entry you expect not to transfer"
    )
    limit = faults.TEXT_LIMITS["why_different"]
    assert len(value) <= limit, f"answers.why_different must be at most {limit} characters"


def test_lab_file_for_the_chosen_fault_is_unedited_and_returned_to_baseline(
    fault_id: str, lab: dict[str, Any] | None
) -> None:
    """The chosen fault's lab file exists, is as the lab wrote it, and reports baseline."""
    assert fault_id, "answers.fault_id names no catalog fault, so no lab file can be checked"
    problems = faults.lab_problems(lab, fault_id)
    others = [name for name in faults.committed_lab_files() if name != f"{fault_id}-lab.json"]
    if others:
        problems.append(
            "docs/student/faults holds a lab file for a fault you did not choose "
            f"({', '.join(others)}); run one catalog fault and commit its file only"
        )
    assert problems == [], "\n".join(problems)


def test_evidence_covers_the_four_kinds_and_cites_the_lab_files_trace_ids(
    answers: dict[str, Any], lab: dict[str, Any] | None
) -> None:
    """answers.evidence holds trace, metric, log, and queue entries, each cited by reference."""
    evidence = faults.mapping(answers, "evidence")
    problems: list[str] = []
    for kind in faults.EVIDENCE_KINDS:
        entries = evidence.get(kind)
        if not isinstance(entries, list) or not entries:
            problems.append(f"answers.evidence.{kind} must hold at least one entry")
            continue
        for position, entry in enumerate(entries):
            reference = faults.text(entry.get("reference")) if isinstance(entry, dict) else None
            observation = faults.text(entry.get("observation")) if isinstance(entry, dict) else None
            if reference is None or observation is None:
                problems.append(
                    f"answers.evidence.{kind}[{position}] needs a non-empty reference and "
                    "observation"
                )
    sampled = faults.lab_trace_ids(lab)
    raw_trace = evidence.get("trace")
    trace_entries = raw_trace if isinstance(raw_trace, list) else []
    for position, entry in enumerate(trace_entries):
        reference = faults.text(entry.get("reference")) if isinstance(entry, dict) else None
        if reference is not None and reference not in sampled:
            problems.append(
                f"answers.evidence.trace[{position}].reference {reference!r} is not one of the "
                "trace_ids in your lab file"
            )
    assert problems == [], "\n".join(problems)


def test_first_affected_component_and_detection_signal_use_allowed_values(
    answers: dict[str, Any],
) -> None:
    """The component and the signal are allowed values, and the signal note is bounded."""
    problems: list[str] = []
    if answers.get("first_affected_component") not in faults.COMPONENTS:
        problems.append(
            "answers.first_affected_component must be one of " + ", ".join(faults.COMPONENTS)
        )
    if answers.get("detection_signal") not in faults.SIGNALS:
        problems.append("answers.detection_signal must be one of " + ", ".join(faults.SIGNALS))
    note = faults.text(answers.get("detection_signal_note"))
    limit = faults.TEXT_LIMITS["detection_signal_note"]
    if note is None or len(note) > limit:
        problems.append(
            f"answers.detection_signal_note must say where you saw the signal and how long "
            f"after the fault started, in at most {limit} characters"
        )
    assert problems == [], "\n".join(problems)


def test_recovery_outcome_is_allowed_and_the_counts_cover_the_lab_files_readings(
    answers: dict[str, Any], lab: dict[str, Any] | None
) -> None:
    """answers.recovery holds an allowed outcome and counts that add up to the lab's readings."""
    recovery = faults.mapping(answers, "recovery")
    problems: list[str] = []
    outcome = recovery.get("outcome")
    if outcome not in faults.OUTCOMES:
        problems.append("answers.recovery.outcome must be one of " + ", ".join(faults.OUTCOMES))
    completed, failed = recovery.get("completed_count"), recovery.get("failed_count")
    if not faults._is_count(completed) or not faults._is_count(failed):
        problems.append(
            "answers.recovery.completed_count and failed_count must be whole numbers of zero "
            "or more"
        )
    else:
        expected = faults.lab_reading_count(lab)
        if expected is None:
            problems.append("the lab file lists no readings to compare the counts with")
        elif completed + failed != expected:
            problems.append(
                f"completed_count ({completed}) plus failed_count ({failed}) must equal the "
                f"{expected} readings in your lab file"
            )
        if outcome == "recovered" and failed != 0:
            problems.append("outcome `recovered` is not consistent with a non-zero failed_count")
    if not isinstance(recovery.get("failure_reasons"), list):
        problems.append("answers.recovery.failure_reasons must be a list (empty if none)")
    if not faults._is_count(recovery.get("redriven_count")):
        problems.append("answers.recovery.redriven_count must be a whole number of zero or more")
    if recovery.get("alert_state") not in faults.ALERT_STATES:
        problems.append(
            "answers.recovery.alert_state must be one of " + ", ".join(faults.ALERT_STATES)
        )
    assert problems == [], "\n".join(problems)


@pytest.mark.runtime
def test_recorded_baseline_matches_a_passing_baseline_check(answers: dict[str, Any]) -> None:
    """`poe baseline-check` exits 0, and answers.recovery.baseline records what it printed."""
    returncode, fields, output = faults.run_baseline_check()
    assert returncode == 0 and fields is not None, (
        f"`poe baseline-check` did not pass against the running stack:\n{output}"
    )
    recorded = faults.mapping(faults.mapping(answers, "recovery"), "baseline")
    mismatches = [
        f"answers.recovery.baseline.{field} records {recorded.get(field)!r}; "
        f"`poe baseline-check` printed {fields.get(field)!r}"
        for field in faults.BASELINE_FIELDS
        if recorded.get(field) != fields.get(field)
    ]
    assert mismatches == [], "\n".join(mismatches)


def test_first_runbook_entry_is_unchanged() -> None:
    """The runbook still opens with the supplied entry, byte for byte (line endings aside)."""
    assert faults.first_entry_unchanged(faults.runbook_text(), faults.supplied_runbook_text()), (
        "docs/student/runbook.md no longer opens with the supplied first entry as written; "
        "restore it from tests/fixtures/runbook-first-entry.md and add your entry below it"
    )


def test_second_runbook_entry_names_the_fault_with_its_four_sections(fault_id: str) -> None:
    """A second top-level entry names answers.fault_id and carries the four sections, in order."""
    assert fault_id, "answers.fault_id names no catalog fault, so no entry can be matched to it"
    problems = faults.second_entry_problems(faults.runbook_text(), fault_id)
    assert problems == [], "\n".join(problems)


def test_notes_answers_elena_within_its_limit(answers: dict[str, Any]) -> None:
    """answers.notes is present and at most 600 characters."""
    value = faults.text(answers.get("notes"))
    assert value is not None, (
        "answers.notes must say whether the first entry's method held, which section changed "
        "most, and what you would tell Elena"
    )
    limit = faults.TEXT_LIMITS["notes"]
    assert len(value) <= limit, f"answers.notes must be at most {limit} characters"


@pytest.mark.runtime
def test_supplied_fault_controls_report_no_active_fault_in_the_worker() -> None:
    """Both fault controls answer inside the worker container and report no fault applied."""
    problems: list[str] = []
    for module in faults.FAULT_CONTROL_MODULES:
        try:
            status = faults.fault_status(module)
        except faults.FaultCheckError as exc:
            problems.append(str(exc))
            continue
        if status != "none":
            problems.append(
                f"{module} still has fault {status!r} applied in the worker; an interrupted "
                "`poe fault-lab` left it behind, and the next run lifts it"
            )
    assert problems == [], "\n".join(problems)
