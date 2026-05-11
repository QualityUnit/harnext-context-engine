"""GraphitiSink — writes each event as one Graphiti episode.

Field mapping per docs/architecture/ingestion-pipeline.md §10:
    name             = f"{source}:{type}:{event_id}"
    episode_body     = artifacts['text'] OR json.dumps(event.data)
    reference_time   = event.time  (the bitemporal event_time)
    source           = EpisodeType.text or EpisodeType.json
    group_id         = event.mgtenant   (Graphiti's tenant boundary)

`created_at` on the resulting nodes/edges is Graphiti's wall-clock at write,
which is effectively `ingest_time`. → bitemporal by construction.
"""

import json
import logging

from graphiti_core import Graphiti
from graphiti_core.nodes import EpisodeType

from meaninggrid_shared import IngestionContext

log = logging.getLogger("meaninggrid.worker.sinks.graphiti")


class GraphitiSink:
    name = "graphiti"
    requires: list[str] = []  # consumes event.data; "text" when a processor extracted it

    def __init__(self, client: Graphiti) -> None:
        self._client = client

    async def write(self, ctx: IngestionContext) -> None:
        text = ctx.artifacts.get("text")
        if text:
            episode_body = text
            episode_type = EpisodeType.text
        else:
            episode_body = json.dumps(ctx.event.data or {}, default=str)
            episode_type = EpisodeType.json

        episode_name = f"{ctx.event.source}:{ctx.event.type}:{ctx.event.id}"
        log.debug("graphiti.add_episode name=%s tenant=%s", episode_name, ctx.event.mgtenant)

        await self._client.add_episode(
            name=episode_name,
            episode_body=episode_body,
            source=episode_type,
            source_description=ctx.event.source,
            reference_time=ctx.event.time,
            group_id=ctx.event.mgtenant,
        )
