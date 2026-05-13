"""Sinks — Phase B of the worker pipeline.

Each sink implements the meaninggrid_shared.Sink protocol.
See docs/architecture/ingestion-pipeline.md §9.4 for the contract and §9.8 for
the recipe to add a new sink.
"""

from meaninggrid_worker.sinks.faiss import FaissSink
from meaninggrid_worker.sinks.graphiti import GraphitiSink

__all__ = ["FaissSink", "GraphitiSink"]
