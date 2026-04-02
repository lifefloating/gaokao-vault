"""Tests for the data pipeline: hasher, validator, and dedup logic."""

from __future__ import annotations

from gaokao_vault.models.school import SchoolItem
from gaokao_vault.models.score import ScoreLineItem
from gaokao_vault.pipeline.hasher import compute_content_hash
from gaokao_vault.pipeline.validator import validate_item


class TestContentHash:
    def test_deterministic(self):
        item = {"name": "Test School", "sch_id": 1, "city": "Beijing"}
        h1 = compute_content_hash(item)
        h2 = compute_content_hash(item)
        assert h1 == h2

    def test_excludes_meta_fields(self):
        item1 = {"name": "Test", "sch_id": 1}
        item2 = {"name": "Test", "sch_id": 1, "id": 99, "created_at": "2024-01-01", "content_hash": "abc"}
        assert compute_content_hash(item1) == compute_content_hash(item2)

    def test_different_content_different_hash(self):
        item1 = {"name": "School A", "sch_id": 1}
        item2 = {"name": "School B", "sch_id": 1}
        assert compute_content_hash(item1) != compute_content_hash(item2)

    def test_key_order_independent(self):
        item1 = {"name": "Test", "sch_id": 1, "city": "Beijing"}
        item2 = {"city": "Beijing", "sch_id": 1, "name": "Test"}
        assert compute_content_hash(item1) == compute_content_hash(item2)


class TestValidator:
    def test_valid_school_item(self):
        data = {"sch_id": 1, "name": "Test University"}
        result = validate_item(SchoolItem, data)
        assert result is not None
        assert result["sch_id"] == 1
        assert result["name"] == "Test University"
        assert result["is_211"] is False

    def test_invalid_school_item_missing_required(self):
        data = {"sch_id": 1}  # missing 'name'
        result = validate_item(SchoolItem, data)
        assert result is None

    def test_valid_score_line(self):
        data = {
            "province_id": 1,
            "year": 2024,
            "batch": "本科一批",
            "score": 530,
        }
        result = validate_item(ScoreLineItem, data)
        assert result is not None
        assert result["year"] == 2024

    def test_invalid_score_line_year(self):
        data = {
            "province_id": 1,
            "year": 1999,  # below 2000 minimum
            "batch": "本科一批",
        }
        result = validate_item(ScoreLineItem, data)
        assert result is None

    def test_school_defaults(self):
        data = {"sch_id": 42, "name": "Test U"}
        result = validate_item(SchoolItem, data)
        assert result is not None
        assert result["is_985"] is False
        assert result["is_double_first"] is False
        assert result["province_id"] is None
