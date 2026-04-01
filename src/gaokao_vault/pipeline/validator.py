from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)


def validate_item(model_class: type[BaseModel], data: dict[str, Any]) -> dict[str, Any] | None:
    try:
        instance = model_class.model_validate(data)
        return instance.model_dump()
    except ValidationError as e:
        logger.warning("Validation failed for %s: %s", model_class.__name__, e)
        return None
