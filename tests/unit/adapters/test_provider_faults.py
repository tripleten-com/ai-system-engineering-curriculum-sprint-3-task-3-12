"""Coldline.

===================

File:              tests/unit/adapters/test_provider_faults.py
Component:         Unit tests — Provider emulator fault controls
Purpose:           Unit tests for the fault flag, the outage, and the provider that honours them.
Interacts With:    One isolated source responsibility
Sprint/Task:       Sprint 3 — Project 3
Concepts:          Fast feedback, failure paths, fault injection
Tools:             Python 3.12, pytest
"""

from pathlib import Path

import pytest

from adapters.model import DeterministicModelProvider, ProviderFaultControls
from adapters.model import faults as fault_module
from domain.contracts import ModelRequest
from domain.errors import RetryableProviderError

REQUEST = ModelRequest(
    exception_id="exc-fault-001",
    shipment_id="shipment-syn-001",
    temperature_c=9.2,
    allowed_min_c=2.0,
    allowed_max_c=8.0,
)


def test_controls_apply_read_and_lift_one_fault(tmp_path: Path) -> None:
    """The flag file carries exactly the applied fault and nothing once lifted."""
    controls = ProviderFaultControls(tmp_path / "fault")

    assert controls.current() is None
    controls.apply("provider_outage")
    assert controls.current() == "provider_outage"
    controls.lift()
    assert controls.current() is None
    controls.lift()  # lifting twice is not an error


def test_controls_reject_an_unknown_fault(tmp_path: Path) -> None:
    """Only the supplied fault can be applied; a typo never silently arms nothing."""
    controls = ProviderFaultControls(tmp_path / "fault")

    with pytest.raises(ValueError, match="unknown provider fault"):
        controls.apply("queue_unavailable")
    assert controls.current() is None


def test_an_unrecognised_flag_is_treated_as_no_fault(tmp_path: Path) -> None:
    """A flag file with unexpected content leaves the emulator behaving normally."""
    path = tmp_path / "fault"
    path.write_text("something-else\n", encoding="utf-8")

    assert ProviderFaultControls(path).current() is None


@pytest.mark.asyncio
async def test_provider_fails_retryably_while_the_fault_is_applied(tmp_path: Path) -> None:
    """With the outage applied every call fails as retryable; lifted, the summary returns."""
    controls = ProviderFaultControls(tmp_path / "fault")
    provider = DeterministicModelProvider(latency_ms=0, faults=controls)
    controls.apply("provider_outage")

    with pytest.raises(RetryableProviderError, match="provider_outage"):
        await provider.summarize(REQUEST)

    controls.lift()
    response = await provider.summarize(REQUEST)
    assert response.provider == "deterministic-local"


@pytest.mark.asyncio
async def test_provider_without_controls_ignores_any_flag(tmp_path: Path) -> None:
    """A provider composed without fault controls never reads a flag file."""
    path = tmp_path / "fault"
    ProviderFaultControls(path).apply("provider_outage")

    response = await DeterministicModelProvider(latency_ms=0).summarize(REQUEST)

    assert "operational review is required" in response.summary


def test_command_line_applies_reports_and_lifts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The container command reports the state a run reads back."""
    path = str(tmp_path / "fault")

    assert fault_module.main(["--path", path, "status"]) == 0
    assert capsys.readouterr().out.strip() == "none"
    assert fault_module.main(["--path", path, "apply", "provider_outage"]) == 0
    assert capsys.readouterr().out.strip() == "applied provider_outage"
    assert fault_module.main(["--path", path, "status"]) == 0
    assert capsys.readouterr().out.strip() == "provider_outage"
    assert fault_module.main(["--path", path, "lift"]) == 0
    assert capsys.readouterr().out.strip() == "lifted"
    assert fault_module.main(["--path", path, "status"]) == 0
    assert capsys.readouterr().out.strip() == "none"
