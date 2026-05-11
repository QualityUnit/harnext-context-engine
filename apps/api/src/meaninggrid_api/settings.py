from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    api_host: str = "0.0.0.0"
    api_port: int = 8000

    kafka_bootstrap_servers: str = "localhost:9092"

    falkordb_host: str = "localhost"
    falkordb_port: int = 6379
    falkordb_username: str = ""
    falkordb_password: str = ""

    minio_endpoint: str = "http://localhost:9000"
    minio_access_key: str = "meaninggrid"
    minio_secret_key: str = "meaninggrid_dev"
    minio_bucket: str = "meaninggrid-blobs"

    # Graphiti LLM + embedder. Defaults point at local Ollama via its OpenAI-compatible endpoint.
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "ollama"
    llm_model: str = "qwen3.6:27b"
    embedding_model: str = "nomic-embed-text"
    embedding_dim: int = 768

    database_url: str = "sqlite+aiosqlite:///./data/meaninggrid.sqlite"


settings = Settings()
