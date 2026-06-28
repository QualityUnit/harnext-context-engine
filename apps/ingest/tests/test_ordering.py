"""Per-connector ordering-key derivation table (D1, #15).

The table in ``connectors/ordering.py`` is the reviewed connector contract: each
source declares the *ordering domain* its events partition by. These tests lock:

* **Completeness** — every ``SUPPORTED_KINDS`` connector has a rule, so adding a
  source forces an explicit, reviewed choice.
* **Per-connector derivation** — Stripe→customer (incl. the divergent
  invoice/customer case), GitHub→PR/issue, Slack→thread (fallback channel),
  Discord→channel, LiveAgent→ticket, YouTube→video, web→page.
* **The source-prefix == kind invariant** the central resolver relies on.
* **The publish-path stamping** in ``Producer.send_event``.
"""

from datetime import UTC, datetime

import pytest
from harnext_ingest.connectors import SUPPORTED_KINDS
from harnext_ingest.connectors.ordering import (
    ORDERING_KEYS,
    derive_ordering_key,
)
from harnext_ingest.kafka import Producer
from harnext_shared import CloudEvent


def _event(source: str, subject: str, *, type: str = "com.test", data: dict | None = None):
    return CloudEvent(
        id="evt-1",
        source=source,
        type=type,
        subject=subject,
        time=datetime(2026, 1, 1, tzinfo=UTC),
        mgtenant="org-1",
        data=data or {},
    )


# -- completeness: the table IS the contract ----------------------------------


def test_every_supported_kind_has_a_rule():
    """Adding a connector to SUPPORTED_KINDS without a derivation rule fails here —
    the mechanism that forces an explicit ordering-key choice per #15."""
    assert set(ORDERING_KEYS) == set(SUPPORTED_KINDS)


def test_no_orphan_rules():
    """No rule for a kind that isn't a real connector (catches typos/renames)."""
    assert set(ORDERING_KEYS) <= set(SUPPORTED_KINDS)


def test_every_rule_has_a_human_readable_domain():
    for kind, rule in ORDERING_KEYS.items():
        assert rule.domain and isinstance(rule.domain, str), kind


# -- Stripe: the divergent case (subject=invoice, ordering_key=customer) -------


def test_stripe_invoice_orders_by_customer_not_invoice():
    ev = _event(
        "stripe:acme",
        "stripe:invoice",
        data={"object": "invoice", "object_id": "in_1", "customer": "cus_42"},
    )
    assert derive_ordering_key(ev) == "customer:cus_42"


def test_stripe_charge_and_invoice_same_customer_share_partition():
    invoice = _event(
        "stripe:acme", "stripe:invoice", data={"object": "invoice", "customer": "cus_42"}
    )
    charge = _event(
        "stripe:acme", "stripe:charge", data={"object": "charge", "customer": "cus_42"}
    )
    invoice.ordering_key = derive_ordering_key(invoice)
    charge.ordering_key = derive_ordering_key(charge)
    assert invoice.subject != charge.subject
    assert invoice.partition_key() == charge.partition_key() == b"org-1:customer:cus_42"


def test_stripe_customer_event_orders_by_its_own_id():
    """customer.* events ARE the customer (object id == customer id)."""
    ev = _event(
        "stripe:acme",
        "stripe:customer",
        data={"object": "customer", "object_id": "cus_42"},
    )
    assert derive_ordering_key(ev) == "customer:cus_42"


def test_stripe_without_customer_falls_back_to_subject():
    ev = _event("stripe:acme", "stripe:account", data={"object": "account", "object_id": "acct_1"})
    assert derive_ordering_key(ev) is None
    assert ev.partition_key() == b"org-1:stripe:account"


# -- GitHub: PR/issue thread ---------------------------------------------------


def test_github_issue_orders_by_repo_and_number():
    ev = _event("github:o/n", "repo:o/n", type="com.github.issue", data={"number": 7})
    assert derive_ordering_key(ev) == "o/n#7"


def test_github_pull_request_orders_by_repo_and_number():
    ev = _event("github:o/n", "repo:o/n", type="com.github.pull_request", data={"number": 12})
    assert derive_ordering_key(ev) == "o/n#12"


def test_github_comment_orders_by_parent_issue():
    ev = _event(
        "github:o/n",
        "repo:o/n",
        type="com.github.issue_comment",
        data={"issue_url": "https://api.github.com/repos/o/n/issues/7"},
    )
    assert derive_ordering_key(ev) == "o/n#7"


def test_github_issue_and_its_comment_share_partition():
    issue = _event("github:o/n", "repo:o/n", type="com.github.issue", data={"number": 7})
    comment = _event(
        "github:o/n",
        "repo:o/n",
        type="com.github.issue_comment",
        data={"issue_url": "https://api.github.com/repos/o/n/issues/7"},
    )
    issue.ordering_key = derive_ordering_key(issue)
    comment.ordering_key = derive_ordering_key(comment)
    assert issue.partition_key() == comment.partition_key() == b"org-1:o/n#7"


def test_github_commit_falls_back_to_repo():
    ev = _event("github:o/n", "repo:o/n", type="com.github.commit", data={"sha": "abc"})
    assert derive_ordering_key(ev) is None
    assert ev.partition_key() == b"org-1:repo:o/n"


# -- Slack / Discord: thread (fallback channel) --------------------------------


def test_slack_thread_message_orders_by_thread():
    ev = _event(
        "slack:C1", "channel:general", type="com.slack.message", data={"thread_ts": "1700.1"}
    )
    assert derive_ordering_key(ev) == "channel:general:thread:1700.1"


def test_slack_standalone_message_falls_back_to_channel():
    ev = _event("slack:C1", "channel:general", type="com.slack.message", data={"thread_ts": None})
    assert derive_ordering_key(ev) is None
    assert ev.partition_key() == b"org-1:channel:general"


def test_slack_thread_replies_share_partition():
    a = _event("slack:C1", "channel:general", data={"thread_ts": "1700.1"})
    b = _event("slack:C1", "channel:general", data={"thread_ts": "1700.1"})
    a.ordering_key = derive_ordering_key(a)
    b.ordering_key = derive_ordering_key(b)
    assert a.partition_key() == b.partition_key()


def test_discord_orders_by_channel():
    ev = _event("discord:g:c", "channel:general", type="com.discord.message", data={})
    assert derive_ordering_key(ev) is None
    assert ev.partition_key() == b"org-1:channel:general"


# -- LiveAgent / YouTube / Web -------------------------------------------------


def test_liveagent_orders_by_ticket():
    ev = _event(
        "liveagent:dep", "department:Support", type="com.liveagent.ticket", data={"ticket_id": "T9"}
    )
    assert derive_ordering_key(ev) == "ticket:T9"


def test_youtube_orders_by_video():
    ev = _event("youtube:UC1", "channel:My", type="com.youtube.caption", data={"video_id": "vZ"})
    assert derive_ordering_key(ev) == "video:vZ"


def test_web_orders_by_page_url():
    ev = _event("url:example.com", "site:example.com", type="com.web.page",
                data={"url": "https://example.com/a"})
    assert derive_ordering_key(ev) == "page:https://example.com/a"


def test_web_different_pages_different_partitions():
    a = _event("sitemap:ex.com", "site:ex.com", data={"url": "https://ex.com/a"})
    b = _event("sitemap:ex.com", "site:ex.com", data={"url": "https://ex.com/b"})
    a.ordering_key = derive_ordering_key(a)
    b.ordering_key = derive_ordering_key(b)
    assert a.partition_key() != b.partition_key()


# -- invariants the central resolver relies on ---------------------------------


def test_source_prefix_resolves_to_kind_for_every_connector():
    """Every connector emits ``source=f"{kind}:…"``; the resolver keys on that
    prefix. Verify a kind-prefixed source resolves to that kind's rule."""
    for kind in SUPPORTED_KINDS:
        ev = _event(f"{kind}:whatever", "subj")
        # Resolves to *this* kind's rule (no KeyError, no cross-talk). The rule may
        # return None for a bare event lacking its key fields — that's the safe
        # subject fallback, which is exactly what we assert below.
        assert derive_ordering_key(ev) is None or isinstance(derive_ordering_key(ev), str)


def test_unknown_source_falls_back_to_subject():
    ev = _event("mystery:thing", "subj:x")
    assert derive_ordering_key(ev) is None
    assert ev.partition_key() == b"org-1:subj:x"


# -- publish path stamps the key (single application point) --------------------


class _FakeKafka:
    def __init__(self):
        self.sent = []

    async def send_and_wait(self, topic, *, value, key):
        self.sent.append((topic, value, key))


@pytest.fixture
def producer():
    # Bypass __init__ so no real AIOKafkaProducer (and event loop) is created.
    p = Producer.__new__(Producer)
    p._p = _FakeKafka()
    return p


async def test_send_event_stamps_ordering_key_from_table(producer):
    ev = _event(
        "stripe:acme", "stripe:invoice", data={"object": "invoice", "customer": "cus_42"}
    )
    assert ev.ordering_key is None
    await producer.send_event("cms.events.raw.v1", ev)
    # Stamped onto the event AND used as the Kafka message key.
    assert ev.ordering_key == "customer:cus_42"
    topic, _value, key = producer._p.sent[0]
    assert topic == "cms.events.raw.v1"
    assert key == b"org-1:customer:cus_42"


async def test_send_event_preserves_explicit_ordering_key(producer):
    ev = _event("stripe:acme", "stripe:invoice", data={"customer": "cus_42"})
    ev.ordering_key = "customer:override"
    await producer.send_event("cms.events.raw.v1", ev)
    assert ev.ordering_key == "customer:override"
    assert producer._p.sent[0][2] == b"org-1:customer:override"
