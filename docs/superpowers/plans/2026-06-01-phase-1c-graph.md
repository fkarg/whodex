# whodex Phase 1c — Graph Projection + Repairs + Change/Reminder Persistence

> REQUIRED SUB-SKILL: superpowers:subagent-driven-development. **Testing law (AGENTS §10):** behavior & invariants via public interfaces; parametric/property where a real invariant exists; never assert internals. Controller runs an independent gate checkpoint after EVERY task.

**Goal:** turn the vault's wikilink relationships into a queryable `Edge` graph, surface deterministic `GraphRepairSuggestion`s for unresolved/placeholder refs, and **persist** Change/ConflictSuggestion/Reminder/GraphRepairSuggestion rows so they survive runs and `event_boost` finally wires into scoring. Expose contact-point queries (`who-at`).

**Builds on:** 1b durable core (EntityStore, SQLite ledger/projection, ObsidianSource emits `person.organisations`/`person.lives`/etc. as raw wikilink values).

## Scope
In: `Edge` persistence + `EdgeStore` (queries); ref→entity resolution; `build_edges` pure builder (REF/MULTI_REF observations → edges, with provenance); `GraphRepairSuggestion` rules for `unresolved_ref` + `placeholder_ref`; persistence of derived rows (Change/ConflictSuggestion/Reminder/GraphRepair) + run_sync wiring; `event_boost` fed from open (un-acked) Changes; contact-point queries + a `whodex who-at` CLI.

Out (later): `missing_inverse`/`stale_membership`/`duplicate_entity`/`missing_note` repairs + org `employees` ingestion (needs inverse modelling) → 1c-follow / 1d; centrality (Phase 5); applying repairs / write-back (1d).

## Invariants (the tests)
- **G1:** the fixture's wikilink relationships project to the expected edges (person→org `member_of`, person→location `lives_in`, event→org `organized_by`, etc.); re-sync is idempotent (no duplicate edges).
- **G2:** an `organisations: [[Nonexistent]]` (target with no matching note) yields exactly one `unresolved_ref` GraphRepairSuggestion, deduped on re-sync (stable fingerprint).
- **G3:** a job-change (notable Change) persists and, while un-acked, raises the person's priority via `event_boost`; acking it (UserAction) removes the boost — verified through the engine, not internals.
- **G4:** derived rows (Change/Reminder/...) persist and reload across store instances.
- **G5:** `who-at <org>` returns the people with a `member_of` edge to that org.

## Tasks

### Task 1: Edge persistence + EdgeStore (+ contract)
Behavioral contract (both in-memory + SQLite): `replace_edges(edges)` is a full snapshot (re-sync idempotent — invariant G1's dedup); `outgoing(entity_id, type=None)`, `incoming(entity_id, type=None)`, `neighbors(entity_id)`. Edge identity = `(src, dst, type)` (matches the existing `Edge` unique constraint). Add `EdgeRow`+mappers, `EdgeStore` protocol, in-memory + SQLite impls, shared contract test. Gate checkpoint.

### Task 2: ref resolution + `build_edges` (+ repair suggestions G2)
- `resolve_ref(entities: EntityStore, ref: EntityRef) -> str | None`: try `find_by_identifiers([("vault_path", ref.target_path + ".md")])`, then `[("vault_path", ref.target_path)]`; None if unresolved. (Bare-name/`canonical_name` resolution deferred.)
- `EDGE_FOR: dict[str, EdgeType]`: `person.organisations→member_of`, `person.lives→lives_in`, `org.location→located_in`, `org.parent→part_of`, `event.location→hosted_at`, `event.organizer→organized_by`, `event.participants→attended`.
- `build_edges(observations, *, resolve: Callable[[EntityRef], str|None], ids, now) -> tuple[list[Edge], list[GraphRepairSuggestion]]`: for each observation whose field is in `EDGE_FOR`, parse its value(s) via `EntityRef.parse`, resolve; resolved → `Edge(src=obs.entity_id, dst, type, observed_at=obs.observed_at)`; a wikilink target that doesn't resolve → `GraphRepairSuggestion(repair_type="unresolved_ref", fingerprint=stable(src,field,target))`; a non-wikilink scalar placeholder (no `target_path`, e.g. "Unknown"/"Location") → `placeholder_ref`. Pure given `resolve`. Behavioral + parametric tests over the field→edge table; G2 dedup via fingerprint. Gate checkpoint.

### Task 3: persist derived rows (G4)
Add rows+mappers+stores for `Change`, `ConflictSuggestion`, `Reminder`, `GraphRepairSuggestion` (a `DerivedStore` or extend existing). Snapshot-replace per sync EXCEPT carry user-state: `Change.seen/notified`, repair `status`, reminder dedup are overlaid from `UserAction`s (ack/dismiss). Behavioral: save→load round-trip across instances; status overlay survives re-sync (an acked change stays acked). Gate checkpoint.

### Task 4: wire edges + event_boost into run_sync (G3)
- `run_sync`: after projection, `build_edges` (resolver from EntityStore) → `edge_store.replace_edges(...)`; persist changes/conflicts/repairs.
- `build_score_inputs`: populate `open_change_kinds` from persisted, un-acked notable `Change`s for each person (pass the changes/acks in, keep it pure). → `event_boost` in `score_contact` now reflects real changes. G3 verified end-to-end (job change bumps priority; ack removes it).
Gate checkpoint.

### Task 5: contact-point queries + `who-at` CLI (G5)
`engine/graph.py`: `people_at(edge_store, entity_store, org_or_location_id) -> list[entity_id]` (incoming `member_of`/`lives_in`); `contact_points(edge_store, person_id)` (outgoing). CLI `whodex who-at <name> --vault --db` resolves a name/path to an entity and lists people. Behavioral CLI test. Gate checkpoint.

### Task 6: e2e invariants + gate
`tests/test_e2e_phase1c.py`: G1 (fixture edges + idempotent), G2 (unresolved repair dedup), G3 (event_boost from change, ack removes), G5 (who-at). Full gate + coverage. Controller independent gate verify before merge.

## Self-review: every task leads with behavior/invariant tests; edges/repairs deduped (idempotent); derived-row persistence proven cross-instance; event_boost wired & verified through the engine; deferred repairs (missing_inverse/duplicate/missing_note) explicitly noted.
