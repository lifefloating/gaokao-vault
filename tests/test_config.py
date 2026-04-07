"""Tests for configuration and constants."""

from __future__ import annotations

from gaokao_vault.config import CrawlConfig, DatabaseConfig, ProxyConfig
from gaokao_vault.constants import BASE_URL, META_FIELDS, PHASE2_TYPES, PHASE3_TYPES, TaskType


class TestConfig:
    def test_database_config_defaults(self):
        config = DatabaseConfig()
        assert config.pool_min == 5
        assert config.pool_max == 20

    def test_crawl_config_defaults(self):
        config = CrawlConfig()
        assert config.concurrency == 2
        assert config.base_delay > 0
        assert 0 < config.jitter_ratio < 1

    def test_proxy_config_defaults(self):
        config = ProxyConfig()
        assert isinstance(config.static_proxies, (list, tuple))


class TestConstants:
    def test_base_url(self):
        assert "gaokao.chsi.com.cn" in BASE_URL

    def test_meta_fields(self):
        assert "id" in META_FIELDS
        assert "created_at" in META_FIELDS
        assert "content_hash" in META_FIELDS

    def test_task_types_enum(self):
        assert TaskType.SCHOOLS.value == "schools"
        assert TaskType.MAJORS.value == "majors"
        assert len(TaskType) == 14

    def test_phase_types(self):
        assert len(PHASE2_TYPES) == 5
        assert len(PHASE3_TYPES) == 8
        assert TaskType.SCHOOLS in PHASE2_TYPES
        assert TaskType.ANNOUNCEMENTS in PHASE2_TYPES
        assert TaskType.SCHOOL_MAJORS in PHASE3_TYPES
