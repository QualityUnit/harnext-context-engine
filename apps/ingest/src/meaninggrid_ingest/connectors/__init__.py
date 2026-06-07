from meaninggrid_ingest.connectors.base import Connector, FetchResult
from meaninggrid_ingest.connectors.registry import SUPPORTED_KINDS, get_connector

__all__ = ["Connector", "FetchResult", "SUPPORTED_KINDS", "get_connector"]
