"""Coldline.

===================

File:              tests/unit/adapters/test_queue_faults.py
Component:         Unit tests — Queue endpoint fault controls
Purpose:           Unit tests for the queue fault flag and the client wrapper that honours it.
Interacts With:    One isolated source responsibility
Sprint/Task:       Sprint 3 — Project 3
Concepts:          Fast feedback, failure paths, fault injection
Tools:             Python 3.12, pytest
"""

from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import EndpointConnectionError

from adapters.queue import FaultableSqsClient, QueueFaultControls
from adapters.queue import faults as fault_module


class _RecordingClient:
    """Stand in for a boto3 SQS client: record every call and answer a fixed depth."""

    exceptions = "the client's exception namespace"

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get_queue_attributes(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("get_queue_attributes", kwargs))
        return {"Attributes": {"ApproximateNumberOfMessages": "0"}}


def test_controls_apply_read_and_lift_one_fault(tmp_path: Path) -> None:
    """The flag file carries exactly the applied fault and nothing once lifted."""
    controls = QueueFaultControls(tmp_path / "fault")

    assert controls.current() is None
    controls.apply("queue_unavailable")
    assert controls.current() == "queue_unavailable"
    controls.lift()
    assert controls.current() is None
    controls.lift()  # lifting twice is not an error


def test_controls_reject_an_unknown_fault(tmp_path: Path) -> None:
    """Only the supplied fault can be applied; a typo never silently arms nothing."""
    controls = QueueFaultControls(tmp_path / "fault")

    with pytest.raises(ValueError, match="unknown queue fault"):
        controls.apply("provider_outage")
    assert controls.current() is None


def test_wrapped_client_fails_as_unreachable_only_while_the_fault_is_applied(
    tmp_path: Path,
) -> None:
    """Every operation raises botocore's endpoint error under the fault and delegates otherwise."""
    controls = QueueFaultControls(tmp_path / "fault")
    inner = _RecordingClient()
    client = FaultableSqsClient(inner, endpoint_url="http://localstack:4566", faults=controls)

    assert client.get_queue_attributes(QueueUrl="q")["Attributes"]["ApproximateNumberOfMessages"]
    controls.apply("queue_unavailable")
    with pytest.raises(EndpointConnectionError, match="http://localstack:4566"):
        client.get_queue_attributes(QueueUrl="q")
    controls.lift()
    client.get_queue_attributes(QueueUrl="q")

    assert [name for name, _ in inner.calls] == ["get_queue_attributes", "get_queue_attributes"]


def test_wrapped_client_passes_plain_attributes_through(tmp_path: Path) -> None:
    """A non-callable attribute such as `exceptions` is the wrapped client's own."""
    client = FaultableSqsClient(
        _RecordingClient(),
        endpoint_url="http://localstack:4566",
        faults=QueueFaultControls(tmp_path / "fault"),
    )

    assert client.exceptions == "the client's exception namespace"


def test_command_line_applies_reports_and_lifts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The container command reports the state a run reads back."""
    path = str(tmp_path / "fault")

    assert fault_module.main(["--path", path, "status"]) == 0
    assert capsys.readouterr().out.strip() == "none"
    assert fault_module.main(["--path", path, "apply", "queue_unavailable"]) == 0
    assert capsys.readouterr().out.strip() == "applied queue_unavailable"
    assert fault_module.main(["--path", path, "status"]) == 0
    assert capsys.readouterr().out.strip() == "queue_unavailable"
    assert fault_module.main(["--path", path, "lift"]) == 0
    assert capsys.readouterr().out.strip() == "lifted"
    assert fault_module.main(["--path", path, "status"]) == 0
    assert capsys.readouterr().out.strip() == "none"
