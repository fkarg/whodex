# whodex Phase 1e — Google Contacts connector (OAuth)

> REQUIRED SUB-SKILL: superpowers:subagent-driven-development. **Testing law (AGENTS §10):** behavior/invariants via public interfaces; HTTP mocked with `respx` (no live calls); no internals. Controller runs an INDEPENDENT full-gate checkpoint after every task.

**Goal:** pull real contacts from the Google People API into the same funnel, fully testable without live credentials (HTTP via an injected `httpx.Client`, OAuth token via an injected provider; `respx` mocks the API).

**External dependency (user supplies at deploy):** a Google Cloud OAuth client (Desktop) + consent screen set to Production/Personal-Use (avoids 7-day refresh-token expiry — DESIGN O3). The OAuth flow lives in a thin helper exercised manually; CI never calls Google.

## Scope
In: deps (`httpx` → main, `google-auth`, `google-auth-oauthlib`); an OAuth token helper (load client config + refresh token from env → access token); `GoogleContacts` PULL source calling `people.connections.list` via injected `httpx.Client` + token provider, mapping to drafts; `nextSyncToken` persistence + incremental + `EXPIRED_SYNC_TOKEN` full-resync; `respx` + `SourceContract` tests; optional wiring when creds present.
Out: live OAuth in CI; contact-group/photo sync; write-back to Google.

## Invariants / behaviors (the tests, `respx`-mocked)
- **GG1:** an initial `connections.list` response → the expected `ObservationDraft`s per contact (names→name.full, emails→email, phones→phone, organizations.title→job.title, .name→job.org); `metadata...updateTime → observed_at`. Identity keys `("google_resource","email")`.
- **GG2:** pagination — a multi-page response (`nextPageToken`) is fully consumed.
- **GG3:** incremental — after an initial sync stores `nextSyncToken`, the next `fetch(since)` sends `syncToken=...` and only processes returned (changed) contacts.
- **GG4:** `EXPIRED_SYNC_TOKEN` (HTTP 400 with that status) → the source clears the token and does a full resync (no crash).
- **GG5:** passes the shared `SourceContract`.
- No live network in any test (respx asserts mocked routes).

## Tasks

### Task 1: deps + OAuth token helper
Move `httpx` to `[project].dependencies`; add `google-auth`, `google-auth-oauthlib` to deps; add `respx` to `[dependency-groups].dev`. `uv sync`. `sources/google/auth.py`: `GoogleTokenProvider` — given client id/secret + refresh token (from `pydantic-settings`/env), returns a valid access token (refreshing via `google.oauth2.credentials.Credentials`). Keep it thin; unit-test only the env-config parsing / a fake-credentials path (no live call). Note the manual OAuth bootstrap (`whodex google login`-style) as a follow-up/manual step. Gate checkpoint.

### Task 2: GoogleContacts PULL source (GG1/GG2/GG5)
`sources/google/contacts.py`: `GoogleContacts(http: httpx.Client, token_provider: Callable[[], str], *, sync_token_store=None)` — `id="google_contacts"` (trust 60), `identity_keys=("google_resource","email")`. `fetch(since)`: GET `https://people.googleapis.com/v1/people/me/connections?personFields=names,emailAddresses,phoneNumbers,organizations,metadata&pageSize=...&requestSyncToken=true` with `Authorization: Bearer <token>`; follow `nextPageToken`; yield one `RawRecord` per `person` (identity from `resourceName`→google_resource + first email; payload = the person dict; `observed_at` from `metadata.sources[].updateTime` else now-injected). `normalize` maps via `apply_map`/`FieldMap` on the People payload shape. respx-mocked tests for GG1 (mapping), GG2 (pagination), GG5 (SourceContract). Inject the clock for `observed_at` fallback. Gate checkpoint.

### Task 3: sync-token persistence + incremental + expired (GG3/GG4)
A tiny `SyncTokenStore` (or reuse a small KV: store `nextSyncToken` keyed by source id) — rows+store mem+sqlite, or persist in the existing source config. `fetch(since)`: if a stored token exists, send `syncToken=`; on success, persist the new `nextSyncToken` from the final page. On HTTP 400 with `status == "EXPIRED_SYNC_TOKEN"` (or the documented error body), clear the token and retry full. respx tests: GG3 (second fetch sends syncToken; processes only returned), GG4 (expired → full resync, token cleared, no crash). Gate checkpoint.

### Task 4: wiring (optional) + e2e (mocked) + gate
`build_app`/config: when Google creds are present (env), add a `GoogleContacts` source (real `httpx.Client` + `GoogleTokenProvider`); absent → skip silently. `pydantic-settings` reads `WHODEX_GOOGLE_*`. e2e `tests/test_e2e_phase1e.py` (respx-mocked): a Google connections response flows through `run_sync` → person entities exist; a Google value LOSES to an Obsidian value for the same field by trust precedence (60 < 80) — assert the projected winner. Full gate + coverage. Independent gate verify before merge. Document (in the plan/AGENTS) exactly what the user must create in Google Cloud + which env vars to set.

## Self-review: no live network (respx); connector logic (mapping/pagination/sync-token/expired) fully tested; OAuth flow isolated + manual; Google data correctly loses to Obsidian/manual by trust; layering preserved.
