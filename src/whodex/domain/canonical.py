from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from whodex.domain.enums import ObsOp

_WS = re.compile(r"\s+")
_LOWER_FIELDS = {"email", "linkedin.url"}


def canonicalize(field: str, value: Any) -> Any:
    """Normalize a value so cosmetic differences are not treated as changes (§6.4)."""
    if isinstance(value, str):
        out = _WS.sub(" ", value).strip()
        if field in _LOWER_FIELDS:
            out = out.lower()
        return out
    if isinstance(value, list):
        return [canonicalize(field, v) for v in value]
    return value


def value_hash(field: str, op: ObsOp, value: Any) -> str:
    payload = json.dumps(
        {"field": field, "op": op.value, "value": canonicalize(field, value)},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()
