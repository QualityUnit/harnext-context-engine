"""Per-connector ordering-key derivation — the reviewed connector contract (D1, #15).

The Kafka partition key is ``f"{mgtenant}:{ordering_key or subject}"`` (see
``harnext_shared.envelope``). The **ordering key** names an event's *ordering
domain*: the coarsest entity within which event order must be preserved, and no
coarser. Decoupling it from ``subject`` (the *entity identity* the builder
organizes the FS around) lets sources where the two diverge stay correctly
ordered without collapsing every entity into one partition — e.g. Stripe emits
``subject=stripe:invoice`` but orders by ``ordering_key=customer:cus_123`` so a
customer's invoice/charge/refund events serialize while different customers run
in parallel.

    * Different ordering keys → different partitions → run in parallel.
    * Same ordering key       → same partition       → serialized (safe for tasks
      that write back to the same AgentFS / external resource).

This table is the **single, reviewed place** each connector declares its key, so
adding a source forces an explicit, auditable choice rather than ad-hoc code
scattered across connectors. ``tests/test_ordering.py`` asserts every
``SUPPORTED_KINDS`` entry has a rule here. A rule returns ``None`` to fall back to
``subject`` — the connector's natural channel/repo/site granularity — which is the
right answer when an event has no finer ordering domain (a GitHub commit, a
standalone Slack message, a Discord channel poll).

Derivation reads only the constructed :class:`CloudEvent` (``data``/``subject``/
``source``), so the rules are pure and unit-testable, and a single application
point (``Producer.send_event``) stamps every connector's events the same way.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from harnext_shared import CloudEvent


@dataclass(frozen=True)
class OrderingRule:
    """One connector's ordering-key derivation plus the domain it was reviewed under.

    ``domain`` is the human-readable ordering domain (shown in reviews/docs);
    ``derive`` maps an event to its ordering key, or ``None`` to fall back to
    ``subject``.
    """

    domain: str
    derive: Callable[[CloudEvent], str | None]


def _repo_of(event: CloudEvent) -> str:
    """``github:owner/name`` → ``owner/name`` (the ``source`` suffix)."""
    return event.source.split(":", 1)[1] if ":" in event.source else event.source


def _stripe_customer(event: CloudEvent) -> str | None:
    """Stripe → the customer the event is about.

    ``subject`` keys on the resource (invoice/charge/…); the *ordering* domain is
    the customer, so a customer's lifecycle stays serialized. invoice/charge/
    subscription objects carry ``customer`` flat; ``customer.*`` events *are* the
    customer (the object id is the customer id). No customer (e.g. account-level
    events) → fall back to the resource ``subject``.
    """
    data = event.data or {}
    customer = data.get("customer")
    if not customer and data.get("object") == "customer":
        customer = data.get("object_id")
    return f"customer:{customer}" if customer else None


def _github_pr_issue(event: CloudEvent) -> str | None:
    """GitHub → the PR/issue thread the event belongs to.

    Issues and PRs carry ``number``; ``issue_comment`` carries the parent issue's
    API url (``…/issues/123``). Commits belong to no PR/issue → fall back to the
    repo ``subject`` (``repo:owner/name``).
    """
    data = event.data or {}
    number = data.get("number")
    if number is None:
        issue_url = data.get("issue_url")
        if isinstance(issue_url, str) and issue_url:
            tail = issue_url.rstrip("/").rsplit("/", 1)[-1]
            number = tail if tail.isdigit() else None
    return f"{_repo_of(event)}#{number}" if number is not None else None


def _slack_thread(event: CloudEvent) -> str | None:
    """Slack → the thread (fallback channel).

    Replies carry ``thread_ts`` (the root message's ts); a thread's messages must
    stay ordered among themselves but are independent of the channel's other
    threads → their own partition. Standalone messages have no ``thread_ts`` →
    fall back to the channel ``subject``.
    """
    thread_ts = (event.data or {}).get("thread_ts")
    return f"{event.subject}:thread:{thread_ts}" if thread_ts else None


def _channel(event: CloudEvent) -> str | None:
    """Discord → the channel (fallback for "thread").

    The poller pulls one channel at a time and tracks no per-thread granularity,
    so the channel ``subject`` *is* the ordering domain.
    """
    return None


def _liveagent_ticket(event: CloudEvent) -> str | None:
    """LiveAgent → the ticket the event is about (a ticket's updates serialize)."""
    tid = (event.data or {}).get("ticket_id")
    return f"ticket:{tid}" if tid else None


def _youtube_video(event: CloudEvent) -> str | None:
    """YouTube → the video (re-indexing a caption serializes per-video; different
    videos run in parallel)."""
    vid = (event.data or {}).get("video_id")
    return f"video:{vid}" if vid else None


def _web_page(event: CloudEvent) -> str | None:
    """Web (sitemap/url) → the page url. Each page is independent, but re-crawls of
    the *same* url must process in order → key on the url."""
    url = (event.data or {}).get("url")
    return f"page:{url}" if url else None


# The reviewed table. One row per connector kind; adding a connector means adding a
# row here (enforced by tests/test_ordering.py against SUPPORTED_KINDS).
ORDERING_KEYS: dict[str, OrderingRule] = {
    "stripe": OrderingRule("Stripe customer", _stripe_customer),
    "github": OrderingRule("GitHub PR/issue", _github_pr_issue),
    "slack": OrderingRule("Slack thread (fallback channel)", _slack_thread),
    "discord": OrderingRule("Discord channel", _channel),
    "liveagent": OrderingRule("LiveAgent ticket", _liveagent_ticket),
    "youtube": OrderingRule("YouTube video", _youtube_video),
    "sitemap": OrderingRule("Web page (sitemap)", _web_page),
    "url": OrderingRule("Web page (url)", _web_page),
}


def derive_ordering_key(event: CloudEvent) -> str | None:
    """The connector's declared ordering key for ``event`` (``None`` → use ``subject``).

    The connector is resolved by the ``source`` prefix — every connector emits
    ``source=f"{kind}:…"``. An unknown kind falls back to ``subject`` so an
    unrecognized source can never break publishing; ``tests/test_ordering.py``
    guarantees every supported kind has a rule, so this never silently degrades in
    practice.
    """
    kind = event.source.split(":", 1)[0]
    rule = ORDERING_KEYS.get(kind)
    return rule.derive(event) if rule else None
