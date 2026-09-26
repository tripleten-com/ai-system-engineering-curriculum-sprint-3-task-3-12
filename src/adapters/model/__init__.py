"""Coldline.

===================

File:              src/adapters/model/__init__.py
Component:         Model adapters — Package exports
Purpose:           Expose active model-provider adapters and the emulator's fault controls.
Interacts With:    Domain contracts, ports, and local providers
Sprint/Task:       Sprint 3 — Project 3
Concepts:          Boundary translation, deterministic infrastructure, bounded resilience
Tools:             Python 3.12
"""

from adapters.model.deterministic import DeterministicModelProvider
from adapters.model.faults import ProviderFaultControls
from adapters.model.resilient import ResilientModelProvider, classify_default

__all__ = [
    "DeterministicModelProvider",
    "ProviderFaultControls",
    "ResilientModelProvider",
    "classify_default",
]
