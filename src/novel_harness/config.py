"""Environment based configuration."""

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import quote_plus

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = "development"
    log_level: str = "INFO"
    log_file: Path | None = Path("logs/novel-harness.log")
    log_max_bytes: int = 10 * 1024 * 1024
    log_backup_count: int = 5

    database_host: str = "localhost"
    database_port: int = 3306
    database_name: str = "novel_agent"
    database_root_user: str = "root"
    database_root_password: str = "root_password"
    database_user: str = "novel_agent"
    database_password: str = "novel_agent_password"

    minio_endpoint: str = "localhost:20000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_secure: bool = False
    minio_bucket: str = "novel-agent"

    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_collection: str = "novel_chunks_qwen_v4_1024"

    embedding_provider: Literal["deterministic", "qwen"] = "qwen"
    embedding_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    embedding_model: str = "text-embedding-v4"
    embedding_dimension: int = 1024
    qwen_api_key: str = ""

    llm_provider: Literal["mock", "openai_compatible"] = "openai_compatible"
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    llm_model: str = "deepseek-v4-flash"
    deepseek_api_key: str = ""
    llm_supports_json_schema: bool = False
    llm_input_cost_per_million: float = Field(default=0.0, ge=0)
    llm_output_cost_per_million: float = Field(default=0.0, ge=0)

    search_provider: Literal["mock", "searxng"] = "searxng"
    searxng_base_url: str = "https://searxng.dsppt.site"

    cache_provider: Literal["none", "redis"] = "redis"
    redis_host: str = "localhost"
    redis_port: int = 20_005
    redis_password: str = "myredissecret"
    redis_database: int = 0
    redis_cache_ttl_seconds: int = 900

    auth_required: bool = True
    auth_service_url: str = "http://localhost:8001"
    auth_request_timeout_seconds: float = 5.0
    auth_database_name: str = "novel_auth"

    billing_enabled: bool = True
    billing_required: bool = True
    billing_service_url: str = "http://localhost:8002"
    billing_internal_api_key: str = ""
    billing_request_timeout_seconds: float = 5.0
    billing_database_name: str = "novel_billing"

    request_timeout_seconds: float = 30.0
    provider_max_retries: int = 2
    research_fetch_enabled: bool = True
    research_fetch_max_bytes: int = 2 * 1024 * 1024
    research_fetch_max_sources: int = 5
    context_max_characters: int = 24_000
    context_retrieval_limit: int = 12
    workflow_lease_seconds: int = 300
    workflow_retry_backoff_seconds: int = 5
    worker_poll_interval_seconds: float = 1.0
    originality_max_contiguous_chars: int = 24
    originality_max_ngram_overlap: float = Field(default=0.35, ge=0, le=1)
    max_upload_bytes: int = 20 * 1024 * 1024
    cors_origins: str = "http://localhost:5173"
    prompt_directory: Path = Path(__file__).parent / "prompts"

    @field_validator("minio_endpoint")
    @classmethod
    def normalize_minio_endpoint(cls, value: str) -> str:
        return value.removeprefix("http://").removeprefix("https://").rstrip("/")

    @property
    def database_url(self) -> str:
        user = quote_plus(self.database_user)
        password = quote_plus(self.database_password)
        return (
            f"mysql+pymysql://{user}:{password}@{self.database_host}:"
            f"{self.database_port}/{self.database_name}?charset=utf8mb4"
        )

    @property
    def root_database_url(self) -> str:
        user = quote_plus(self.database_root_user)
        password = quote_plus(self.database_root_password)
        return (
            f"mysql+pymysql://{user}:{password}@{self.database_host}:"
            f"{self.database_port}/?charset=utf8mb4"
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return a process-wide immutable-by-convention settings instance."""

    return Settings()
