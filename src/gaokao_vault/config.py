from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GAOKAO_DB__")

    dsn: str = "postgresql://localhost:5432/gaokao_vault"
    pool_min: int = 5
    pool_max: int = 20


class ProxyConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GAOKAO_PROXY__")

    static_proxies: list[str] = Field(default_factory=list)
    use_freeproxy: bool = True
    refresh_interval_min: int = 30


class CrawlConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GAOKAO_CRAWL__")

    concurrency: int = 2
    concurrency_per_domain: int = 1
    base_delay: float = 2.0
    jitter_ratio: float = 0.5
    batch_size: int = 500
    max_blocked_retries: int = 3
    crawl_dir: str = "./crawl_data"
    year_start: int = 2015
    rs_wait_ms: int = 10000  # Wait time (ms) for RS anti-bot JS challenge


class OpenAIConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OPENAI_")

    api_base: str = "https://api.openai.com/v1"
    api_key: str = ""
    health_model: str = "gpt-5.4"
    vision_model: str = "gpt-5.4"


class S3Config(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="S3_")

    endpoint_url: str = "http://minio:9000"
    public_url: str = "http://localhost:9000"
    access_key: str = "minioadmin"
    secret_key: str = "minioadmin"  # noqa: S105
    bucket_name: str = "gaokao-screenshots"
    presign_expires: int = 3600


class AppConfig(BaseSettings):
    db: DatabaseConfig = Field(default_factory=DatabaseConfig)
    proxy: ProxyConfig = Field(default_factory=ProxyConfig)
    crawl: CrawlConfig = Field(default_factory=CrawlConfig)
    openai: OpenAIConfig = Field(default_factory=OpenAIConfig)
    s3: S3Config = Field(default_factory=S3Config)


def get_config() -> AppConfig:
    return AppConfig()


def create_openai_client(config: OpenAIConfig, *, timeout: float = 60, max_retries: int = 2):
    """Create an AsyncOpenAI client with a browser-like User-Agent.

    Some third-party OpenAI-compatible proxies sit behind Cloudflare which
    blocks the default ``AsyncOpenAI/Python`` User-Agent.  Using a generic
    UA via ``default_headers`` avoids the 403 block.
    """
    from openai import AsyncOpenAI

    return AsyncOpenAI(
        base_url=config.api_base,
        api_key=config.api_key,
        timeout=timeout,
        max_retries=max_retries,
        default_headers={"User-Agent": "Mozilla/5.0"},
    )
