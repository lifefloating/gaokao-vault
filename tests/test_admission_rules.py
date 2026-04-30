from __future__ import annotations

from gaokao_vault.pipeline.admission_rules import (
    extract_adjustment_rule,
    extract_physical_exam_limit,
    extract_single_subject_limit,
)


def test_extract_plan_specific_admission_rules() -> None:
    note = "不招色盲,英语单科不低于110分,服从专业调剂"

    assert extract_physical_exam_limit(note) == "不招色盲"
    assert extract_single_subject_limit(note) == "英语单科不低于110分"
    assert extract_adjustment_rule(note) == "服从专业调剂"
