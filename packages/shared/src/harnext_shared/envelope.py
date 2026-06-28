"""CloudEvents v1.0 envelope with harnext extensions.

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

    # harnext extensions (lowercase per CloudEvents extension naming rules)
    mgtenant: str = Field(description="Tenant id; server-set from auth context.")
    mgingesttime: datetime | None = Field(
        default=None,
        description="When the Ingest API observed the event. Server-set, never trusted from caller.",
    )
    mgblobref: str | None = Field(
        default=None,
        description="Object-store URL when payload is a blob (file uploads).",
    )
    ordering_key: str | None = Field(
        default=None,
        description=(
            "Optional Kafka ordering domain, decoupled from `subject`. `subject` is "
            "*entity identity* (drives how the builder organizes the FS); "
            "`ordering_key` is the *ordering domain* (the coarsest entity within "
            "which event order must be preserved, and no coarser). They diverge for "
            "sources like Stripe (`subject=stripe:invoice` but `ordering_key=customer:…`). "
            "Each connector declares its key via the reviewed derivation table "
            "(harnext_ingest.connectors.ordering, D1 in #14). Unset → partition by "
            "`subject`, so existing topics behave identically."
        ),
    )

    def partition_key(self) -> bytes:
        """Tenant-scoped Kafka partition key over the event's *ordering domain*.

        Uses ``ordering_key`` when set, else falls back to ``subject`` — so an
        unset ``ordering_key`` reproduces the original ``{mgtenant}:{subject}``
        routing exactly. Same key → same partition → serialized; different keys →
        different partitions → parallel.
        """
        return f"{self.mgtenant}:{self.ordering_key or self.subject}".encode()
