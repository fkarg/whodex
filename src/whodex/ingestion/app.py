"""FastAPI ingestion application (P1f-4).

Provides a thin HTTP wrapper around the shared ingestion pipeline.
Bearer-token authentication is applied to POST /ingest (P1f-4).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Annotated, Protocol

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from whodex.domain.clock import Clock, SystemClock
from whodex.domain.ids import IdFactory, UlidIdFactory
from whodex.ingestion.schemas import IngestRequest, IngestResponse
from whodex.sources.base import PullSource, Source
from whodex.store.interfaces import (
    DerivedStore,
    EdgeStore,
    EntityStore,
    LedgerStore,
    ProjectionStore,
    TokenStore,
)
from whodex.sync.hub import IngestionHub
from whodex.sync.ingest import ingest_one, reproject_and_persist

__all__ = ["AppLike", "create_app", "app_from"]

_bearer_scheme = HTTPBearer(auto_error=False)


class AppLike(Protocol):
    """Structural protocol matching ``whodex.config.settings.App``.

    Defined here (in the ``ingestion`` layer) so that ``ingestion`` does not need
    to import ``whodex.config`` — a higher layer — directly.
    """

    hub: IngestionHub
    ledger: LedgerStore
    projection: ProjectionStore
    entities: EntityStore
    edges: EdgeStore
    derived: DerivedStore
    trust: dict[str, int]
    clock: Clock
    sources: list[PullSource]
    tokens: TokenStore


def _make_require_token(
    validate: Callable[[str], bool],
) -> Callable[[HTTPAuthorizationCredentials | None], None]:
    """Return a FastAPI dependency that enforces Bearer-token auth.

    ``validate(token) -> bool`` decides whether a presented bearer token is valid
    (typically ``TokenStore.validate``).
    """

    def require_token(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    ) -> None:
        if credentials is None or not validate(credentials.credentials):
            raise HTTPException(status_code=401, detail="Invalid or missing bearer token")

    return require_token


def create_app(
    *,
    hub: IngestionHub,
    ledger: LedgerStore,
    projection: ProjectionStore,
    sources: Mapping[str, Source],
    trust: Mapping[str, int],
    token_validator: Callable[[str], bool],
    clock: Clock | None = None,
    entities: EntityStore | None = None,
    edge_store: EdgeStore | None = None,
    derived_store: DerivedStore | None = None,
    ids: IdFactory | None = None,
) -> FastAPI:
    """Construct the FastAPI ingestion app wired to the provided dependencies.

    ``sources`` is a registry mapping source-id strings to Source instances.
    Only sources present in this registry may be pushed via the API; unknown
    sources produce a 422 response.

    ``token_validator`` is a :class:`~whodex.store.interfaces.TokenStore` (or any
    ``Callable[[str], bool]``) used to authenticate ``POST /ingest`` requests.
    """
    _clock = clock or SystemClock()
    _ids = ids or UlidIdFactory()
    require_token = _make_require_token(token_validator)
    app = FastAPI(title="whodex ingestion API", version="1f-4")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post(
        "/ingest",
        response_model=IngestResponse,
        status_code=202,
        dependencies=[Depends(require_token)],
    )
    def ingest(body: IngestRequest) -> IngestResponse:
        total_obs = 0
        for record in body.records:
            source = sources.get(record.source)
            if source is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"Unknown source: {record.source!r}. "
                    f"Accepted sources: {sorted(sources)}",
                )
            source_run_id = f"API-{_ids.new()}"
            result = ingest_one(
                source,
                record,
                hub=hub,
                ledger=ledger,
                source_run_id=source_run_id,
            )
            total_obs += len(result.observations)

        now: datetime = _clock.now()
        changes, conflicts = reproject_and_persist(
            ledger=ledger,
            projection=projection,
            hub=hub,
            trust=trust,
            now=now,
            entities=entities,
            edge_store=edge_store,
            derived_store=derived_store,
            ids=_ids,
        )
        return IngestResponse(accepted=len(body.records), changes=changes, conflicts=conflicts)

    return app


def app_from(app_obj: AppLike) -> FastAPI:
    """Build the ingestion FastAPI app from a whodex ``App`` config object.

    Accepts anything satisfying ``AppLike`` (structurally matching
    ``whodex.config.settings.App``) so that this module does not need to
    import ``whodex.config`` — a higher layer — directly.
    """
    from whodex.sources.linkedin.ext import LinkedInExtSource

    # Build a registry of PUSH-capable sources.  Add more push sources here as
    # they are implemented in later phases.
    push_sources: dict[str, Source] = {
        LinkedInExtSource.id: LinkedInExtSource(),
    }

    return create_app(
        hub=app_obj.hub,
        ledger=app_obj.ledger,
        projection=app_obj.projection,
        sources=push_sources,
        trust=app_obj.trust,
        token_validator=app_obj.tokens.validate,
        clock=app_obj.clock,
        entities=app_obj.entities,
        edge_store=app_obj.edges,
        derived_store=app_obj.derived,
    )
