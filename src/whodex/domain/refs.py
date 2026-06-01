from __future__ import annotations

import re

from pydantic import BaseModel

_WIKILINK = re.compile(r"^\[\[(?P<target>[^|\]]+?)(?:\|(?P<label>[^\]]+))?\]\]$")


class EntityRef(BaseModel):
    entity_id: str | None = None
    target_path: str | None = None
    label: str | None = None
    raw: str
    resolution: str = "unresolved"  # resolved|ambiguous|missing|placeholder|unresolved

    @classmethod
    def parse(cls, raw: str) -> EntityRef:
        raw = raw.strip()
        m = _WIKILINK.match(raw)
        if m:
            target = m.group("target").strip()
            label = (m.group("label") or target.split("/")[-1]).strip()
            return cls(target_path=target, label=label, raw=raw)
        return cls(target_path=None, label=raw, raw=raw)
