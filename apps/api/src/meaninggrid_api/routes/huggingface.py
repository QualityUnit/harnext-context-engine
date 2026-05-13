"""HuggingFace dataset ingestion — pick a supported dataset, ingest the whole thing.

Each supported HF repo becomes one entry in the `DATASETS` catalog below.
A dataset may be physically split into multiple parts (the AIxBlock corpus is
11 ZIP files at the repo root, one per industry/direction); the catalog
hides that detail from the user — pick a dataset, click Import, and the
adapter iterates every part.

Per ingestion-pipeline.md §11, this is a built-in adapter: it consumes the
source's native format and emits CloudEvents into the existing
`events.raw.v1` topic. No downstream changes — the same processor chain
(extract_text → lift_text → embed_document) and the same sinks (graphiti +
faiss) handle the rest.

Adding a new dataset = one entry in DATASETS + (if its on-disk shape is
not a ZIP-of-JSON) a new emitter function. See `_emit_aixblock_zip` below
for the pattern.
"""

import asyncio
import json
import logging
import uuid
import zipfile
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from huggingface_hub import hf_hub_download
from huggingface_hub.errors import HfHubHTTPError
from meaninggrid_shared import CloudEvent, IngestedEvent
from pydantic import BaseModel, Field

from meaninggrid_api.auth import get_tenant_id
from meaninggrid_api.db import SessionLocal
from meaninggrid_api.kafka import publish_event

router = APIRouter(prefix="/api/v1/ingest/huggingface", tags=["ingest"])
log = logging.getLogger("meaninggrid.api.ingest.huggingface")


# ---------------------------------------------------------------------------
# Catalog of supported datasets
#
# Public-facing shape — what the dropdown shows. To add a new dataset, append
# one DatasetSpec here. If its on-disk shape is something other than the
# AIxBlock zip-of-JSON layout, also add a new emitter function and dispatch
# in `_run_import`.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Part:
    """One physical file inside a dataset (a ZIP archive for AIxBlock)."""
    filename: str
    domain: str
    direction: str


@dataclass(frozen=True)
class _DatasetSpec:
    key: str
    label: str
    dataset_id: str        # HuggingFace repo id
    description: str
    total_rows: int        # approximate — used for progress %
    layout: str            # "aixblock_zips" today; future kinds → new emitter
    parts: tuple[_Part, ...]


_DATASETS: tuple[_DatasetSpec, ...] = (
    _DatasetSpec(
        key="aixblock-call-center-92k",
        label="AIxBlock — 92k call-center transcripts (English)",
        dataset_id="AIxBlock/92k-real-world-call-center-scripts-english",
        description=(
            "91,706 real-world customer-service call transcripts (~10,500 hours) "
            "across medicare, auto + health insurance, automotive, home service, "
            "and telecom. Inbound + outbound. PII-redacted with word-level "
            "timestamps and ASR confidence scores."
        ),
        total_rows=91706,
        layout="aixblock_zips",
        parts=(
            _Part("medicare_inbound.zip", "medicare", "inbound"),
            _Part("auto_insurance_customer_service_inbound.zip", "auto_insurance", "inbound"),
            _Part("insurance_outbound.zip", "insurance", "outbound"),
            _Part("automotive_inbound.zip", "automotive", "inbound"),
            _Part("home_service_inbound.zip", "home_service", "inbound"),
            _Part("customer_service_general_inbound.zip", "customer_service", "inbound"),
            _Part("medical_equipment_outbound.zip", "medical_equipment", "outbound"),
            _Part("automotive_and_healthcare_insurance_inbound.zip", "insurance", "inbound"),
            # NB: filename has a typo + embedded space + ampersand in the upstream repo.
            _Part("home_ervice_inbound&telecom _outbound.zip", "home_service_and_telecom", "mixed"),
        ),
    ),
)
_DATASETS_BY_KEY = {d.key: d for d in _DATASETS}


# ---------------------------------------------------------------------------
# Wire types
# ---------------------------------------------------------------------------


class HfDataset(BaseModel):
    """Public view of a supported dataset (the dropdown payload)."""
    key: str
    label: str
    dataset_id: str
    description: str
    total_rows: int


class HfIngestRequest(BaseModel):
    dataset: str = Field(description="One of the keys from /api/v1/ingest/huggingface/datasets")


class HfIngestResponse(BaseModel):
    job_id: str
    dataset_id: str
    dataset_key: str
    target: int


class HfJobStatus(BaseModel):
    job_id: str
    dataset_id: str
    dataset_key: str
    state: str = Field(description="queued | downloading | importing | done | failed")
    target: int
    accepted: int = 0
    skipped: int = 0
    current_part: str | None = None
    error: str | None = None
    started_at: datetime
    finished_at: datetime | None = None


def _spec_to_public(spec: _DatasetSpec) -> HfDataset:
    return HfDataset(
        key=spec.key,
        label=spec.label,
        dataset_id=spec.dataset_id,
        description=spec.description,
        total_rows=spec.total_rows,
    )


# ---------------------------------------------------------------------------
# In-memory job state. Lost on API restart — fine for v0.
# ---------------------------------------------------------------------------

_jobs: dict[str, HfJobStatus] = {}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/datasets", response_model=list[HfDataset])
async def list_datasets() -> list[HfDataset]:
    return [_spec_to_public(d) for d in _DATASETS]


@router.get("/jobs/{job_id}", response_model=HfJobStatus)
async def get_job(job_id: str) -> HfJobStatus:
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return job


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=HfIngestResponse)
async def start_import(
    req: HfIngestRequest,
    tenant_id: Annotated[str, Depends(get_tenant_id)],
) -> HfIngestResponse:
    spec = _DATASETS_BY_KEY.get(req.dataset)
    if spec is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"unknown dataset '{req.dataset}'. Available: {sorted(_DATASETS_BY_KEY)}",
        )

    job_id = uuid.uuid4().hex[:12]
    job = HfJobStatus(
        job_id=job_id,
        dataset_id=spec.dataset_id,
        dataset_key=spec.key,
        state="queued",
        target=spec.total_rows,
        started_at=datetime.now(UTC),
    )
    _jobs[job_id] = job
    asyncio.create_task(_run_import(job_id, spec, tenant_id))
    return HfIngestResponse(
        job_id=job_id,
        dataset_id=spec.dataset_id,
        dataset_key=spec.key,
        target=spec.total_rows,
    )


# ---------------------------------------------------------------------------
# Job runner — dispatches to a layout-specific emitter
# ---------------------------------------------------------------------------


async def _run_import(job_id: str, spec: _DatasetSpec, tenant_id: str) -> None:
    job = _jobs[job_id]
    try:
        if spec.layout == "aixblock_zips":
            await _run_aixblock_zips(job, spec, tenant_id)
        else:
            raise ValueError(f"unsupported dataset layout: {spec.layout}")

        job.state = "done"
        job.current_part = None
        job.finished_at = datetime.now(UTC)
        log.info(
            "hf job=%s done accepted=%d skipped=%d", job_id, job.accepted, job.skipped
        )
    except HfHubHTTPError as e:
        job.state = "failed"
        job.error = f"HF download failed: {e}"
        job.finished_at = datetime.now(UTC)
        log.exception("hf job=%s download failed", job_id)
    except Exception as e:
        job.state = "failed"
        job.error = f"{type(e).__name__}: {e}"
        job.finished_at = datetime.now(UTC)
        log.exception("hf job=%s failed", job_id)


async def _run_aixblock_zips(job: HfJobStatus, spec: _DatasetSpec, tenant_id: str) -> None:
    """Sequentially download and emit each part (ZIP) of the AIxBlock corpus."""
    for part in spec.parts:
        job.current_part = part.filename
        job.state = "downloading"
        log.info("hf job=%s downloading %s/%s", job.job_id, spec.dataset_id, part.filename)
        zip_path = await asyncio.to_thread(_download_part, spec.dataset_id, part.filename)

        job.state = "importing"
        async for payload, entry_name in _iter_zip_entries(zip_path):
            try:
                await _emit_one_zip_entry(spec, part, entry_name, payload, tenant_id)
                job.accepted += 1
            except Exception as e:
                job.skipped += 1
                log.warning("hf job=%s emit failed %s: %s", job.job_id, entry_name, e)


def _download_part(dataset_id: str, filename: str) -> Path:
    """Cached on disk after first call (HF default cache)."""
    return Path(
        hf_hub_download(repo_id=dataset_id, filename=filename, repo_type="dataset")
    )


async def _iter_zip_entries(zip_path: Path) -> AsyncIterator[tuple[dict[str, Any], str]]:
    """Yield (payload_dict, entry_name) for every valid JSON inside the ZIP.

    macOS resource-fork siblings (`__MACOSX/._foo.json`) get filtered. JSON
    parse failures on individual entries are logged and skipped, not raised.
    Yielding is async so the event loop can interleave Kafka publishes /
    SQLite writes while we read the next entry from disk.
    """
    with zipfile.ZipFile(zip_path) as zf:
        entries = [
            n
            for n in zf.namelist()
            if n.lower().endswith(".json")
            and not n.startswith("__MACOSX/")
            and not Path(n).name.startswith("._")
        ]
        entries.sort()  # deterministic order across re-runs

        for name in entries:
            try:
                with zf.open(name) as f:
                    raw = f.read()
                payload = json.loads(raw.decode("utf-8-sig", errors="replace"))
            except Exception as e:
                log.warning("zip entry parse failed %s: %s", name, e)
                continue
            yield payload, name
            # Cooperative yield so the event loop can publish + write SQLite
            # in parallel with the next zip read.
            await asyncio.sleep(0)


async def _emit_one_zip_entry(
    spec: _DatasetSpec,
    part: _Part,
    entry_name: str,
    payload: dict[str, Any],
    tenant_id: str,
) -> None:
    """One ZIP entry → one CloudEvent (persisted + published)."""
    transcript = _extract_transcript(payload)
    domain = _str_or(payload, "domain", part.domain)
    topic = _str_or(payload, "topic", "")
    call_type = _str_or(payload, "call_type", part.direction)
    accent = _str_or(payload, "accent", "")

    # Drop the noisy arrays (timestamps, confidence_scores). They balloon the
    # SQLite `envelope_json` column and add no signal for embedding/labelling.
    clean = {
        "transcript": transcript,
        "domain": domain,
        "topic": topic,
        "call_type": call_type,
        "accent": accent,
        "source_file": entry_name,
    }

    entry_id = Path(entry_name).stem
    accepted_at = datetime.now(UTC)
    event = CloudEvent(
        id=f"hf:{spec.key}:{part.domain}:{entry_id}",
        source=f"huggingface:{part.domain}:{part.direction}",
        type="huggingface.call.imported",
        subject=f"call:{entry_id}",
        time=accepted_at,
        data=clean,
        mgtenant=tenant_id,
        mgingesttime=accepted_at,
    )

    async with SessionLocal() as session:
        existing = await session.get(IngestedEvent, (tenant_id, event.id))
        if existing is not None:
            # Idempotent re-import — skip without crashing.
            return
        session.add(
            IngestedEvent(
                tenant_id=event.mgtenant,
                event_id=event.id,
                source=event.source,
                type=event.type,
                subject=event.subject,
                event_time=event.time,
                ingest_time=event.mgingesttime or accepted_at,
                blob_ref=None,
                envelope_json=event.model_dump_json(),
            )
        )
        await session.commit()
    await publish_event(event)


def _extract_transcript(payload: dict[str, Any]) -> str:
    """Best-effort transcript extraction.

    Tolerates flat-string and list-of-segments shapes; falls back to longest
    top-level string. Adapter shouldn't crash on a minor schema variation in
    a 91k-row corpus.
    """
    for key in ("transcript", "text", "redacted_transcript", "content"):
        v = payload.get(key)
        if isinstance(v, str) and v.strip():
            return v
        if isinstance(v, list) and v:
            parts: list[str] = []
            for item in v:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    s = item.get("text") or item.get("transcript") or item.get("word")
                    if isinstance(s, str):
                        parts.append(s)
            if parts:
                return " ".join(parts)

    longest = ""
    for v in payload.values():
        if isinstance(v, str) and len(v) > len(longest):
            longest = v
    return longest


def _str_or(d: dict[str, Any], key: str, default: str) -> str:
    v = d.get(key)
    return v if isinstance(v, str) and v else default
