# whodex Phase 1 (MVP) — Master Plan & Increment Roadmap

> **What this is:** Phase 1 of DESIGN §13 spans several independent subsystems (Obsidian connector, graph, Google, ingestion API, TUI, Firefox extension). Per the writing-plans scope rule, it is decomposed into **sequenced, individually-shippable increments**. This document is the increment-level plan: goal, design decisions, interfaces, dependencies, test strategy, acceptance, and deferrals for each. **Each increment gets its own task-level code plan** (`docs/superpowers/plans/2026-06-01-phase-1<x>-*.md`) authored just before it is executed — as 1a (engine) already did. Architecture authority remains `docs/DESIGN.md`; working conventions remain `AGENTS.md`.
>
> **Definition of "Phase 1 done" (DESIGN §13):** the daily loop works on real data — ranked reach-out queue, "I contacted them", per-field freshness, "what changed", Obsidian as a bidirectional source of truth, ≥1 real connector, in a usable TUI; one-shot `sync` and a daemon both work.

## Status of increments

| # | Increment | Status | Depends on |
|---|-----------|--------|-----------|
| 1a | Engine (prioritization/freshness/reminders) | ✅ **done** | Phase 0 |
| 1b | Durable core + Obsidian **read** connector | next | 1a |
| 1c | Graph projection + repair suggestions + change/reminder persistence | | 1b |
| 1d | Obsidian **write-back** (anti-clobber) | | 1b (1c helpful) |
| 1e | Google Contacts connector (OAuth) | | 1b |
| 1f | Ingestion API (FastAPI) + tokens + LinkedIn-ext push | | 1b |
| 1g | TUI (Textual, 5 screens) + notification dispatch + `serve` daemon + TOML config | | 1c, 1d (reads), 1f (optional) |
| 1h | Firefox WebExtension (MV3) | | 1f |

**Dependency graph:** `1a → 1b → {1c, 1d, 1e, 1f}`; `1g` needs `1c`+`1d`(read side); `1h` needs `1f`. 1c/1d/1e/1f are largely parallel after 1b but we execute sequentially (one branch at a time). Recommended order: **1b → 1c → 1d → 1f → 1e → 1g → 1h** (defer Google's external-credential friction; bring the ingestion API up before Google so the Firefox path has a target).

## Cross-cutting decisions (settled here, applied by every increment)

1. **Durability becomes real in 1b.** Phase 0's CLI wires *in-memory* stores and an in-memory `IdentityResolver`, so nothing survives across `whodex sync` invocations. 1b switches the composition root to **SQLite-backed** `LedgerStore` + `ProjectionStore`, and makes identity resolution **store-backed** (persist `Entity` + `EntityIdentifier` rows; resolve by querying them) so repeated runs resolve to the same entity. This is the single most important non-obvious requirement and is a prerequisite for every connector.
2. **JSONL ledger mirror** (DESIGN §1) lands in 1b alongside durable SQLite: after each successful append, mirror events to `vault/.whodex/events/*.jsonl` for recovery.
3. **Secrets via env only** (never committed): Google OAuth client + refresh token, ingestion bearer token. `pydantic-settings` + TOML for non-secret config (vault path, cadence tiers, trust ranks, freshness TTLs, notifier toggles) — the TOML config object is introduced in 1b (minimal) and grown per increment.
4. **`now`/`IdFactory` stay injected** everywhere; new pure logic keeps the Phase-0 purity + import-linter layering. Connectors emit `ObservationDraft`/`RawRecord`; only the hub finalizes.
5. **Field registry grows additively** in `domain/fields.py` as connectors need new canonical fields; the flat-vs-`kind.field` convention from DESIGN stays.
6. **Every connector passes the `SourceContract` suite**; every store-backed component is exercised against the existing store contract.
7. **TDD + per-increment review + merge to `main`** (the established loop). No `Co-Authored-By` trailers; focused commits.

---

## Increment 1b — Durable core + Obsidian read connector

**Goal:** `whodex sync` reads the real `../people-network` vault into durable, typed `Entity`s + observations that survive across runs, and the priority queue reflects real people. No write-back, no edges yet.

**Key design decisions:**
- **Store-backed identity resolution.** Replace the in-memory `IdentityResolver` with one that persists `Entity` rows + `EntityIdentifier` rows (new SQLModel rows + mappers) and resolves by querying them; strong keys per DESIGN §7 (`vault_uid`, `linkedin_url`, `google_resource`, `email`, `phone`) plus vault keys (`vault_path`, `canonical_name`). New `Entity`/`EntityIdentifier` row classes + a `system entity_create` UserAction on first sight (so replay preserves IDs).
- **SQLite-backed `ProjectionStore`** (recompute-on-read for now, O5): persist the projected `EntityState` (or recompute from the durable ledger each run — pick recompute-from-ledger to stay simple and append-only-faithful; cache table optional). Wire SQLite ledger + projection into the composition root (`config/settings.py`) behind a `--db PATH` / config; keep in-memory wiring for tests.
- **Vault parsing** (`vault/` package): `markdown.py` splits frontmatter (via `ruamel.yaml`, byte-preserving body) and parses values; `EntityRef.parse` for wikilink-valued fields. `fs.py` scans `*.md`. Routing (folder + `type` + tags → `EntityKind`/subtype) per DESIGN §2.3 table.
- **`ObsidianSource`** (`sources/obsidian.py`, `Capability.PULL`): `fetch(since)` yields one `RawRecord` per note (identity from `whodex.uid`/path/links/emails; payload = mapped frontmatter incl. wikilink raws); `normalize` maps to `ObservationDraft`s using the people-network vocabulary (`organisations`/`lives`/`city`/`country`/`last contact`/`next contact`/`tags`/`aliases` + the new enrichment keys). `last contact` → an `Interaction` (decide: emit interactions from the connector, or a dedicated path — likely the hub gains an interaction-ingest path; specify in the task plan).
- **`observed_at`** from `git log -1 --format=%cI <file>` when the vault is a git repo, else mtime.

**Files (new/changed):** `vault/interface.py`, `vault/fs.py`, `vault/markdown.py`; `sources/obsidian.py`; `store/rows.py`+`mappers.py` (Entity/EntityIdentifier rows); `store/sqlite.py` (+ProjectionStore, JSONL mirror); `sync/hub.py` (store-backed identity; interaction ingest path); `config/settings.py` (SQLite wiring, vault path, `--vault`/`--db`); `domain/fields.py` (any new fields).

**Test strategy:** unit — markdown round-trip parse (frontmatter/body/wikilinks), routing table, normalize mapping; contract — `ObsidianSource` passes `SourceContract`; integration — temp vault dir → `run_sync` → durable SQLite → re-run resolves same entities (no duplicates); a **smoke test against a copied fixture subset of `../people-network`**; store-backed identity contract.

**Done when:** `whodex sync --vault <copy-of-people-network>` ingests People notes into durable SQLite, re-running creates no duplicate entities, `whodex queue` ranks real people with why-now, and replaying the ledger reproduces identical state. Gate green.

**Defers:** edges/graph (1c), write-back (1d), Organisation/Location/Event richness beyond entity creation (1c).

**Rough tasks (~8–10):** Entity/EntityIdentifier rows+mappers; store-backed IdentityResolver + contract; SQLite ProjectionStore + JSONL mirror + composition wiring; markdown frontmatter/body/wikilink parser; vault scanner; routing; ObsidianSource.normalize + SourceContract; interaction-ingest path (`last contact`); CLI `--vault`/`--db`; integration + fixture smoke.

---

## Increment 1c — Graph projection + repair suggestions + change/reminder persistence

**Goal:** turn `REF`/`MULTI_REF` observations into the `Edge` graph, answer contact-point queries, surface `GraphRepairSuggestion`s, and **persist** `Change`/`ConflictSuggestion`/`Reminder` rows so "what changed" and reminders survive runs (and `event_boost` can finally be wired).

**Key design decisions:**
- **Edge projection** (extend `projection/`): `person.organisations → member_of`, `person.lives/city/country → lives_in`, `org.location → located_in`, `org.parent → part_of`, `event.location → hosted_at`, `event.organizer → organized_by`, event participants → `attended`; bitemporal `valid_from/valid_to`; `same_org/same_city/colleague` derived. Persist `Edge` rows (new rows+mappers). `EntityRef` resolution to `entity_id` via the identity index; unresolved → repair.
- **GraphRepairSuggestion rules** (DESIGN §5.2 table): `missing_inverse`, `unresolved_ref`, `placeholder_ref`, `broken_wikilink`, `duplicate_entity`, `missing_note`, `stale_membership`, `template_drift`; fingerprinted + batchable; **read-only** here (applying repairs = write side, 1d).
- **Persist derived rows**: `Change`/`ConflictSuggestion`/`GraphRepairSuggestion`/`Reminder` row classes + mappers; the projector/engine results are written each run with status caches; `UserAction` (ack/dismiss/snooze) overlays. Wire `event_boost` in scoring from open (unacked) notable Changes.
- **Contact-point queries** (`engine/queue.py` or new `engine/graph.py`): `people_at(entity_id)`, `contact_points(entity_id)`, `graph_repairs()`.

**Files:** `projection/edges.py` (or extend `project.py`), `projection/repairs.py`; `store/rows.py`+`mappers.py` (Edge/Change/ConflictSuggestion/GraphRepairSuggestion/Reminder); `engine/graph.py`; `engine/scoring.py` (wire event_boost); `sync/engine.py` (persist derived).

**Test strategy:** unit — edge derivation per field type, repair-rule detection + fingerprint stability, event_boost from open changes; integration — vault with a person→org link missing the inverse employee → one `missing_inverse` suggestion, idempotent on re-run; query tests.

**Done when:** the people-network graph (people↔orgs↔locations↔events) materializes as edges; "who do I know at Kolai?" / "who is in Frankfurt?" answer; missing inverses + unresolved scalars surface as deduped repair suggestions; a notable job change bumps priority via `event_boost`; re-runs don't duplicate suggestions. Gate green.

**Defers:** applying repairs / writing the inverse (1d); centrality (Phase 5).

**Rough tasks (~8–12).**

---

## Increment 1d — Obsidian write-back (anti-clobber)

**Goal:** the riskiest piece — propagate learned/enriched facts and applied graph repairs back into frontmatter **without ever clobbering** hand edits; keep the body byte-identical; idempotent (no-op re-write = clean git diff).

**Key design decisions (DESIGN §3.3):** three-way merge (`base`=last_frontmatter_seen, `theirs`=current file, `ours`=projected) per managed field; `VaultFileState` row (content hash + last_written_hash) for out-of-band-edit detection + echo suppression; **opt-in `managed_fields`**; write-back limited to enrichment scalars first (`linkedin`/`emails`/`phones`/`job_title`) + `whodex.uid` injection; `last contact` write-back on TUI log; applying a `GraphRepairSuggestion` is a `UserAction` → minimal frontmatter/body edit touching only the proposed field/block; `%% whodex:edges %%` block last-write-wins. `watchdog` debounced watch for daemon mode. `ruamel.yaml` round-trip fidelity.

**Files:** `vault/writeback.py`, `vault/watch.py`; `store/rows.py` (VaultFileState); `sources/obsidian.py` (`WRITEBACK`+`WATCH` capabilities); `sync/engine.py` (write phase).

**Test strategy (most paranoid, L4):** `parse(render(note)) == note`; unknown keys + body survive; out-of-band edit → ingested as obsidian observation, wins by precedence, not clobbered; idempotent write → byte-identical; uid injected once; applying a repair edits only the targeted field/block; echo suppression (our write not re-ingested). Property test on round-trip.

**Done when:** `whodex sync` writes enrichment back without clobbering a hand-edited field (hand edit wins; lower-trust disagreement → conflict suggestion), produces byte-identical files on no-op re-run, injects `whodex.uid` once, and can apply a missing-inverse repair on request. Gate green; validated against a copy of the real vault.

**Rough tasks (~8–12).** Highest risk → most review.

---

## Increment 1e — Google Contacts connector (OAuth)

**Goal:** pull real contacts from Google People API into the same funnel.

**External dependency (needs you):** a Google Cloud OAuth **client ID/secret** (Desktop app), consent screen set to **Production / Personal-Use** (avoids 7-day refresh-token expiry — O3); first-run does the OAuth flow and stores the refresh token via env/secure file (never committed). I'll flag exactly what you need to create.

**Key design decisions (DESIGN §4.7):** `GoogleContacts` (`Capability.PULL`), scope `contacts.readonly`; `people.connections.list` with `personFields=names,emailAddresses,phoneNumbers,organizations,addresses,urls,metadata`; `requestSyncToken=true` → persist `nextSyncToken` for incremental sync; `EXPIRED_SYNC_TOKEN` → full resync; map `metadata.sources[].updateTime → observed_at`; identity keys `("google_resource", "email")`. HTTP injected (`httpx`) so tests use `respx` (no live calls).

**Files:** `sources/google.py`; auth helper (`sources/google_auth.py`); config (client creds via env, token store path); `domain/fields.py` (any new fields).

**Test strategy:** `respx`-mocked `connections.list` (initial + incremental + expired-token paths) → drafts; `SourceContract`; sync-token persistence test. No live API in CI.

**Done when:** with creds present, `whodex sync` merges Google contacts with vault entities by email (identity resolution), incremental sync uses the stored token, and Google data loses to Obsidian/manual by trust precedence. Gate green (mocked).

**Rough tasks (~6–8).**

---

## Increment 1f — Ingestion API (FastAPI) + tokens + LinkedIn-ext push

**Goal:** the universal push funnel so the Firefox extension (and webhooks/RSS pollers) can POST normalized records.

**Key design decisions (DESIGN §4.4, §9.4):** `ingestion/app.py` `create_app(deps)` + `routes.py` + `schemas.py` (API request/response envelopes; reuse domain `RawRecord` as the item type); `POST /ingest` (batch, `202`), token-gated (`Authorization: Bearer`, validated against a small revocable token table — new rows); `whodex token issue --label <x>` CLI mints/stores a token (env/db). `linkedin_ext` registered as a `PUSH` source whose `normalize` maps the extension payload `{name,headline,title,company,location,linkedin_url}` → drafts. The API is a thin caller of the same `hub.ingest`.

**Files:** `ingestion/app.py`/`routes.py`/`schemas.py`; `sources/linkedin/ext.py`; token rows+mappers; `cli/main.py` (`token` command); `config` (token store).

**Test strategy:** FastAPI `TestClient` over in-memory SQLite — valid→202+appended, malformed→422, unknown source→422, auth-reject→401, duplicate POST idempotent, batch; `linkedin_ext` `SourceContract`.

**Done when:** a token-authenticated `POST /ingest` with a LinkedIn-ext payload creates/updates the right entity through the same projection path; unmatched captures quarantine; bad/no token rejected. Gate green.

**Rough tasks (~6–8).**

---

## Increment 1g — TUI + notification dispatch + `serve` daemon + TOML config

**Goal:** the usable day-to-day surface and the always-on mode; one-shot `sync` and daemon share code.

**Key design decisions (DESIGN §9):** a headless **facade** (`Whodex` class) exposing the read/write ops the TUI calls (priority_queue, contact/entity detail, timeline, review/maintenance queue, people_at, contact_points, graph_repairs, log_interaction, pin/snooze/dismiss/ack, apply_graph_repair, set_cadence) — pure orchestration over engine/store, no UI deps. `Notifier` protocol + `NotificationDispatcher` + `TUINotifier`; notifications append-only `PENDING` → dispatched (so one-shot and daemon are the same mechanism). Textual app with the 5 screens (§9.3): Priority Queue, Contact Detail (+freshness dots), Contact Points, Review/Maintenance Queue, Log Interaction modal. `whodex serve` = `run_sync`+drain+dispatch on a loop + (optional) FastAPI + `watchdog`; systemd-timer-compatible. TOML config grown to full (paths, tokens, cadence tiers, trust, freshness TTLs, notifier toggles).

**Files:** `app/facade.py` (or `sync/facade.py`), `notifiers/interface.py`+`impls.py`, `tui/*` (screens), `cli/main.py` (`tui`, `serve`), `config/settings.py` (full TOML).

**Test strategy:** facade unit/integration (all logic headless); Textual `Pilot` smoke + `pytest-textual-snapshot` on 2 key screens; dispatcher idempotency (no double-send); `serve` one-tick test.

**Done when:** `whodex tui` shows a ranked queue with why-now; `l` logs an interaction (resets clock, writes `last contact` back), `s`/`p` work; contact-point + maintenance screens render; `whodex serve` runs the loop. Gate green.

**Rough tasks (~10–14).**

---

## Increment 1h — Firefox WebExtension (MV3)

**Goal:** passive LinkedIn capture during real browsing → POST to the 1f ingestion endpoint.

**Key design decisions (DESIGN §9.4):** separate JS/TS codebase under `extension/`; MV3 event page; content script on `*.linkedin.com/in/*` extracts rendered DOM (name/headline/title/company/location/url), debounced, one profile → one `RawRecord`; background page does the cross-origin `fetch` POST (HTTPS to the VPS endpoint); bearer token in `browser.storage.local` from options page. Fully separable from core.

**Test strategy:** JS unit tests for the extractor against saved profile HTML fixtures; manual end-to-end against a running ingestion API (documented). Not in the Python CI gate.

**Done when:** viewing a LinkedIn profile posts a valid `RawRecord` that the ingestion API ingests into the right entity; token configurable; capture is passive-only. (Manual acceptance.)

**Rough tasks (~5–7).** ToS risk is user-accepted (DESIGN §14).

---

## Risks & checkpoints (Phase-1-wide)

- **Durable identity + projection (1b)** is the foundational risk — get it right or every connector duplicates entities. Heaviest review.
- **Obsidian write-back (1d)** is the highest-bug-risk code — most paranoid tests, validate on a *copy* of the real vault before trusting the live one.
- **Google (1e)** and **Firefox (1h)** carry external dependencies (creds, browser) — I'll surface exactly what you must provide; both are testable/mockable up to that boundary.
- **Re-review the field registry** when 1b/1c/1e add fields — keep the flat-vs-`kind.field` convention coherent (the open Phase-0 note).
- Each increment ends green on `main` and updates `AGENTS.md` §8/§9; we checkpoint between increments so you can re-sequence.
