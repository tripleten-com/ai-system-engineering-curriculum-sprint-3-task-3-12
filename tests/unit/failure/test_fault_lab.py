"""Coldline.

===================

File:              tests/unit/failure/test_fault_lab.py
Component:         Unit tests — Fault lab
Purpose:           Unit tests for the catalog reader, the lab's refusal, and the lab file digest.
Interacts With:    One isolated source responsibility
Sprint/Task:       Sprint 3 — Project 3
Concepts:          Fast feedback, failure paths, generated evidence
Tools:             Python 3.12, pytest
"""

from pathlib import Path

import pytest

from tests.contract import fault_contract
from tests.failure import fault_catalog, fault_lab


def test_supplied_catalog_loads_with_the_lab_controls_for_every_id() -> None:
    """The catalog's ids are exactly the faults the lab knows how to apply."""
    faults = fault_catalog.load_catalog()

    assert [fault.id for fault in faults] == list(fault_lab.FAULT_CONTROLS)
    assert all(fault.duration_seconds > 0 for fault in faults)


@pytest.mark.parametrize(
    "text,message",
    [
        ("faults: []\n", "faults"),
        ("faults:\n  - id: x\n    description: d\n", "exactly the keys"),
        (
            "faults:\n  - id: x\n    description: d\n    duration_seconds: 0\n",
            "positive duration_seconds",
        ),
        (
            "faults:\n"
            "  - {id: x, description: d, duration_seconds: 5}\n"
            "  - {id: x, description: e, duration_seconds: 5}\n",
            "appears twice",
        ),
    ],
    ids=["empty", "missing-key", "zero-duration", "duplicate-id"],
)
def test_a_malformed_catalog_is_refused(tmp_path: Path, text: str, message: str) -> None:
    """A catalog that does not have the published shape is an error, not a shorter list."""
    path = tmp_path / "catalog.yaml"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(fault_catalog.CatalogError, match=message):
        fault_catalog.load_catalog(path)


def test_the_lab_refuses_an_id_that_is_not_in_the_catalog(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An unknown id exits 2 naming the catalog ids, before touching the stack."""
    assert fault_lab.main(["--fault", "worker_outage"]) == 2

    err = capsys.readouterr().err
    assert "not in infra/faults/catalog.yaml" in err
    assert "provider_outage" in err and "queue_unavailable" in err


def test_the_lab_file_digest_is_what_the_contract_recomputes() -> None:
    """The lab and the check compute the same digest, and an edit changes it."""
    document = {"generator": "poe fault-lab", "fault": "provider_outage", "readings": []}
    document["digest"] = fault_catalog.digest(document)

    assert fault_contract.digest(document) == document["digest"]
    edited = {**document, "fault": "queue_unavailable"}
    assert fault_contract.digest(edited) != document["digest"]
