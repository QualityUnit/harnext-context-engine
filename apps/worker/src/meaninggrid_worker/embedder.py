"""Embedder singleton — used by processors that need vector embeddings.

Reuses the same Ollama OpenAI-compatible endpoint Graphiti uses (settings
`llm_base_url` + `embedding_model`), but exists separately so EmbedDocument-
Processor doesn't have to reach into Graphiti's internals.
"""

from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig

from meaninggrid_worker.settings import settings

_embedder: OpenAIEmbedder | None = None


def start_embedder() -> OpenAIEmbedder:
    global _embedder
    _embedder = OpenAIEmbedder(
        config=OpenAIEmbedderConfig(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            embedding_model=settings.embedding_model,
            embedding_dim=settings.embedding_dim,
        )
    )
    return _embedder


def get_embedder() -> OpenAIEmbedder:
    if _embedder is None:
        raise RuntimeError("Embedder not started")
    return _embedder
