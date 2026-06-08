"""YouTube connector — polls a channel's videos and emits each video's captions.

YouTube has no push webhook for "channel uploaded a video", so this is a
*polling* connector: ``fetch`` enumerates the channel's Videos tab with yt-dlp
(a flat, cheap listing), then for each *new* video pulls the full metadata and
its caption track — preferring a manually-authored subtitle in a configured
language, falling back to YouTube's auto-generated captions, then to whatever
track exists. Each video → one ``com.youtube.caption`` CloudEvent whose
``data["text"]`` is the transcript, so the same downstream pipeline that ingests
chat messages can process the spoken content.

The cursor is the newest video id seen on the channel, fed back to skip already
-ingested uploads. yt-dlp returns the Videos tab newest-first, so we collect new
ids until we hit the cursor, then reverse to chronological order.

yt-dlp is a blocking, synchronous library, so every extraction runs in a worker
thread (``asyncio.to_thread``) to keep the event loop free. It is imported lazily
inside ``_extract_info`` so importing this module never requires the dependency
and tests can stub the extraction seam.
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import re
from datetime import UTC, datetime
from typing import Any, cast

import httpx
from meaninggrid_shared import CloudEvent

from meaninggrid_ingest.connectors.base import FetchResult, PollingConnector

log = logging.getLogger("ingest.connectors.youtube")

# Channel sub-pages that are already a concrete listing — a channel_url ending in
# one of these (or pointing at a playlist/video) is used as given; anything else
# (a bare channel root) gets the uploads tab appended.
_YT_TABS = ("videos", "shorts", "streams", "live", "playlists", "featured", "community", "about")

# Caption languages tried in order before falling back to any available track.
DEFAULT_LANGS = ("en", "en-US", "en-GB", "en-orig")
# Caption formats we know how to parse, best (cleanest to parse) first.
_FORMAT_PREF = ("json3", "srv1", "srv3", "vtt", "ttml")
# Transcripts are the whole point here, so unlike chat bodies they are not
# clipped to ~1k chars — only capped well below Kafka's default 1 MiB message
# limit so a pathological multi-hour transcript can't wedge the producer.
_CAPTION_CLIP = 100_000

_TAG_RE = re.compile(r"<[^>]+>")
_XML_TEXT_RE = re.compile(r"<(?:text|p)\b[^>]*>(.*?)</(?:text|p)>", re.DOTALL | re.IGNORECASE)


def _extract_info(url: str, *, flat: bool, limit: int | None = None) -> dict[str, Any]:
    """Run yt-dlp's extractor for ``url`` and return its info dict.

    ``flat=True`` enumerates a channel/playlist cheaply (one entry per video, no
    per-video network round-trip); ``flat=False`` resolves a single video's full
    metadata including ``subtitles`` / ``automatic_captions``. yt-dlp is imported
    here (not at module top) so the connector module imports without the optional
    dependency and tests can monkeypatch this seam.
    """
    import yt_dlp  # noqa: PLC0415 — lazy: keeps yt-dlp optional + stubbable in tests

    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist" if flat else False,
    }
    if flat and limit:
        opts["playlistend"] = limit
    # yt-dlp's stubs type these as internal TypedDicts; cast at the boundary.
    with yt_dlp.YoutubeDL(cast(Any, opts)) as ydl:
        return cast("dict[str, Any]", ydl.extract_info(url, download=False) or {})


def _channel_videos_url(config: dict[str, Any]) -> str:
    """Resolve the channel's uploads (Videos-tab) URL from the source config.

    A ``channel_url`` is normalized to ``…/videos`` unless it already targets a
    specific tab, playlist, or video. This matters: a bare channel root
    (``/@handle`` or ``/channel/UC…``) flat-extracts to the channel's *tabs*
    (Videos, Shorts, …), not its uploads, so it yields no videos. A
    ``channel_id`` may be a ``UC…`` id or an ``@handle`` (a bare handle is
    treated as ``@handle``).
    """
    raw = config.get("channel_url")
    if raw:
        u = str(raw).strip().rstrip("/")
        last = u.rsplit("/", 1)[-1].lower()
        if last in _YT_TABS or "list=" in u or "/watch" in u or "/playlist" in u:
            return u  # already a concrete listing — use as given
        return f"{u}/videos"
    ident = str(config["channel_id"])
    if ident.startswith("@"):
        return f"https://www.youtube.com/{ident}/videos"
    if ident.startswith(("UC", "UU")):
        return f"https://www.youtube.com/channel/{ident}/videos"
    return f"https://www.youtube.com/@{ident}/videos"


def _langs(config: dict[str, Any]) -> list[str]:
    """Preferred caption languages, from ``caption_langs`` (list or CSV) /
    ``caption_lang``, else the English-first defaults."""
    raw = config.get("caption_langs") or config.get("caption_lang")
    if isinstance(raw, str):
        raw = [x.strip() for x in raw.split(",") if x.strip()]
    return list(raw) if raw else list(DEFAULT_LANGS)


def _video_time(video: dict[str, Any]) -> datetime:
    """Best available upload time: epoch ``timestamp`` → ``upload_date`` → now."""
    ts = video.get("timestamp")
    if ts:
        return datetime.fromtimestamp(int(ts), tz=UTC)
    d = video.get("upload_date")
    if isinstance(d, str) and len(d) == 8 and d.isdigit():
        return datetime(int(d[:4]), int(d[4:6]), int(d[6:8]), tzinfo=UTC)
    return datetime.now(tz=UTC)


def _select_track(
    info: dict[str, Any], langs: list[str]
) -> tuple[str | None, list[dict[str, Any]] | None]:
    """Choose a caption track: a preferred-language track (manual subtitle first,
    then auto-caption), else any available track (manual first). Returns the
    language tag and its list of format dicts, or ``(None, None)``."""
    subs = info.get("subtitles") or {}
    autos = info.get("automatic_captions") or {}
    for store in (subs, autos):
        for lang in langs:
            if store.get(lang):
                return lang, store[lang]
    for store in (subs, autos):
        for lang, fmts in store.items():
            if fmts:
                return lang, fmts
    return None, None


def _pick_format(fmts: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the most parse-friendly caption format that has a download url."""
    by_ext: dict[str, dict[str, Any]] = {}
    for f in fmts:
        ext = f.get("ext")
        if f.get("url") and ext and ext not in by_ext:
            by_ext[ext] = f
    for ext in _FORMAT_PREF:
        if ext in by_ext:
            return by_ext[ext]
    return next((f for f in fmts if f.get("url")), None)


def _collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _from_json3(body: str) -> str:
    try:
        doc = json.loads(body)
    except ValueError:
        return ""
    parts = [
        seg["utf8"]
        for ev in (doc.get("events") or [])
        for seg in (ev.get("segs") or [])
        if seg.get("utf8")
    ]
    return _collapse_ws("".join(parts))


def _from_xml(body: str) -> str:
    parts = _XML_TEXT_RE.findall(body) or [_TAG_RE.sub("", body)]
    return _collapse_ws(" ".join(html.unescape(p) for p in parts))


def _from_vtt(body: str) -> str:
    lines: list[str] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line == "WEBVTT" or "-->" in line or line.isdigit():
            continue
        if line.startswith(("NOTE", "STYLE", "REGION")):
            continue
        line = html.unescape(_TAG_RE.sub("", line)).strip()  # drop <c>/<00:00:00.000> tags
        if line and (not lines or lines[-1] != line):  # collapse the repeats auto-captions emit
            lines.append(line)
    return _collapse_ws(" ".join(lines))


def _parse_caption(body: str, ext: str) -> str:
    body = body or ""
    if ext == "json3":
        return _from_json3(body)
    if ext == "vtt":
        return _from_vtt(body)
    if "<text" in body or "<p" in body:  # srv1/srv3/ttml are timed XML
        return _from_xml(body)
    return _collapse_ws(body)


class YouTubeConnector(PollingConnector):
    kind = "youtube"

    def __init__(self, limit: int = 25, caption_clip: int = _CAPTION_CLIP) -> None:
        self.limit = limit
        self.caption_clip = caption_clip

    async def fetch(
        self, *, org_id: str, config: dict[str, Any], secret: str | None, since: str | None
    ) -> FetchResult:
        # secret is unused: public captions need no auth (the abstract contract
        # keeps the param for parity with token-based connectors).
        if not (config.get("channel_id") or config.get("channel_url")):
            raise RuntimeError("YouTube source requires a channel_id or channel_url")
        langs = _langs(config)

        try:
            listing = await asyncio.to_thread(
                _extract_info, _channel_videos_url(config), flat=True, limit=self.limit
            )
        except Exception as e:  # noqa: BLE001 — surface a clean sync error to the service
            raise RuntimeError(f"YouTube channel listing failed: {e}") from e

        # Key events on a stable channel id (the same UC… for every upload) so
        # ``source``/``id`` stay clean and consistent even when the source was
        # configured with only a handle or a ``/videos`` URL.
        channel = str(
            config.get("channel_id")
            or listing.get("channel_id")
            or listing.get("uploader_id")
            or listing.get("id")
            or config["channel_url"]
        )
        channel_name = (
            config.get("channel_name")
            or listing.get("channel")
            or listing.get("uploader")
            or listing.get("title")
            or channel
        )

        entries = [e for e in (listing.get("entries") or []) if e and e.get("id")]
        fresh: list[dict[str, Any]] = []  # newest-first
        for e in entries:
            if since and e["id"] == since:  # reached the watermark — rest already ingested
                break
            fresh.append(e)
        fresh.reverse()  # -> chronological (oldest first)

        events: list[CloudEvent] = []
        for entry in fresh:
            vid = str(entry["id"])
            watch = entry.get("url") or f"https://www.youtube.com/watch?v={vid}"
            try:
                info = await asyncio.to_thread(_extract_info, watch, flat=False)
            except Exception as exc:  # noqa: BLE001 — one bad video can't fail the whole sync
                log.warning("youtube: skipping video %s (%s)", vid, exc)
                continue
            text, lang = await self._caption_text(info or {}, langs)
            events.append(
                self._video_event(
                    org_id=org_id,
                    channel=channel,
                    channel_name=channel_name,
                    video={**entry, **(info or {})},
                    video_id=vid,
                    text=text,
                    lang=lang,
                )
            )

        events.sort(key=lambda ev: ev.time)
        # Watermark advances to the newest enumerated upload regardless of
        # per-video caption outcome, so the listing stays monotonic and we never
        # re-walk the whole tab.
        cursor = entries[0]["id"] if entries else since
        return FetchResult(events=events, cursor=cursor)

    async def _caption_text(
        self, info: dict[str, Any], langs: list[str]
    ) -> tuple[str | None, str | None]:
        """Download and flatten the best caption track to plain text. Returns
        ``(text, lang)``; ``(None, None)`` when the video has no captions."""
        lang, fmts = _select_track(info, langs)
        if not fmts:
            return None, None
        fmt = _pick_format(fmts)
        if not fmt:
            return None, lang
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(fmt["url"])
            r.raise_for_status()
            body = r.text
        return _parse_caption(body, str(fmt.get("ext", ""))), lang

    def _video_event(
        self,
        *,
        org_id: str,
        channel: str,
        channel_name: str,
        video: dict[str, Any],
        video_id: str,
        text: str | None,
        lang: str | None,
    ) -> CloudEvent:
        """One video's caption → a CloudEvent. ``id`` matches the dedup key shape
        of the other connectors; ``subject`` keys on the channel so a channel's
        uploads stay ordered in one Kafka partition; the transcript rides in
        ``data["text"]`` like every other connector's primary content."""
        time = _video_time(video)
        return CloudEvent(
            id=f"youtube-{channel}-{video_id}",
            source=f"youtube:{channel}",
            type="com.youtube.caption",
            subject=f"channel:{channel_name}",
            time=time,
            mgtenant=org_id,
            data={
                "video_id": video_id,
                "channel_id": channel,
                "channel_name": channel_name,
                "title": video.get("title"),
                "url": video.get("webpage_url") or f"https://www.youtube.com/watch?v={video_id}",
                "uploader": video.get("uploader") or video.get("channel"),
                "duration": video.get("duration"),
                "published_at": time.isoformat(),
                "caption_lang": lang,
                "has_caption": bool(text),
                "text": self.clip(text, limit=self.caption_clip),
            },
        )
