"""Canonical, timezone-normalized hashes for policy evidence across processes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel


def canonical_json(value: Any) -> str:
    def normalize(item: Any) -> Any:
        if isinstance(item, BaseModel):
            return normalize(item.model_dump(mode="python"))
        if is_dataclass(item) and not isinstance(item, type):
            return normalize(asdict(item))
        if isinstance(item, datetime):
            if item.utcoffset() is None:
                raise ValueError("aware evidence time required")
            return item.astimezone(UTC).isoformat()
        if isinstance(item, Enum):
            return normalize(item.value)
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise ValueError("string evidence keys required")
            return {key: normalize(val) for key, val in item.items()}
        if isinstance(item, (set, frozenset)):
            return sorted((normalize(val) for val in item), key=lambda val: json.dumps(val, sort_keys=True))
        if isinstance(item, (tuple, list)):
            return [normalize(val) for val in item]
        return item

    return json.dumps(normalize(value), sort_keys=True, allow_nan=False, separators=(",", ":"))


def evidence_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()
