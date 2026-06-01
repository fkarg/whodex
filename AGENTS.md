# AGENTS.md — whodex working guide

> **Living document.** This is the operational companion to `docs/DESIGN.md`. DESIGN.md is the
> architectural source of truth (the *what* and *why*); AGENTS.md is the *how we work* + *where we are*.
> **Keep it alive:** when a decision is made, append to the Decision Log (§9); when a phase task lands,
> tick it in Status (§8). If AGENTS.md and DESIGN.md disagree, DESIGN.md wins for architecture — fix
> AGENTS.md; for working conventions, AGENTS.md wins.

## 1. What this is

whodex is a single-user, local-first "people CRM" that tells you **who to reach out to, why now, and
what changed about them** — without owning your data. It is a supplemental layer over an Obsidian vault
that already works. Delete whodex and the vault + relationships survive intact.

**The central bet** (DESIGN §1): an append-only **event ledger** (three streams — `Observation`,
`Interaction`, `UserAction`) is the only thing the world writes to. The SQLite projection tables **and**
the Obsidian frontmatter are *caches* — deterministic pure folds over the ledger. The projection is a
typed **entity graph** (person / organisation / location / event) that mirrors the vault.

**Reference vault:** `../people-network` (`/home/pars/Coding/people-network`) is the user's real vault and
the canonical example of the note format whodex reads/writes/improves. Treat its templates and existing
notes as the contract — see §6.

## 2. Priority order (applies to every decision)

**modularity → testability → abstractions over shared concerns → simplification (YAGNI).**
When two designs tie, pick the simpler one and write down why.

## 3. Stack & tooling

- **Language/runtime:** Python (3.12+), `src/` layout, packaged with **`uv`** + **`hatchling`**, single `pyproject.toml`.
- **Core libs:** `pydantic` (domain models), `SQLModel`/SQLAlchemy (**only** in `store.sqlite`),
  `FastAPI` (ingestion API), `Typer` (CLI), `Textual` (TUI), `ruamel.yaml` (frontmatter round-trip),
  `httpx` (HTTP, injected), `watchdog` (vault watch), `rapidfuzz` (dedup suggestions), `python-ulid`.
- **Connectors:** `google-api-python-client` + `google-auth-oauthlib` (Google People API).
- **Quality gates (all must pass in CI):** `ruff check` + `ruff format --check`, `mypy --strict`
  (pydantic plugin), **`import-linter`** (dependency contracts, §5), `pytest` with coverage.
- **Tests:** `pytest` + markers `unit | integration | e2e | tui | property`; `respx` (HTTP),
  `syrupy` + `pytest-textual-snapshot` (snapshots), `hypothesis` (property), `pytest-asyncio`.
- **Config:** `pydantic-settings`, TOML + env. **Secrets/tokens via env only — never committed.**

## 4. Non-negotiable conventions

- **`domain` is pure.** pydantic + stdlib only. No ORM, no IO, no `datetime.now()`, no network.
- **Append-only ledger.** The store exposes no update/delete on ledger rows. Corrections are new events
  (`assert_absent` / a fresh `set` / a new `UserAction`).
- **Purity at the core.** `project()`, `score_contact()`, `staleness()`, identity resolution, and the
  precedence comparator are **pure functions** — `now`, IDs, and config are passed in, never read ambiently.
- **One funnel for ingress:** `producer → RawRecord → normalize → list[ObservationDraft] → hub → ledger
  → projection`. Connectors never mint IDs or resolve identity; the hub does (DESIGN §4.4).
- **IDs:** ULID strings. **Timestamps:** tz-aware UTC everywhere.
- **Determinism:** inject `Clock` and `IdFactory`. A flaky test is a seam bug, not a retry candidate.
- **Never clobber the vault.** Write-back obeys the three-way merge + echo-suppression invariant
  (DESIGN §3.3): *never overwrite a field whose current file value hasn't already been ingested as an
  observation.* The markdown body outside marked blocks is byte-preserved. Graph/inverse-link gaps are
  surfaced as `GraphRepairSuggestion`s and only written on an explicit `apply_graph_repair` action.
- **Every connector passes the `SourceContract` test suite** (DESIGN §12 L2). That suite is what makes
  "drop-in plugin, zero core changes" real — including idempotency (re-ingest ⇒ no fake changes).

## 5. Repo layout & dependency rule

Enforced by `import-linter`: **`domain` depends on nothing beyond pydantic/stdlib; SQLModel/SQLAlchemy live
only in `store.sqlite`; everything depends on `domain`; `tui`/`sources`/`ingestion`/`notifiers` never depend
on each other; no cycles.** `config` is the composition root (the only module allowed to import widely).
Full tree + per-module responsibilities: DESIGN §11.

```
src/whodex/
  domain/      pure models (Entity, EntityRef, events, EntityState/ContactProfileState,
               Change/ConflictSuggestion/GraphRepairSuggestion, Edge) + Clock/IdFactory + fields.py
  projection/  pure fold: events -> entity-graph state (+ Changes/Conflicts/GraphRepairs); conflict comparator
  engine/      pure: scoring · reminders · freshness · identity
  store/       persistence behind interfaces; SQLModel rows + mappers live HERE only
  sources/     connectors (google, obsidian, linkedin/*) — depend on domain only
  vault/       Obsidian FS + markdown round-trip (ruamel)
  ingestion/   FastAPI app; wire schemas (RawRecord) kept separate from domain
  sync/        orchestration; the ONLY place daemon vs one-shot differ
  notifiers/   Notifier protocol + sinks (TUI now; telegram/email later)
  enrich/      LATER-lane seam, stubbed now (NullEnricher)
  tui/         Textual app
  cli/         Typer entrypoints
  config/      pydantic-settings; composition root
```

## 6. Obsidian / vault contract

whodex **adopts the existing `../people-network` vocabulary** (no forced migration) and *enriches* sparse
notes. The vault is a typed graph, mirrored as whodex `Entity` nodes (DESIGN §2.3 / §3.1 / §5):

- `People/**/*.md` or `type: Person` → `Entity(kind=person)` + `ContactProfile` — the only kind that enters the reach-out queue.
- `Organisations/**/*.md`, `type: Organisation`, or `tags: [Organisation]` → `Entity(kind=organisation)` — a contact point ("who do I know at Kolai?"). `type` may be a subtype such as `Startup`.
- `Locations/**/*.md` or `type: Location|City|Country|Address` → `Entity(kind=location)` — a contact point ("who is in Frankfurt?").
- `Events/**/*.md` or `type: Event` → `Entity(kind=event)` — ties organizer/location/participants; participants → `Interaction`s.

Wikilinks parse into `EntityRef`s (canonical target path = identity, alias = display, `raw` for lossless
round-trip, `resolution` for resolved/ambiguous/missing/placeholder) and project into the `Edge` graph —
Phase 1 reads the graph you already drew. Bare wikilinks and scalar placeholders are accepted input but
become repair suggestions when they cannot be resolved deterministically.

**Mapping (current vault → whodex):**

| Vault frontmatter / file              | whodex                                          | Notes |
|---------------------------------------|-------------------------------------------------|-------|
| filename `Jane Doe.md`                | `display_name` / canonical-name identifier      | |
| `type:`                               | `Entity.kind` / `subtype` (Startup, City, …)    | routes person/org/location/event |
| `aliases: [..]`                       | aliases / alias identifiers                     | |
| `organisations: [[Kolai]]`            | `member_of` Edge + `job.org`; ↔ org `employees` | missing inverse → `GraphRepairSuggestion` |
| `lives: [[…]]` (preferred)            | `lives_in` Edge + `location.*`                  | **preferred** location field on write-back |
| `city:` / `country:` / `location:` / `parent:` | read as location hierarchy/contact point | scalar placeholders → graph repair |
| `last contact: <date>`                | `Interaction(contacted, obsidian)`              | whodex writes it back on TUI log |
| `next contact: <date>`                | manual reminder / next-reminder override        | |
| `source: [LinkedIn,Email,…]`          | channel metadata (NOT whodex provenance)        | naming collision — read-only |
| `strategic tier`/`parent`/`location` (org) | `org.strategic_tier` / `part_of` / `located_in` | preserve key spelling on write-back |
| Event `datetime`/participants/follow-up | `Interaction` + `attended`/`hosted_at`/`organized_by` Edges | |
| body `## Notes`, `- Kennenlernen:`    | untouched                                       | only the marked `%% whodex:edges %%` block is whodex-owned |
| **(new)** `linkedin:`/`emails:`/`phones:`/`job_title:` | `linkedin.url`/`email`/`phone`/`job.title` | **enriched** from Google/LinkedIn |
| **(new)** `cadence:` / `tier:`        | `cadence_days` / `importance`                   | enables reminders + prioritization |
| **(new)** `whodex:` block             | `uid` (once), `last_sync`, `projection_hash`, `managed_fields` | whodex-owned; never hand-edit |

**Decisions (locked 2026-06-01):** adopt-and-add vocabulary (no migration); inject a one-time `whodex.uid`;
ingest the wikilink graph into edges in Phase 1. **Write-back** covers opted-in `managed_fields` (incl.
`organisations`/`lives`); graph/inverse-link gaps go through `GraphRepairSuggestion` + an explicit
`apply_graph_repair` — whodex never silently restructures the vault. Preserve existing key spelling
(`next contact`, `strategic tier`). Quote any value containing `[[`/`:`; write frontmatter (not Dataview
inline) so Bases/Dataview render editable tables.

Initial graph repair queue: `missing_inverse`, `stale_membership`, `unresolved_ref`, `placeholder_ref`,
`broken_wikilink`, `duplicate_entity`, `missing_note`, and `template_drift`. Repairs must be fingerprinted
and batchable/idempotent; applying one may edit only the proposed frontmatter field or whodex-owned block.

**Value story:** read the graph you already maintain, fill the blanks (real emails / LinkedIn URL / job
title) in notes you keep, keep `last contact` current from the TUI, and offer one-click graph maintenance —
all while Obsidian stays the editable source.

## 7. Commands (target — wire up in Phase 0, keep current)

```
uv sync                 # install
uv run whodex sync      # one-shot: run_sync + drain_tasks + dispatch_notifications
uv run whodex serve     # daemon: the same, on a loop + FastAPI ingest + vault watch
uv run whodex tui       # Textual UI
uv run whodex token issue --label firefox   # mint an ingestion bearer token
uv run pytest -m "not tui" --cov            # unit/integration/e2e
uv run pytest -m tui                         # TUI snapshot tests
uv run ruff check . && uv run ruff format --check . && uv run mypy --strict src && uv run lint-imports
```

## 8. Status

**Current phase: Phase 1 in progress (sequenced into increments).** Spec at `docs/DESIGN.md`; vault
contract locked (§9). Phase 0 plan: `docs/superpowers/plans/2026-06-01-phase-0-walking-skeleton.md`.

- **Phase 0 — Walking Skeleton: COMPLETE ✅** (ledger → projection → SQLite, `whodex sync`).
- **Phase 1a — Engine: COMPLETE ✅** (`docs/superpowers/plans/2026-06-01-phase-1a-engine.md`) — pure
  `score_contact`/`build_score_inputs` prioritization, `staleness` freshness, idempotent `generate_reminders`,
  `priority_queue` + `whodex queue`. 85 tests, gate green. *Deferred:* `event_boost` wiring from persisted
  changes, `centrality`, reminder persistence/dispatch, freshness re-check queue.
- **Phase 1b — Durable core + Obsidian read: COMPLETE ✅**
  (`docs/superpowers/plans/2026-06-01-phase-1b-durable-obsidian-read.md`) — store-backed durable identity
  (`StoreIdentityResolver` + `EntityStore`), SQLite ledger+projection, JSONL ledger mirror, vault parser
  (`ruamel`)/routing/`ObsidianSource` (PULL), `whodex sync/queue --vault --db`. 209 tests, gate green.
  Invariants I1–I6 (idempotent re-sync, durable identity, replay determinism, parse fidelity, routing,
  source contract) verified; the e2e invariant suite caught two real defects (`vault_path` strong key;
  hub `_kind` routing). *Deferred:* edges/graph-repair (1c), write-back (1d), git-based `observed_at`,
  interaction-dedup on re-sync (1c).
- **Phase 1c — Graph projection + repairs + persistence: COMPLETE ✅**
  (`docs/superpowers/plans/2026-06-01-phase-1c-graph.md`) — `EdgeStore` + edge projection from wikilink refs
  (`member_of`/`lives_in`/`located_in`/`part_of`/`hosted_at`/`organized_by`/`attended`), `unresolved_ref`/
  `placeholder_ref` repairs, durable Change/Conflict/Reminder/Repair rows, `event_boost` wired from open
  changes, `people_at`/`contact_points` + `whodex who-at`. 333 tests, gate green. Invariant tests caught 2
  real defects (non-idempotent edge replace; missing change fingerprint). *Deferred:* `missing_inverse`/
  `duplicate_entity`/`missing_note` repairs + org `employees` ingestion; centrality (Phase 5).
- **Phase 1d — Obsidian write-back (anti-clobber): COMPLETE ✅**
  (`docs/superpowers/plans/2026-06-01-phase-1d-writeback.md`) — round-trip `render_with_changes` (clean
  diffs), `VaultFileState` persistence, pure `plan_writeback` (fill-blank, never clobber, uid-once,
  idempotent; property-tested), `whodex sync --write-back` + echo suppression. 405 tests, gate green.
  Dedicated review caught + fixed a vacuous echo-suppression test and an empty/scalar-`whodex.uid`
  non-convergence bug. *Deferred:* `watchdog` daemon watch (1g), applying graph repairs to the vault.
- **Phase 1f — Ingestion API + tokens + LinkedIn-ext: COMPLETE ✅**
  (`docs/superpowers/plans/2026-06-01-phase-1f-ingestion-api.md`) — revocable bearer tokens (hash-only) +
  `whodex token issue`, FastAPI `create_app`/`POST /ingest` (202, token-gated, shared `ingest_one`/
  `reproject_and_persist` pipeline — no divergent path), `linkedin_ext` PUSH source. 458 tests, gate green,
  97% cov. A1–A6 (auth/ingest/idempotent/422) via TestClient over a durable app. *Deferred:* serving the
  app (`whodex serve` in 1g), webhook/RSS, TLS.
- **Phase 1e — Google Contacts (OAuth): COMPLETE ✅**
  (`docs/superpowers/plans/2026-06-01-phase-1e-google.md`) — People API via injected `httpx` +
  `GoogleTokenProvider` (OAuth refresh isolated, `respx`-mocked in CI), mapping/pagination/`nextSyncToken`
  incremental + `EXPIRED_SYNC_TOKEN` recovery, optional wiring when `WHODEX_GOOGLE_*` env present, Google
  loses to Obsidian by trust (60<80). 505 tests, gate green, 97% cov. **User setup** (Google Cloud OAuth
  Desktop client + env vars) documented in the plan's "Google setup" section. *Deferred:* live OAuth in CI,
  delete-handling, group/photo sync.
- **Phase 1g — Facade + notifications + TUI + serve + config: COMPLETE ✅**
  (`docs/superpowers/plans/2026-06-01-phase-1g-tui.md`) — headless `Whodex` facade (priority_queue/
  contact_detail/review_queue + log_interaction/pin/snooze/ack/apply_repair), `Notification` persistence +
  `NotificationDispatcher`/`TUINotifier` (idempotent), Textual TUI (queue/detail/contact-points/review/
  log-interaction modal), `serve_tick` + `whodex serve`, TOML+env config (`pydantic-settings`). 572 tests,
  gate green, 94% cov. Full CLI: `sync`/`queue`/`who-at`/`serve`/`tui`/`token`. *Deferred/known:* scoring &
  freshness config knobs parsed but not yet threaded into the queue (stashed on `App`); Telegram/email sinks
  (Phase 2); FastAPI mount + watchdog in `serve`; TUI snapshot tests (Pilot-only for now).
- **Phase 1h — Firefox WebExtension (MV3): COMPLETE ✅**
  (`docs/superpowers/plans/2026-06-01-phase-1h-firefox.md`) — `extension/` MV3 package (manifest, content/
  background/options), pure node-tested core: `extractProfile`/`canonicalLinkedinUrl`/`buildRecord`/
  `postRecord` (27 `node --test` cases), dynamic-import extractor (`web_accessible_resources`) for MV3,
  manual-E2E README. Outside the Python gate (`extension/` ≠ `src/`); Python gate unaffected (572).
  *Deferred:* one-command HTTP server (`whodex serve --http` / uvicorn mount), store packaging, esbuild bundling.

### 🎉 Phase 1 (MVP) COMPLETE — 1a–1h all merged to `main`.
The daily loop works on real data: `whodex sync --vault <vault> --db <db>` ingests the Obsidian vault
(durable, idempotent) + Google (when configured) + LinkedIn-ext (via the ingestion API/extension); `whodex
queue`/`tui` rank reach-outs with why-now; `log_interaction`/`pin`/`snooze` work; write-back enriches notes
without clobbering; the graph answers `who-at`; reminders/notifications dispatch; `serve` runs the loop.
**572 Python tests + 27 node tests, full gate green.** Next: **Phase 2 — push notifiers (Telegram/email)**
— detailed task plan ready at `docs/superpowers/plans/2026-06-02-phase-2-push-notifiers.md` (7 tasks;
reuses the Phase-1g Notifier/dispatch seam; Telegram bot client + email sink + cross-sink dedupe).

**Phase 0 — Walking Skeleton (done):** fake source → ledger → projection → SQLite, end-to-end, fully tested.
62 tests passing; `ruff`/`mypy --strict`/`import-linter` all green; 94% coverage. `uv run whodex sync --demo` works.
- [x] Repo scaffolding: `uv`/`hatchling`, `src/` layout, `ruff`/`mypy --strict`/`import-linter`, CI
- [x] `domain`: `EntityRef`, events (`Observation`/`ObservationDraft`/`Interaction`/`UserAction`),
      `EntityState`/`ContactProfileState`, `Change`, `ConflictSuggestion`, `GraphRepairSuggestion` (seam),
      `Clock`/`FixedClock`, `IdFactory`, `fields.py` (22 fields), `DEFAULT_TRUST`
- [x] `projection`: precedence comparator + pure `project()` fold + change (§6.4) + conflict (§6.5, gated on
      strictly-lower-trust) detection
- [x] `store`: in-memory + SQLite behind one `LedgerStore` contract (recompute-on-read)
- [x] `sources.base`: `Source`/`PullSource` protocol + `apply_map` + `FakeSource` + `SourceContract` suite
- [x] `sync`: `IngestionHub`+`IdentityResolver`, `run_sync` wiring FakeSource → hub → ledger → projection
- [x] `config` composition root + `cli`: `whodex sync` prints projected state
- [x] test DSL `obs()/interaction()/action()/raw()`; L1 projection tests; e2e acceptance
- **Done when (met):** `sync` idempotent (re-run ⇒ 0 changes/conflicts), SQLite ≡ in-memory, all gates green.

**Phase 0 deferred to Phase 1 (seams present):** edge projection + graph-repair rules; JSONL ledger mirror.
**Phase 1 follow-ups flagged in final review:** strengthen store contract to exercise interaction/user-action
mappers (currently 56% cover); assert full `EntityState` parity in the SQLite≡memory e2e; make `ConflictSuggestion.reason`
an enum; cover/justify the CLI `version` command.

(Phase 1+ deliverables: DESIGN §13.)

## 9. Decision log & open questions

**Decisions** (newest first):
- 2026-06-01 — Strengthened the graph-maintenance design after inspecting the live templates/notes:
  route entities by folder + type + tags, accept nested people folders and bare wikilinks, treat placeholders
  as repair candidates, make contact-point summaries explicit, and define the initial repair taxonomy.
- 2026-06-01 — Vault contract locked: (Q1) adopt `people-network` vocabulary + add keys, no migration;
  (Q2) inject one-time `whodex.uid`; (Q3) ingest the wikilink graph into edges in Phase 1. Reflected in
  DESIGN §2.3 / §3.1 / §5.
- 2026-06-01 — DESIGN upgraded to a typed `Entity` graph (person/organisation/location/event) with
  `EntityRef` wikilinks and a `GraphRepairSuggestion` maintenance lane — mirrors the real vault; supersedes
  the earlier person-centric `Contact` model.
- 2026-06-01 — Adopted 3 ledger streams (`Observation`/`Interaction`/`UserAction`) + JSONL mirror,
  `Change`/`ConflictSuggestion` split, `ObservationDraft`→hub-finalized `Observation`, pure-pydantic
  `domain` (SQLModel only in `store`).

**To resolve during Phase 0 (implementation-time):**
- **Field-registry strings** — DESIGN uses flat paths for shared person atoms (`name.full`, `job.title`,
  `email`, `linkedin.url`) and `kind.field` paths for entity-specific/graph fields (`person.organisations`,
  `person.lives`, `org.location`, `org.parent`, `org.strategic_tier`, `event.participants`,
  `contact.next_at`/`contact.last_at`). Pin the exact canonical strings in `fields.py` as the single source of
  truth; every example (incl. `GoogleContacts.MAP` §4.3) must reference them.

**Carried from DESIGN §14:** O1 `custom.*` write-back · O2 date-less `observed_at` discount · O3 Google
consent posture · O4 edges-block anti-clobber · O5 projection timing · O6 cadence default · O7 snooze vs
dismiss · O8 weak-tier visibility · O9 contact-event granularity · O10 Obsidian visual wikilink behavior ·
O11 managed graph-repair auto-apply classes.

## 10. Working agreements

- **TDD by default** (superpowers `test-driven-development`): red → green → refactor. Behavior tests over
  implementation; the event ledger is the fixture format.
- **Test behavior & invariants, NOT implementation** (user directive). Confirm invariants that hold across
  many states — idempotency (run N times == once, no dup entities/changes), replay determinism (rebuild
  from ledger/JSONL == original), order-independence, round-trip (`parse(render(x)) == x`), identity
  stability across runs. Prefer parametric / `hypothesis` property tests over one hardcoded example. Assert
  through public interfaces / the facade, never internal helpers, private functions, or call counts — tests
  must survive any behavior-preserving refactor. (Readable example tests are fine only for concrete numbers.)
- **Don't break the dependency direction** (§5). `lint-imports` is a merge gate, not a suggestion.
- **Never weaken the anti-clobber invariant** to make a test pass — fix the design.
- **Commits:** conventional, scoped. **Never add a `Co-Authored-By` / AI co-author trailer** (user
  preference — keep authorship clean). Branch off `main` for feature work; commit/push only when asked.
- **Update this file** (§8 Status, §9 Decision log) as part of finishing any task.
