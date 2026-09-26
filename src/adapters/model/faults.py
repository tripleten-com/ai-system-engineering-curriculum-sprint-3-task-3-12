"""Coldline.

===================

File:              src/adapters/model/faults.py
Component:         Adapter — Provider emulator fault controls
Purpose:           Apply, lift, and read the one catalog fault the provider emulator offers.
Interacts With:    adapters.model.deterministic, tests/failure/fault_lab.py, docker compose exec
Sprint/Task:       Sprint 3 — Project 3
Concepts:          Fault injection, bounded outage, deterministic emulation
Tools:             Python 3.12

The emulator is an in-process adapter, so a fault has to reach it from outside the
container without a network endpoint. The control is one flag file inside the container's
own filesystem: ``apply`` writes the fault's catalog id into it, ``lift`` removes it, and
the provider reads it at the start of every ``summarize`` call. The file lives under
``/tmp``, which the unprivileged runtime user can write, and it is per container, so
applying a fault to the worker never touches another container's emulator.

Commands, run inside the worker container:

    python -m adapters.model.faults apply provider_outage   # every provider call now fails
    python -m adapters.model.faults lift                    # back to the deterministic summary
    python -m adapters.model.faults status                  # print the active fault, or `none`

One fault is supplied, and its name is its catalog id (``infra/faults/catalog.yaml``).
``provider_outage`` makes the emulated provider answer every call with a retryable error, as
a hosted provider does while it is down: the resilient wrapper spends its attempt budget on
the call, the worker records the failure and returns the delivery for the transport to
redeliver, and the reading completes once the fault is lifted and the message becomes
visible again. No reading ends ``FAILED`` from this fault alone; that outcome would need
the delivery budget to run out while the fault is still active.
"""

import argparse
import sys
from pathlib import Path

from domain.errors import RetryableProviderError

FAULT_PATH = Path("/tmp/coldline-provider-fault")
PROVIDER_OUTAGE = "provider_outage"
FAULTS = (PROVIDER_OUTAGE,)


class ProviderFaultControls:
    """Read and change the one fault flag the deterministic provider consults."""

    def __init__(self, path: Path = FAULT_PATH) -> None:
        """Bind the controls to one flag file; the default is the container's own."""
        self._path = path

    @property
    def path(self) -> Path:
        """Return the flag file these controls read and write."""
        return self._path

    def current(self) -> str | None:
        """Return the active fault's catalog id, or None when the emulator behaves normally."""
        try:
            name = self._path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None
        except OSError:
            return None
        return name if name in FAULTS else None

    def apply(self, fault: str) -> None:
        """Activate one supplied fault for every provider call that starts from now on."""
        if fault not in FAULTS:
            raise ValueError(f"unknown provider fault {fault!r}; supplied: {', '.join(FAULTS)}")
        self._path.write_text(fault + "\n", encoding="utf-8")

    def lift(self) -> None:
        """Deactivate whatever fault is applied; a call already failing still returns."""
        self._path.unlink(missing_ok=True)


def outage() -> None:
    """Fail the calling provider request the way a provider that is down does."""
    raise RetryableProviderError(
        f"provider emulator fault: {PROVIDER_OUTAGE} answered the call with an error"
    )


def main(argv: list[str] | None = None) -> int:
    """Apply, lift, or print the emulator fault from the command line."""
    parser = argparse.ArgumentParser(description="Control the deterministic provider's fault.")
    parser.add_argument("--path", type=Path, default=FAULT_PATH, help="the flag file to use")
    commands = parser.add_subparsers(dest="command", required=True)
    apply_parser = commands.add_parser("apply", help="activate one supplied fault")
    apply_parser.add_argument("fault", choices=FAULTS)
    commands.add_parser("lift", help="deactivate the fault")
    commands.add_parser("status", help="print the active fault, or none")
    args = parser.parse_args(argv)
    controls = ProviderFaultControls(args.path)
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
