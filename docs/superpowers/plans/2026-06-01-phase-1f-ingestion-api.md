# whodex Phase 1f — Ingestion API (FastAPI) + tokens + LinkedIn-ext push

> REQUIRED SUB-SKILL: superpowers:subagent-driven-development. **Testing law (AGENTS §10):** behavior/invariants via public interfaces (here: the HTTP API + FastAPI `TestClient`); no internals. Controller runs an INDEPENDENT full-gate checkpoint after every task.

**Goal:** a token-gated `POST /ingest` endpoint — the universal push funnel — so the Firefox extension (1h), webhooks, and RSS pollers can submit normalized records into the same `hub.ingest` pipeline. Plus a `linkedin_ext` PUSH source and `whodex token issue`.

**Builds on:** 1b durable hub/stores, `RawRecord`, `IngestionHub.ingest`.

## Scope
In: revocable bearer tokens (rows + issue/validate + `whodex token issue`); FastAPI `create_app(deps)` with `POST /ingest` (token-gated, batch, 202); the `linkedin_ext` PUSH source (maps extension payload → drafts); wiring `/ingest` to the durable hub; integration tests via `TestClient`.
Out (later): the Firefox extension itself (1h); webhook/RSS pollers; rate limiting; HTTPS/TLS (deployment concern).

## Invariants / behaviors (the tests, via `TestClient`)
- **A1:** valid token + valid `RawRecord` batch → `202` and the records are ingested (entity created/updated through the same projection path as `whodex sync`).
- **A2:** missing/invalid token → `401`; revoked token → `401`.
- **A3:** unknown `source` → `422`; malformed body → `422`.
- **A4:** idempotent — POSTing the same batch twice doesn't duplicate entities (same durable-identity invariant as sync).
- **A5:** `linkedin_ext` passes the shared `SourceContract`; its `normalize` maps `{name,headline,title,company,location,linkedin_url}` → the expected canonical drafts.
- **A6:** `whodex token issue --label X` prints a token once; that token authenticates a subsequent `/ingest`; a different/garbage token does not.

## Tasks

### Task 1: revocable tokens + `whodex token issue`
`TokenRow(id, token_hash, label, created_at, revoked)` + store (`TokenStore`: `issue(label, *, now, secret) -> str` returns the plaintext token once, stores only its sha256 hash; `validate(token) -> bool`; `revoke(id)`). In-memory + SQLite under a contract. `whodex token issue --label <x> --db <file>` mints + prints the token (once) and persists the hash. Behavioral: issued token validates; tampered/garbage doesn't; revoked doesn't; only the hash is stored (never the plaintext). Gate checkpoint.

### Task 2: `linkedin_ext` PUSH source (A5)
`sources/linkedin/__init__.py` (+ `ext.py`): `LinkedInExtSource` (`Capability.PUSH`), `id="linkedin"` (trust `linkedin_ext`=50), `identity_keys=("linkedin_url",)`, `normalize(record)` maps payload `{name→name.full, title→job.title, company→job.org, location→? , headline→?, linkedin_url→linkedin.url}` to `ObservationDraft`s (map what's in the field registry; add registry fields only if needed). Passes the shared `SourceContract`. Behavioral mapping tests. Gate checkpoint.

### Task 3: FastAPI app + `POST /ingest` (A1/A3)
`ingestion/app.py` `create_app(*, hub, registry, token_validator, ledger, ...)` returning a FastAPI app; `ingestion/schemas.py` (request envelope: `list[RawRecord]` or `{records: [...]}` — reuse domain `RawRecord` as the item; response `{accepted, changes, conflicts}`); `ingestion/routes.py` `POST /ingest` → for each record `hub.ingest(...)` (+ ledger append + projection persist, mirroring `run_sync`'s per-record path — factor a shared `ingest_records(...)` helper in `sync/` if cleaner). Unknown source → 422; malformed → 422 (pydantic). Token dependency added in Task 4. Tests via `TestClient` over an in-memory app. Gate checkpoint.

### Task 4: token gating + wiring (A2/A4/A6)
Add a `require_token` dependency (header `Authorization: Bearer <t>` → `token_validator.validate`); 401 on missing/invalid/revoked. Wire `create_app` deps from `build_app` (durable). `whodex serve` (if it exists) or a new minimal `whodex serve --db --vault` mounts the app (uvicorn) — OR defer running it to 1g and just expose `create_app`. Tests: A2 (401 paths), A4 (double-POST idempotent → entity count stable), A6 (issued token authenticates end-to-end via TestClient). Gate checkpoint.

### Task 5: integration e2e + gate
`tests/test_e2e_phase1f.py`: end-to-end via `TestClient` over a durable (tmp-file db) app — issue a token, POST a `linkedin` RawRecord with a `linkedin_url`, get 202, then verify (via the store or a `whodex queue`) the person entity exists; POST again → no duplicate (A4); bad token → 401; unknown source → 422. Full gate + coverage. Independent gate verify before merge.

## Self-review: behavior via HTTP/TestClient; tokens store only hashes; /ingest reuses the exact hub pipeline (no divergent ingest path); idempotency = same durable-identity invariant; layering (`ingestion`→`domain`/`store`/`sync` via DI) preserved.
