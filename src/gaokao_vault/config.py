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
    use_freeproxy: bool = False
    refresh_interval_min: int = 30


class CrawlConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GAOKAO_CRAWL__")

    concurrency: int = 5
    concurrency_per_domain: int = 3
    base_delay: float = 1.0
    jitter_ratio: float = 0.5
    batch_size: int = 500
    max_blocked_retries: int = 3
    crawl_dir: str = "./crawl_data"


class AppConfig(BaseSettings):
    db: DatabaseConfig = Field(default_factory=DatabaseConfig)
    proxy: ProxyConfig = Field(default_factory=ProxyConfig)
    crawl: CrawlConfig = Field(default_factory=CrawlConfig)


def get_config() -> AppConfig:
    return AppConfig()
