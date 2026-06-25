"""Minimal Mailchimp Marketing API client — upsert an audience member + tag.

Used by the closed-beta / webinar registration endpoint. We never store these
contacts ourselves: the email + name go straight to a Mailchimp audience so the
existing audience stays the single source of truth (tagged, not duplicated)."""

from __future__ import annotations

import hashlib

import httpx


class MailchimpError(RuntimeError):
    """A Mailchimp API call failed (network error or non-2xx response)."""


def _datacenter(api_key: str) -> str:
    """Mailchimp keys are ``<secret>-<dc>`` (e.g. ``...-us21``); the datacenter
    suffix selects the API host. Raise early if the key is malformed."""
    _, _, dc = api_key.rpartition("-")
    if not dc:
        raise MailchimpError("malformed Mailchimp API key (expected '<key>-<dc>')")
    return dc


def subscriber_hash(email: str) -> str:
    """Mailchimp addresses a member by the MD5 of the lowercased email."""
    return hashlib.md5(email.strip().lower().encode()).hexdigest()


async def upsert_member(
    *,
    api_key: str,
    audience_id: str,
    email: str,
    name: str | None,
    tag: str,
    status_if_new: str = "subscribed",
) -> str:
    """Add or update a contact in ``audience_id`` and apply ``tag``.

    Idempotent: PUT upserts by subscriber hash, so a person already on the list
    is matched (not duplicated) and simply gets the tag. Returns the member's
    Mailchimp status (e.g. ``"subscribed"``, ``"pending"``).
    """
    dc = _datacenter(api_key)
    base = f"https://{dc}.api.mailchimp.com/3.0"
    auth = ("anystring", api_key)  # HTTP Basic: username ignored, key is the password
    sub = subscriber_hash(email)

    first, _, last = (name or "").strip().partition(" ")
    body: dict = {
        "email_address": email.strip().lower(),
        "status_if_new": status_if_new,
        "merge_fields": {"FNAME": first, "LNAME": last},
        # Applying the tag in the upsert keeps it to a single round-trip and works
        # for brand-new members; existing members keep their current status.
        "tags": [tag],
    }
    async with httpx.AsyncClient(timeout=20) as c:
        try:
            res = await c.put(f"{base}/lists/{audience_id}/members/{sub}", json=body, auth=auth)
        except httpx.HTTPError as e:
            raise MailchimpError(f"Mailchimp request failed: {e}") from e
    if res.status_code >= 400:
        detail = ""
        try:
            detail = res.json().get("detail", "")
        except Exception:  # noqa: BLE001 - body may not be JSON
            detail = res.text[:200]
        raise MailchimpError(f"Mailchimp returned {res.status_code}: {detail}")
    return res.json().get("status", status_if_new)
