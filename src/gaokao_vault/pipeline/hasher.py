from __future__ import annotations

import hashlib
import json

from gaokao_vault.constants import META_FIELDS


def compute_content_hash(item: dict, exclude_fields: set[str] | None = None) -> str:
    excludes = META_FIELDS | (exclude_fields or set())
    business_data = {k: v for k, v in sorted(item.items()) if k not in excludes}
    canonical = json.dumps(business_data, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
