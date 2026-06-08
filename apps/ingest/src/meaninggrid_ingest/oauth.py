"""OAuth helpers for GitHub + Slack + Discord connect flows.

Authorize-URL building, code→token exchange, and repo/channel listing. CSRF
state is kept in-memory (single-instance MVP). For GitHub/Slack the obtained
access token is stored on the Project and sources reuse it; for Discord the
"Connect" flow only records the invited guild (the poller uses one app-level
bot token), so the exchange returns the guild rather than a per-project token.
"""

from __future__ import annotations

import secrets
import time
from urllib.parse import urlencode

import httpx


class OAuthError(Exception):
    pass


# state -> (project_id, provider, monotonic_ts)
_states: dict[str, tuple[str, str, float]] = {}
_STATE_TTL = 600.0


def new_state(project_id: str, provider: str) -> str:
    token = secrets.token_urlsafe(24)
    _states[token] = (project_id, provider, time.monotonic())
    return token


def consume_state(state: str) -> tuple[str, str] | None:
    v = _states.pop(state, None)
    if v is None:
        return None
    project_id, provider, ts = v
    if time.monotonic() - ts > _STATE_TTL:
        return None
    return project_id, provider


def redirect_uri(base: str, provider: str) -> str:
    return f"{base}/oauth/{provider}/callback"


def google_authorize_url(client_id: str, redirect: str, state: str) -> str:
    q = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "online",
            "prompt": "select_account",
        }
    )
    return f"https://accounts.google.com/o/oauth2/v2/auth?{q}"


async def google_exchange(client_id: str, client_secret: str, code: str, redirect: str) -> dict:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect,
                "grant_type": "authorization_code",
            },
        )
        r.raise_for_status()
        access = r.json().get("access_token")
        if not access:
            raise OAuthError("google token exchange returned no access_token")
        u = await c.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {access}"},
        )
        u.raise_for_status()
        info = u.json()
    return {
        "sub": info.get("sub"),
        "email": info.get("email"),
        "name": info.get("name"),
        "picture": info.get("picture"),
    }


def github_login_authorize_url(client_id: str, redirect: str, state: str) -> str:
    q = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect,
            "scope": "read:user user:email",
            "state": state,
        }
    )
    return f"https://github.com/login/oauth/authorize?{q}"


async def github_login_exchange(
    client_id: str, client_secret: str, code: str, redirect: str
) -> dict:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect,
            },
            headers={"Accept": "application/json"},
        )
        r.raise_for_status()
        token = r.json().get("access_token")
        if not token:
            raise OAuthError("github token exchange returned no access_token")
        hdr = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
        user = (await c.get("https://api.github.com/user", headers=hdr)).json()
        email = user.get("email")
        if not email:  # primary email may be private — fetch it explicitly
            emails = (await c.get("https://api.github.com/user/emails", headers=hdr)).json()
            if isinstance(emails, list):
                primary = next((e for e in emails if e.get("primary") and e.get("verified")), None)
                email = (primary or (emails[0] if emails else {})).get("email")
    return {
        "email": email,
        "name": user.get("name") or user.get("login"),
        "avatar": user.get("avatar_url"),
    }


def github_authorize_url(client_id: str, redirect: str, state: str) -> str:
    q = urlencode(
        {"client_id": client_id, "redirect_uri": redirect, "scope": "repo read:org", "state": state}
    )
    return f"https://github.com/login/oauth/authorize?{q}"


def slack_authorize_url(client_id: str, redirect: str, state: str) -> str:
    q = urlencode(
        {
            "client_id": client_id,
            "scope": "channels:history,channels:read,groups:history,groups:read",
            "redirect_uri": redirect,
            "state": state,
        }
    )
    return f"https://slack.com/oauth/v2/authorize?{q}"


async def github_exchange(client_id: str, client_secret: str, code: str, redirect: str) -> dict:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect,
            },
            headers={"Accept": "application/json"},
        )
        r.raise_for_status()
        data = r.json()
        if "access_token" not in data:
            raise OAuthError(data.get("error_description") or str(data))
        token = data["access_token"]
        u = await c.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        )
    login = u.json().get("login") if u.status_code == 200 else None
    return {"token": token, "login": login}


async def slack_exchange(client_id: str, client_secret: str, code: str, redirect: str) -> dict:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(
            "https://slack.com/api/oauth.v2.access",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect,
            },
        )
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise OAuthError(data.get("error") or "slack oauth failed")
    team = data.get("team", {})
    return {
        "token": data.get("access_token"),
        "team_id": team.get("id"),
        "team_name": team.get("name"),
    }


async def github_create_webhook(token: str, repo: str, url: str, secret: str) -> str | None:
    """Idempotently register a push/issues/PR/comment webhook on ``repo`` (needs
    the OAuth ``repo`` scope, which includes hook admin). Returns the new hook id,
    or None if one with this ``url`` already exists. Raises OAuthError otherwise."""
    hdr = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    async with httpx.AsyncClient(timeout=20) as c:
        existing = await c.get(f"https://api.github.com/repos/{repo}/hooks", headers=hdr)
        if existing.status_code == 200:
            for h in existing.json():
                if (h.get("config") or {}).get("url") == url:
                    return None  # already registered — nothing to do
        r = await c.post(
            f"https://api.github.com/repos/{repo}/hooks",
            headers=hdr,
            json={
                "name": "web",
                "active": True,
                "events": ["push", "issues", "pull_request", "issue_comment"],
                "config": {"url": url, "content_type": "json", "secret": secret, "insecure_ssl": "0"},
            },
        )
        if r.status_code not in (200, 201):
            raise OAuthError(f"github hook create {r.status_code}: {r.text[:200]}")
        return str(r.json().get("id"))


async def github_list_repos(token: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(
            "https://api.github.com/user/repos",
            params={"per_page": 100, "sort": "updated"},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        )
    r.raise_for_status()
    return [{"full_name": x["full_name"]} for x in r.json()]


async def slack_list_channels(token: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(
            "https://slack.com/api/conversations.list",
            params={"types": "public_channel", "limit": 200},
            headers={"Authorization": f"Bearer {token}"},
        )
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise OAuthError(data.get("error") or "slack list failed")
    return [{"id": ch["id"], "name": ch["name"]} for ch in data.get("channels", [])]


def discord_authorize_url(client_id: str, redirect: str, state: str) -> str:
    # scope "bot" invites our app's bot into the chosen guild; permissions 66560
    # = View Channel (1024) | Read Message History (65536).
    q = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect,
            "response_type": "code",
            "scope": "bot",
            "permissions": "66560",
            "state": state,
        }
    )
    return f"https://discord.com/oauth2/authorize?{q}"


async def discord_exchange(client_id: str, client_secret: str, code: str, redirect: str) -> dict:
    """Complete the bot-invite. Returns the guild the bot was added to — the
    poller uses the app-level bot token, so no per-project token is stored."""
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(
            "https://discord.com/api/oauth2/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect,
            },
        )
    r.raise_for_status()
    guild = r.json().get("guild") or {}
    if not guild.get("id"):
        raise OAuthError("discord authorization returned no guild — was the bot added to a server?")
    return {"guild_id": guild.get("id"), "guild_name": guild.get("name")}


async def discord_list_channels(guild_id: str, bot_token: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(
            f"https://discord.com/api/v10/guilds/{guild_id}/channels",
            headers={"Authorization": f"Bot {bot_token}"},
        )
    r.raise_for_status()
    # type 0 == GUILD_TEXT
    return [{"id": ch["id"], "name": ch["name"]} for ch in r.json() if ch.get("type") == 0]
