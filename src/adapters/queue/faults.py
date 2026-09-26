"""Coldline.

===================

File:              src/adapters/queue/faults.py
Component:         Adapter — Queue endpoint fault controls
Purpose:           Make the worker's SQS endpoint unreachable for a bounded window, and lift it.
Interacts With:    adapters.queue.sqs, worker.bootstrap, the fault lab, docker compose exec
Sprint/Task:       Sprint 3 — Project 3
Concepts:          Fault injection, dependency outage, transport errors, deterministic emulation
Tools:             Python 3.12, boto3, botocore

The worker reaches LocalStack SQS through one boto3 client that its composition root builds.
This module wraps that client: while the fault is applied, every call the wrapped client
would make raises the same ``EndpointConnectionError`` botocore raises when the endpoint does
not answer, before any request leaves the process. To the worker loop, the dead-letter depth
monitor, and their logs, the endpoint is unreachable; to the API, the initializer, and the
host-side queue tools, LocalStack is up, exactly as it is when only one consumer's route to
a queue is cut.

The control is the same flag-file shape as the provider emulator's (``adapters.model.faults``):
``apply`` writes the fault's catalog id into ``/tmp/coldline-queue-fault`` inside the worker
container, ``lift`` removes it, and the wrapper reads it before every call.

Commands, run inside the worker container:

    python -m adapters.queue.faults apply queue_unavailable   # every queue call now fails
    python -m adapters.queue.faults lift                      # the endpoint answers again
    python -m adapters.queue.faults status                    # print the active fault, or `none`

The worker resolves its queue URLs at startup with the unwrapped client, so a flag left
behind by an interrupted lab never keeps the worker from starting; it only keeps the loop
from receiving until the flag is lifted.
"""

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from botocore.exceptions import EndpointConnectionError

FAULT_PATH = Path("/tmp/coldline-queue-fault")
QUEUE_UNAVAILABLE = "queue_unavailable"
FAULTS = (QUEUE_UNAVAILABLE,)


class QueueFaultControls:
    """Read and change the one fault flag the wrapped queue client consults."""

    def __init__(self, path: Path = FAULT_PATH) -> None:
        """Bind the controls to one flag file; the default is the container's own."""
        self._path = path

    @property
    def path(self) -> Path:
        """Return the flag file these controls read and write."""
        return self._path

    def current(self) -> str | None:
        """Return the active fault's catalog id, or None when the endpoint is reachable."""
        try:
            name = self._path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None
        except OSError:
            return None
        return name if name in FAULTS else None

    def apply(self, fault: str) -> None:
        """Activate one supplied fault for every queue call that starts from now on."""
        if fault not in FAULTS:
            raise ValueError(f"unknown queue fault {fault!r}; supplied: {', '.join(FAULTS)}")
        self._path.write_text(fault + "\n", encoding="utf-8")

    def lift(self) -> None:
        """Deactivate whatever fault is applied; the next queue call reaches the endpoint."""
        self._path.unlink(missing_ok=True)


class FaultableSqsClient:
    """Wrap one SQS client so its calls fail as unreachable while the fault is applied.

    Every attribute lookup is delegated to the wrapped client. A callable attribute (an API
    operation) is returned as a wrapper that consults the fault controls first and raises
    ``EndpointConnectionError`` for the wrapped endpoint while ``queue_unavailable`` is
    active; anything else (``exceptions``, ``meta``) is returned as it is.
    """

    def __init__(self, client: Any, *, endpoint_url: str, faults: QueueFaultControls) -> None:
        """Bind the wrapper to one client, the endpoint it names, and the fault controls."""
        self._client = client
        self._endpoint_url = endpoint_url
        self._faults = faults

    def __getattr__(self, name: str) -> Any:
        """Delegate to the wrapped client, guarding every operation with the fault flag."""
        attribute = getattr(self._client, name)
        if not callable(attribute):
            return attribute
        operation: Callable[..., Any] = attribute

        def guarded(*args: Any, **kwargs: Any) -> Any:
            if self._faults.current() == QUEUE_UNAVAILABLE:
                raise EndpointConnectionError(endpoint_url=self._endpoint_url)
            return operation(*args, **kwargs)

        return guarded


def main(argv: list[str] | None = None) -> int:
    """Apply, lift, or print the queue endpoint fault from the command line."""
    parser = argparse.ArgumentParser(description="Control the worker's queue endpoint fault.")
    parser.add_argument("--path", type=Path, default=FAULT_PATH, help="the flag file to use")
    commands = parser.add_subparsers(dest="command", required=True)
    apply_parser = commands.add_parser("apply", help="activate one supplied fault")
    apply_parser.add_argument("fault", choices=FAULTS)
    commands.add_parser("lift", help="deactivate the fault")
    commands.add_parser("status", help="print the active fault, or none")
    args = parser.parse_args(argv)
    controls = QueueFaultControls(args.path)
    if args.command == "apply":
        controls.apply(args.fault)
        print(f"applied {args.fault}")
    elif args.command == "lift":
        controls.lift()
        print("lifted")
    else:
        print(controls.current() or "none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
