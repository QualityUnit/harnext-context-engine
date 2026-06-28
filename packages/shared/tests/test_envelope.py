"""CloudEvent envelope: the ``ordering_key`` field and its effect on ``partition_key``.

Covers D1/#15: ``ordering_key`` decouples the Kafka ordering domain from
``subject`` (entity identity). The key invariants:

* Unset ``ordering_key`` reproduces the original ``{mgtenant}:{subject}`` routing
  exactly (existing topics behave identically).
* When set, ``partition_key`` keys on ``ordering_key`` instead.
* The divergent case ``subject=invoice`` / ``ordering_key=customer`` routes by
  customer, so different subjects under one customer share a partition key.
"""

from datetime import UTC, datetime

from harnext_shared import CloudEvent


def _event(**overrides) -> CloudEvent:
    base = dict(
        id="evt-1",
        source="stripe:acme",
        type="com.stripe.event",
        subject="stripe:invoice",
        time=datetime(2026, 1, 1, tzinfo=UTC),
        mgtenant="org-7",
    )
    base.update(overrides)
    return CloudEvent(**base)


def test_ordering_key_defaults_to_none_and_falls_back_to_subject():
    """Unset → partition by subject, byte-identical to the pre-#15 behaviour."""
    ev = _event()
    assert ev.ordering_key is None
    assert ev.partition_key() == b"org-7:stripe:invoice"


def test_partition_key_uses_ordering_key_when_set():
    ev = _event(ordering_key="customer:cus_123")
    assert ev.partition_key() == b"org-7:customer:cus_123"


def test_divergent_subject_and_ordering_key_share_a_partition_by_customer():
    """subject=invoice, ordering_key=customer — the canonical divergent case.

    An invoice event and a charge event for the *same* customer carry different
    subjects but the same ordering key → identical partition key → same partition
    → serialized. (Issue #15 acceptance: "Test covers the divergent case".)
    """
    invoice = _event(subject="stripe:invoice", ordering_key="customer:cus_123")
    charge = _event(subject="stripe:charge", ordering_key="customer:cus_123")

    assert invoice.subject != charge.subject
    assert invoice.partition_key() == charge.partition_key() == b"org-7:customer:cus_123"

    # A different customer lands on a different key → free to run in parallel.
    other = _event(subject="stripe:invoice", ordering_key="customer:cus_999")
    assert other.partition_key() != invoice.partition_key()


def test_empty_ordering_key_falls_back_to_subject():
    """An empty string is falsy → treated as unset (`ordering_key or subject`)."""
    ev = _event(ordering_key="")
    assert ev.partition_key() == b"org-7:stripe:invoice"


def test_ordering_key_round_trips_through_serialization():
    """Set at ingest, the key must survive (de)serialization so downstream lanes
    inherit the same partition domain."""
    ev = _event(ordering_key="customer:cus_123")
    restored = CloudEvent.model_validate_json(ev.model_dump_json())
    assert restored.ordering_key == "customer:cus_123"
    assert restored.partition_key() == ev.partition_key()
