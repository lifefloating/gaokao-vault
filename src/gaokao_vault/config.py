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


class AppConfig(BaseSettings):
    db: DatabaseConfig = Field(default_factory=DatabaseConfig)
    proxy: ProxyConfig = Field(default_factory=ProxyConfig)
    crawl: CrawlConfig = Field(default_factory=CrawlConfig)
    openai: OpenAIConfig = Field(default_factory=OpenAIConfig)


def get_config() -> AppConfig:
    return AppConfig()
