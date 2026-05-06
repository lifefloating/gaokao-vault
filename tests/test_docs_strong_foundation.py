from __future__ import annotations

from pathlib import Path

DOC_PATH = Path("docs/strong-foundation.md")
MKDOCS_YML = Path("mkdocs.yml")


def test_strong_foundation_design_doc_is_published_in_docs_nav() -> None:
    assert DOC_PATH.exists()
    assert "强基计划数据设计: strong-foundation.md" in MKDOCS_YML.read_text(encoding="utf-8")


def test_strong_foundation_design_doc_records_official_source_contract() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")

    for expected in (
        "https://gaokao.chsi.com.cn/gkzt/jcxkzs",
        "https://gaokao.chsi.com.cn/gkzt/jcxkzs#jcxkzs-sch",
        "https://bm.chsi.com.cn/jcxkzs/sch/",
        "https://www.moe.gov.cn/",
        "special_enrollments",
        "不并入普通批/提前批",
        "vector_documents_v",
    ):
        assert expected in text
