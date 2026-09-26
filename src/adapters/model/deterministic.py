"""Coldline.

===================

File:              src/adapters/model/deterministic.py
Component:         Adapter — Deterministic
Purpose:           Implement the deterministic local model-provider adapter, with its fault control.
Interacts With:    Domain contracts, ports, local providers, adapters.model.faults
Sprint/Task:       Sprint 3 — Project 3
Concepts:          Boundary translation, deterministic infrastructure, fault injection
Tools:             Python 3.12, OpenTelemetry
"""

import asyncio

from opentelemetry import trace

from adapters.model.faults import PROVIDER_OUTAGE, ProviderFaultControls, outage
from domain.contracts import ModelRequest, ModelSummary

_TRACER = trace.get_tracer(__name__)


class DeterministicModelProvider:
    """Return repeatable summaries without network or paid-model calls.

    Task 3.12 gives the emulator one fault control. When ``faults`` is supplied, every
    call first asks it whether a fault is active; with none, the provider behaves exactly
    as it did in every earlier Task. Tests and callers that pass no controls never read
    a flag file at all.
    """

    def __init__(
        self, *, latency_ms: int = 250, faults: ProviderFaultControls | None = None
    ) -> None:
        """Configure a fixed non-negative provider delay in milliseconds and the fault control."""
        if latency_ms < 0:
            raise ValueError("latency_ms must not be negative")
        self._latency_seconds = latency_ms / 1000
        self._faults = faults

    async def summarize(self, request: ModelRequest) -> ModelSummary:
        """Return a bounded summary for one synthetic temperature excursion."""
        with _TRACER.start_as_current_span(
            "model_provider.summarize",
            attributes={"coldline.exception_id": request.exception_id},
        ) as span:
            active = self._faults.current() if self._faults is not None else None
            if active == PROVIDER_OUTAGE:
                # Recorded on the span so the trace names the fault the reading met. The
                # outage raises, and the span records that exception and ends in error.
                span.set_attribute("coldline.provider_fault", active)
                outage()

            if self._latency_seconds:
                await asyncio.sleep(self._latency_seconds)

            if request.temperature_c > request.allowed_max_c:
                magnitude = request.temperature_c - request.allowed_max_c
                condition = f"exceeded the upper handling bound by {magnitude:.1f} C"
            else:
                magnitude = request.allowed_min_c - request.temperature_c
                condition = f"fell below the lower handling bound by {magnitude:.1f} C"

            return ModelSummary(
                provider="deterministic-local",
                summary=(
                    f"Synthetic shipment {request.shipment_id} {condition}; "
                    "operational review is required."
                ),
            )
