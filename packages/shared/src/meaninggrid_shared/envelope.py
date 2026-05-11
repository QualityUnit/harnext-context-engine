"""CloudEvents v1.0 envelope with meaninggrid extensions.

Spec: https://github.com/cloudevents/spec/blob/v1.0.2/cloudevents/spec.md
See docs/architecture/ingestion-pipeline.md §4 for the full schema.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CloudEvent(BaseModel):
    """The single normalization point. Every event in the pipeline is one of these."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    # CloudEvents v1.0 required attributes
    specversion: Literal["1.0"] = "1.0"
    id: str
    source: str
    type: str
    subject: str
    time: datetime
    datacontenttype: str = "application/json"
    data: dict[str, Any] | None = None

    # meaninggrid extensions (lowercase per CloudEvents extension naming rules)
    mgtenant: str = Field(description="Tenant id; server-set from auth context.")
    mgingesttime: datetime | None = Field(
        default=None,
        description="When the Ingest API observed the event. Server-set, never trusted from caller.",
    )
    mgblobref: str | None = Field(
        default=None,
        description="Object-store URL when payload is a blob (file uploads).",
    )

    def partition_key(self) -> bytes:
        """Tenant-scoped, entity-keyed partition key for Kafka."""
        return f"{self.mgtenant}:{self.subject}".encode()
