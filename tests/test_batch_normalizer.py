from __future__ import annotations

import pytest

from gaokao_vault.pipeline.batch_normalizer import BatchInfo, normalize_batch


@pytest.mark.parametrize(
    ("raw_batch", "expected"),
    [
        ("本科提前批A段", BatchInfo(code="early", category="提前批", segment="A段")),
        ("提前批普通类A段", BatchInfo(code="early", category="提前批", segment="A段")),
        ("高职专科提前批", BatchInfo(code="early", category="提前批", segment=None)),
        ("本科批", BatchInfo(code="regular", category="普通批", segment=None)),
        ("本科一批", BatchInfo(code="regular", category="普通批", segment=None)),
    ],
)
def test_normalize_batch_classifies_early_and_regular_batches(raw_batch: str, expected: BatchInfo) -> None:
    assert normalize_batch(raw_batch) == expected
