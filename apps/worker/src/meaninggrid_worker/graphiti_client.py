"""Graphiti instance for the worker (writes via add_episode).

Defaults to local Ollama for LLM + embedder; configurable via env (see settings.py).
"""

from graphiti_core import Graphiti
from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
from graphiti_core.driver.falkordb_driver import FalkorDriver
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.llm_client.openai_client import OpenAIClient

from meaninggrid_worker.settings import settings

_client: Graphiti | None = None


def _build_clients() -> tuple[OpenAIClient, OpenAIEmbedder, OpenAIRerankerClient]:
    llm_config = LLMConfig(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        small_model=settings.llm_model,
    )
    llm = OpenAIClient(config=llm_config)
    embedder = OpenAIEmbedder(
        config=OpenAIEmbedderConfig(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            embedding_model=settings.embedding_model,
            embedding_dim=settings.embedding_dim,
        )
    )
    reranker = OpenAIRerankerClient(config=llm_config)
    return llm, embedder, reranker


async def start_graphiti() -> None:
    global _client
    driver = FalkorDriver(
        host=settings.falkordb_host,
        port=settings.falkordb_port,
        username=settings.falkordb_username or None,
        password=settings.falkordb_password or None,
    )
    llm, embedder, reranker = _build_clients()
    _client = Graphiti(
        graph_driver=driver, llm_client=llm, embedder=embedder, cross_encoder=reranker
    )
    # Idempotent — Graphiti tolerates re-runs.
    await _client.build_indices_and_constraints()


async def stop_graphiti() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None


def get_graphiti() -> Graphiti:
    if _client is None:
        raise RuntimeError("Graphiti client not started")
    return _client
