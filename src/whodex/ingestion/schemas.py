"""Wire schemas for the ingestion HTTP API."""

from __future__ import annotations

from pydantic import BaseModel

from whodex.domain.events import RawRecord

__all__ = ["IngestRequest", "IngestResponse"]


class IngestRequest(BaseModel):
    """Body for POST /ingest."""

    records: list[RawRecord]


class IngestResponse(BaseModel):
    """Summary returned after a successful POST /ingest."""

    accepted: int
    changes: int
    conflicts: int
