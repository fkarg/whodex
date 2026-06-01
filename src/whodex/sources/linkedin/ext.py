"""LinkedIn browser-extension PUSH source connector (P1f-2).

Receives payloads pushed by the LinkedIn browser extension and maps them to
canonical field observations.

Skipped payload keys (with rationale):
- ``location``: no scalar location canonical exists in the field registry;
  ``person.lives`` is a REF (entity reference), not a raw scalar string.
- ``headline``:  no fitting canonical field in the registry.
"""

from __future__ import annotations

from whodex.domain.enums import Capability
from whodex.domain.events import ObservationDraft, RawRecord
from whodex.sources.base import FieldMap, FieldSpec, apply_map

__all__ = ["LinkedInExtSource"]

# id must match the trust table key "linkedin_ext" so that source_kind → trust
# resolves to 50 at projection time (DEFAULT_TRUST["linkedin_ext"] == 50).
_ID = "linkedin_ext"

_MAP: list[FieldMap] = [
    FieldMap("name", "name.full"),
    FieldMap("title", "job.title"),
    FieldMap("company", "job.org"),
    FieldMap("linkedin_url", "linkedin.url"),
    # "location" → skipped: person.lives is a REF; no scalar location canonical exists.
    # "headline"  → skipped: no fitting canonical field.
]


class LinkedInExtSource:
    """PUSH source: receives LinkedIn extension payloads and normalises them."""

    id: str = _ID
    capabilities: Capability = Capability.PUSH
    identity_keys: tuple[str, ...] = ("linkedin_url",)
    provides: tuple[FieldSpec, ...] = (
        FieldSpec(canonical="job.title", freshness_ttl_days=90),
        FieldSpec(canonical="job.org"),
    )

    def normalize(self, record: RawRecord) -> list[ObservationDraft]:
        """Map extension payload fields to canonical ObservationDrafts.

        Empty/missing values are silently skipped (skip_if_empty=True default).
        """
        drafts = apply_map(record, _MAP)
        # apply_map skips None; also drop empty strings.
        return [d for d in drafts if not (isinstance(d.value, str) and not d.value.strip())]
