"""Processors — Phase A of the worker pipeline.

Each processor implements the meaninggrid_shared.Processor protocol.
See docs/architecture/ingestion-pipeline.md §9.3 for the contract and §9.7 for
the recipe to add a new processor.
"""

from meaninggrid_worker.processors.embed_document import EmbedDocumentProcessor
from meaninggrid_worker.processors.extract_text import ExtractTextProcessor
from meaninggrid_worker.processors.lift_text import LiftTextProcessor

__all__ = ["EmbedDocumentProcessor", "ExtractTextProcessor", "LiftTextProcessor"]
