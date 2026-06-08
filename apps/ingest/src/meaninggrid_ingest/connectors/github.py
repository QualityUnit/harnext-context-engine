"""GitHub connector — pulls a repo's recent issues, PRs, comments, and commits
as CloudEvents. Token optional (public repos work unauthenticated, with a lower
rate limit). Incremental via the GitHub ``since`` parameter.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
from meaninggrid_shared import CloudEvent, utcnow

from meaninggrid_ingest.connectors.base import FetchResult

_API = "https://api.github.com"
_BODY_CLIP = 1200


def _parse_ts(s: str | None) -> datetime:
    if not s:
        return utcnow()
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _clip(s: str | None) -> str:
    s = s or ""
    return s if len(s) <= _BODY_CLIP else s[:_BODY_CLIP] + "…"


class GitHubConnector:
    kind = "github"

    def __init__(self, per_page: int = 30) -> None:
        self.per_page = per_page

    async def fetch(
        self, *, org_id: str, config: dict[str, Any], secret: str | None, since: str | None
    ) -> FetchResult:
        repo = config["repo"]  # "owner/name"
        subject = f"repo:{repo}"
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if secret:
            headers["Authorization"] = f"Bearer {secret}"

        events: list[CloudEvent] = []
        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            issues = await self._get(
                client,
                f"{_API}/repos/{repo}/issues",
                since,
                state="all",
                sort="updated",
                direction="desc",
            )
            for it in issues:
                is_pr = "pull_request" in it
                ts = it.get("updated_at")
                events.append(
                    CloudEvent(
                        id=f"github-issue-{repo}-{it['number']}-{ts}",
                        source=f"github:{repo}",
                        type="com.github.pull_request" if is_pr else "com.github.issue",
                        subject=subject,
                        time=_parse_ts(ts),
                        mgtenant=org_id,
                        data={
                            "number": it["number"],
                            "title": it.get("title"),
                            "state": it.get("state"),
                            "body": _clip(it.get("body")),
                            "labels": [lbl["name"] for lbl in it.get("labels", [])],
                            "author": (it.get("user") or {}).get("login"),
                            "url": it.get("html_url"),
                            "is_pull_request": is_pr,
                        },
                    )
                )

            comments = await self._get(
                client,
                f"{_API}/repos/{repo}/issues/comments",
                since,
                sort="updated",
                direction="desc",
            )
            for c in comments:
                ts = c.get("updated_at")
                events.append(
                    CloudEvent(
                        id=f"github-comment-{repo}-{c['id']}-{ts}",
                        source=f"github:{repo}",
                        type="com.github.issue_comment",
                        subject=subject,
                        time=_parse_ts(ts),
                        mgtenant=org_id,
                        data={
                            "comment_id": c["id"],
                            "body": _clip(c.get("body")),
                            "author": (c.get("user") or {}).get("login"),
                            "url": c.get("html_url"),
                            "issue_url": c.get("issue_url"),
                        },
                    )
                )

            commits = await self._get(client, f"{_API}/repos/{repo}/commits", since)
            for cm in commits:
                commit = cm.get("commit", {})
                ts = (commit.get("author") or {}).get("date")
                events.append(
                    CloudEvent(
                        id=f"github-commit-{repo}-{cm['sha']}",
                        source=f"github:{repo}",
                        type="com.github.commit",
                        subject=subject,
                        time=_parse_ts(ts),
                        mgtenant=org_id,
                        data={
                            "sha": cm["sha"],
                            "message": _clip(commit.get("message")),
                            "author": (commit.get("author") or {}).get("name"),
                            "url": cm.get("html_url"),
                        },
                    )
                )

        events.sort(key=lambda e: e.time)
        cursor = max((e.time for e in events), default=None)
        return FetchResult(events=events, cursor=cursor.isoformat() if cursor else since)

    async def _get(
        self, client: httpx.AsyncClient, url: str, since: str | None, **params: str
    ) -> list[dict[str, Any]]:
        q: dict[str, Any] = {"per_page": self.per_page, **params}
        if since:
            q["since"] = since
        r = await client.get(url, params=q)
        if r.status_code == 404:
            raise RuntimeError(
                "repository not found or private — check the name and provide a token with access"
            )
        if r.status_code == 401:
            raise RuntimeError("GitHub rejected the token — it's invalid or expired")
        if r.status_code == 403:
            if "rate limit" in r.text.lower():
                raise RuntimeError("GitHub rate limit exceeded — add a token to increase it")
            raise RuntimeError(
                "GitHub denied access (403) — the token lacks permission for this repository"
            )
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []
