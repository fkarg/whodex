# whodex Phase 1b — Durable Core + Obsidian Read Connector

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.
> **Testing law (user directive, AGENTS §10):** test **behavior & invariants across states**, not implementation. Each task LEADS with behavioral/property tests; the implementation exists to satisfy them. Prefer parametric / `hypothesis` tests for genuine invariants. Assert through public interfaces — never private helpers, intermediate shapes, or call counts. Tests must survive any behavior-preserving refactor.

**Goal:** `whodex sync --vault <dir>` reads a real Obsidian vault (people-network format) into a **durable** typed-entity store that survives across process runs (no duplicate entities on re-run), and `whodex queue` ranks the real people. Append-only ledger persists to SQLite + a JSONL mirror.

**Architecture:** make the Phase-0 core durable (SQLite ledger + projection, store-backed identity resolution) and add a read-only `ObsidianSource` (`Capability.PULL`) that feeds the existing ingestion funnel. No write-back, no edges (1c/1d).

**Tech stack:** + `ruamel.yaml` (frontmatter), `watchdog` not yet (1d). Same gate.

---

## Scope

In: durable SQLite `LedgerStore`+`ProjectionStore` wired into the CLI; JSONL ledger mirror; persisted `Entity`+`EntityIdentifier` with **store-backed identity resolution** (stable across runs); vault markdown parser (frontmatter + body + wikilink `EntityRef`s); routing (folder/type/tags → `EntityKind`); `ObsidianSource` (PULL) + interaction ingest for `last contact`; `whodex sync --vault/--db`; integration + invariant tests + a fixture smoke against a copied subset of `../people-network`.

Out (later): edge projection + graph repairs (1c); write-back / `whodex.uid` injection / watch (1d); Organisation/Location/Event beyond entity creation + scalar observations (1c); Google (1e).

**Key invariants this increment must guarantee (these ARE the tests):**
- **I1 Idempotent re-sync:** syncing the same vault twice yields the same set of entities (no duplicates) and **0 changes** on the second run.
- **I2 Durable identity:** the same identity keys resolve to the same `entity_id` across *independent* resolver/store instances (simulating separate process runs).
- **I3 Replay determinism:** rebuilding state from the persisted ledger (and from the JSONL mirror) reproduces the identical projection.
- **I4 Parse fidelity:** parsing preserves unknown frontmatter keys and the body verbatim; parsing is deterministic and order-independent over key order.
- **I5 Routing is a pure function** of (folder, `type`, tags) — same inputs → same kind, across the whole table.
- **I6 Source contract:** `ObsidianSource` passes the shared `SourceContract` (valid drafts, normalize idempotent, stable id).

**Conventions:** TDD; full gate before each commit (`uv run ruff format . && ruff check . && mypy --strict src && lint-imports && pytest -q`); no `Co-Authored-By`; focused commits; `now`/`IdFactory` injected.

## File structure

```
src/whodex/
├── domain/
│   ├── events.py        # (maybe) InteractionDraft for last-contact ingest
│   └── ids.py           # (unchanged)
├── store/
│   ├── interfaces.py    # + EntityStore protocol
│   ├── memory.py        # + InMemoryEntityStore; durable-ish in-memory projection already exists
│   ├── rows.py          # + EntityRow, EntityIdentifierRow, ProjectionStateRow
│   ├── mappers.py       # + entity/identifier/state mappers
│   ├── sqlite.py        # + SqliteEntityStore, SqliteProjectionStore; JSONL mirror in SqliteLedgerStore
│   └── jsonl.py         # JSONL mirror writer + reader (recovery)
├── vault/
│   ├── markdown.py      # parse_note(text) -> ParsedNote ; ref extraction
│   ├── fs.py            # scan(vault_dir) -> Iterable[VaultFile]
│   └── routing.py       # route(folder, type, tags) -> (EntityKind, subtype)
├── sources/
│   └── obsidian.py      # ObsidianSource (PULL)
├── sync/
│   ├── hub.py           # store-backed IdentityResolver; interaction ingest path
│   └── engine.py        # build kinds from EntityStore; persist projection
└── config/settings.py   # SQLite wiring; --vault/--db; vault path
tests/store/ tests/vault/ tests/sources/ tests/sync/ + tests/test_e2e_phase1b.py
fixtures/people-network-min/  # small copied subset of the real vault for smoke tests
```

Dependency note: `vault` and `store` and `sources` stay at the same import layer (depend on `domain` only); `sync` wires them; `config` composes. import-linter must stay green.

---

### Task 1: `Entity` + `EntityIdentifier` persistence (rows + mappers + EntityStore)

**Behavioral spec / invariants to encode (tests first):**

`tests/store/entity_store_contract.py` — a reusable `EntityStoreContract` (no `Test` prefix), subclassed for in-memory and SQLite:
```python
from tests.conftest import _t


class EntityStoreContract:
    def make_store(self):  # override
        raise NotImplementedError

    def test_create_then_find_by_identifier_returns_same_entity(self):
        s = self.make_store()
        eid = s.create_entity(kind="person", created_at=_t(1))
        s.add_identifiers(eid, [("email", "a@b.com")])
        assert s.find_by_identifiers([("email", "a@b.com")]) == eid

    def test_unknown_identifier_returns_none(self):
        assert self.make_store().find_by_identifiers([("email", "x@y.com")]) is None

    def test_identifiers_are_normalized_email_case_insensitive(self):
        s = self.make_store()
        eid = s.create_entity(kind="person", created_at=_t(1))
        s.add_identifiers(eid, [("email", "Jane@Acme.COM")])
        assert s.find_by_identifiers([("email", "jane@acme.com")]) == eid  # normalized

    def test_kinds_map_reflects_created_entities(self):
        s = self.make_store()
        eid = s.create_entity(kind="organisation", created_at=_t(1))
        assert s.kinds()[eid] == EntityKind.organisation  # import EntityKind in the concrete test
```
(Concrete `tests/store/test_entity_memory.py` subclasses with `InMemoryEntityStore`; the SQLite subclass is added in Task 3's store or here — put both backends under the same contract so behavior is identical across them: an invariant, not an implementation detail.)

**Implementation guidance:** `EntityRow(id, kind, subtype, created_at, vault_path, vault_uid, merged_into, archived)`, `EntityIdentifierRow(id, entity_id, kind, value)` with a unique `(kind, value)` (an identifier maps to at most one entity); normalize identifier values on write+query (lowercase email, canonical linkedin url, E.164 phone — reuse/extend a small `normalize_identifier(kind, value)` helper in `domain`). `EntityStore` protocol in `store/interfaces.py`: `create_entity(kind, *, created_at, subtype=None, vault_path=None, vault_uid=None) -> str`, `add_identifiers(entity_id, pairs)`, `find_by_identifiers(pairs) -> str | None` (first matching strong key wins), `kinds() -> dict[str, EntityKind]`, plus `get(entity_id)`. In-memory + SQLite impls.

**Done when:** both backends pass `EntityStoreContract` identically; normalization invariant holds. Commit `feat(store): persistent Entity/EntityIdentifier registry + EntityStore`.

---

### Task 2: SQLite `ProjectionStore` (durable prev-state) + store contract

**Behavioral spec (tests first):** extend a projection-store contract so save→load round-trips an `EntityState` map exactly, across both in-memory and SQLite backends (invariant: `load() == saved`, and a fresh store instance over the same DB path loads the same state — durability).
```python
# tests/store/projection_store_contract.py
class ProjectionStoreContract:
    def make_store(self):  # override; SQLite variant must use a shared temp file path
        raise NotImplementedError

    def test_save_then_load_roundtrips_state(self):
        s = self.make_store()
        state = {"E1": _entity_state("E1", {"job.title": "Eng"})}  # helper builds EntityState
        s.save(state)
        assert s.load() == state

    def test_empty_load_is_empty(self):
        assert self.make_store().load() == {}
```
For SQLite durability, the contract's SQLite variant constructs two store instances over the **same temp-file DB** and asserts the second loads what the first saved (cross-instance invariant ≈ cross-run).

**Implementation guidance:** `ProjectionStateRow(entity_id PK, state_json)`; serialize via `EntityState.model_dump_json()` / validate on load. `SqliteProjectionStore(url)` with `StaticPool` for in-memory (as the ledger does) and a real file for durability. (Recompute-on-read remains valid; this store persists the *previous* projection so cross-run change-detection works.)

**Done when:** both backends pass `ProjectionStoreContract`; SQLite state survives across instances. Commit `feat(store): durable SQLite ProjectionStore`.

---

### Task 3: JSONL ledger mirror + recovery reader

**Behavioral spec (tests first), invariant I3 (partial):**
```python
# tests/store/test_jsonl_mirror.py
def test_jsonl_mirror_roundtrips_all_streams(tmp_path):
    store = SqliteLedgerStore("sqlite://", jsonl_dir=tmp_path)  # mirror enabled
    store.append_observations([obs(entity="E1", field="job.title", value="Eng")])
    store.append_interactions([interaction(entities=("E1",))])
    store.append_user_actions([action(action_type=UserActionType.pin, target_type="contact",
                                       target_id="E1", entity="E1")])
    rebuilt = read_events_from_jsonl(tmp_path)               # recovery path
    sqlite_events = store.read_events()
    assert rebuilt == sqlite_events                          # invariant: JSONL == SQLite truth

def test_mirror_is_append_only_across_calls(tmp_path):
    store = SqliteLedgerStore("sqlite://", jsonl_dir=tmp_path)
    store.append_observations([obs(entity="E1", field="email", value="a@b.com")])
    store.append_observations([obs(entity="E1", field="job.title", value="Eng")])
    assert len(read_events_from_jsonl(tmp_path).observations) == 2
```

**Implementation guidance:** `store/jsonl.py`: `append_jsonl(dir, stream_name, models)` (one JSON object per line, `model_dump_json`), `read_events_from_jsonl(dir) -> EventStream`. `SqliteLedgerStore.__init__` gains optional `jsonl_dir`; each `append_*` mirrors after the SQLite commit. Keep the existing in-memory `sqlite://` tests working (no `jsonl_dir` → no mirror).

**Done when:** rebuilt-from-JSONL `EventStream` equals the SQLite `read_events()`; mirror append-only. Commit `feat(store): JSONL ledger mirror + recovery reader`.

---

### Task 4: store-backed `IdentityResolver` (invariant I2)

**Behavioral spec (tests first):**
```python
# tests/sync/test_identity_durable.py
def test_same_identity_resolves_to_same_entity_across_instances():
    store = InMemoryEntityStore()
    r1 = StoreIdentityResolver(store, ids=SequentialIdFactory("E"), clock=FixedClock(_t(1)))
    eid = r1.resolve({"email": "a@b.com"}, kind=EntityKind.person)
    # NEW resolver over the SAME store == a separate process run
    r2 = StoreIdentityResolver(store, ids=SequentialIdFactory("E"), clock=FixedClock(_t(2)))
    assert r2.resolve({"email": "a@b.com"}, kind=EntityKind.person) == eid

def test_resolution_is_order_independent_over_identity_keys():
    store = InMemoryEntityStore()
    r = StoreIdentityResolver(store, ids=SequentialIdFactory("E"), clock=FixedClock(_t(1)))
    a = r.resolve({"email": "a@b.com", "linkedin_url": "https://x/in/a"}, kind=EntityKind.person)
    b = r.resolve({"linkedin_url": "https://x/in/a", "email": "a@b.com"}, kind=EntityKind.person)
    assert a == b
```
Plus a `hypothesis` property test: for any sequence of `resolve` calls with overlapping identity dicts, an identity key never maps to two different entity ids (function is consistent), and resolving the same dict twice is stable.

**Implementation guidance:** `StoreIdentityResolver` (replaces the in-memory dict resolver) backed by `EntityStore`: `resolve(identity, kind)` → `find_by_identifiers(strong_keys)`; if found, ensure any new keys are added; else `create_entity` + `add_identifiers` + append a system `entity_create` `UserAction` (so the durable ledger explains the entity). `kinds()` delegates to the store. Keep `primary_ref`. Wire into `IngestionHub` (constructor takes the resolver; minimal change). The Phase-0 in-memory resolver may stay for pure-unit hub tests OR be replaced by `StoreIdentityResolver(InMemoryEntityStore())` — keep hub tests green either way.

**Done when:** I2 + order-independence + the property hold; `IngestionHub` uses the store-backed resolver; existing hub tests pass. Commit `feat(sync): store-backed durable identity resolution`.

---

### Task 5: vault markdown parser (invariant I4)

**Behavioral spec (tests first), property/parametric:**
```python
# tests/vault/test_markdown.py — behavior + invariants
import hypothesis.strategies as st
from hypothesis import given

def test_parse_extracts_frontmatter_and_preserves_body():
    text = "---\ntype: Person\naliases: [Jane]\n---\n## Notes\n- Kennenlernen: x\n"
    note = parse_note(text)
    assert note.frontmatter["type"] == "Person"
    assert "## Notes" in note.body and "Kennenlernen" in note.body

def test_unknown_frontmatter_keys_preserved():
    note = parse_note("---\ntype: Person\nweird_key: keep-me\n---\nbody\n")
    assert note.frontmatter["weird_key"] == "keep-me"

def test_no_frontmatter_is_handled():
    note = parse_note("just a body, no frontmatter\n")
    assert note.frontmatter == {} and "just a body" in note.body

def test_wikilink_values_round_trip_via_entityref():
    note = parse_note('---\norganisations:\n  - "[[Organisations/Kolai|Kolai]]"\n---\n')
    refs = note.refs("organisations")            # -> list[EntityRef]
    assert refs[0].target_path == "Organisations/Kolai" and refs[0].label == "Kolai"

@given(body=st.text())
def test_body_is_preserved_verbatim_for_any_body(body):
    # frontmatter fixed, arbitrary body (excluding a leading '---' delimiter clash)
    text = f"---\ntype: Person\n---\n{body}"
    assert parse_note(text).body == body
```
(Invariant I4: unknown keys preserved; body verbatim; deterministic.)

**Implementation guidance:** `vault/markdown.py`: `ParsedNote` (frontmatter: dict, body: str, raw: str; `.refs(key)` parses wikilink scalar/list values to `EntityRef`s). Use `ruamel.yaml` to load frontmatter (round-trip loader so 1d can re-emit); split on the leading `---\n...\n---\n` fence; everything after = body (byte-preserved). Guard the property test against bodies containing a frontmatter fence at column 0 (constrain the strategy or document the boundary).

**Done when:** I4 invariants pass (incl. the property test). Commit `feat(vault): frontmatter+body+wikilink parser`.

---

### Task 6: routing (invariant I5)

**Behavioral spec (tests first), parametric over the DESIGN §2.3 table:**
```python
# tests/vault/test_routing.py
import pytest
from whodex.domain.enums import EntityKind
from whodex.vault.routing import route

@pytest.mark.parametrize("folder,type_,tags,expected_kind", [
    ("People", "Person", ["Person"], EntityKind.person),
    ("People/Inactive", "Person", [], EntityKind.person),          # nested people folder
    ("Organisations", "Startup", ["Organisation"], EntityKind.organisation),  # subtype
    ("Organisations", None, ["Organisation"], EntityKind.organisation),
    ("Locations", "City", ["Location"], EntityKind.location),
    ("Locations", "Country", [], EntityKind.location),
    ("Events", "Event", ["Event"], EntityKind.event),
])
def test_routing_table(folder, type_, tags, expected_kind):
    kind, _subtype = route(folder, type_, tags)
    assert kind == expected_kind

def test_subtype_carries_from_type_for_org():
    _kind, subtype = route("Organisations", "Startup", ["Organisation"])
    assert subtype == "Startup"
```
Add a property/parametric test that `route` is a pure function (same inputs → same output) — trivially true but documents I5; the real value is broad table coverage incl. real-vault edge cases (e.g. `type` missing, conflicting folder/tag → define precedence: folder > type > tags, and TEST that precedence).

**Implementation guidance:** `route(folder: str, type_: str | None, tags: list[str]) -> tuple[EntityKind, str | None]`. Precedence: folder prefix (`People*`→person, `Organisations*`→organisation, `Locations*`→location, `Events*`→event); else `type`/tags. Subtype = `type` when it's not the bare kind name.

**Done when:** I5 + precedence tests pass. Commit `feat(vault): entity routing by folder/type/tags`.

---

### Task 7: `ObsidianSource` (invariant I6) + interaction ingest for `last contact`

**Behavioral spec (tests first):**
- `ObsidianSource` passes the shared `SourceContract` (point a temp vault at it).
- Mapping behavior (parametric over the people-network vocabulary): a Person note with `aliases`, `organisations`, `lives`/`city`/`country`, `tags`, and enrichment keys (`linkedin`, `emails`, `job_title`) → the expected set of `ObservationDraft` canonical fields (assert the *set of (field,value)* produced, a behavior, not internal parsing steps).
- `source:` key is NOT emitted as whodex provenance (it's channel metadata) — assert it does not become an observation.
- A `last contact: <date>` produces an interaction (behavioral: after ingest, the entity's `last_interaction_at` reflects it / an interaction exists for that entity).
```python
# tests/sources/test_obsidian.py (sketch)
def test_obsidian_source_passes_contract(tmp_path): ...   # reuse SourceContract with a vault fixture
def test_person_note_maps_to_expected_canonical_fields(tmp_path): ...
def test_source_channel_list_is_not_provenance(tmp_path): ...
def test_last_contact_becomes_an_interaction(tmp_path): ...
```

**Implementation guidance:** `ObsidianSource(vault_dir, *, clock)` (`Capability.PULL`): `fetch(since)` scans `*.md`, routes, builds `RawRecord` per note (identity from `whodex.uid` if present, else `vault_path`, plus `linkedin`/`emails`; payload = parsed frontmatter incl. wikilink raws + folder/type/tags + filename); `normalize(record)` maps people-network keys → `ObservationDraft`s (scalar fields directly; `organisations`/`lives`/`city`/`country` as REF/MULTI_REF values carrying the raw wikilink string(s) — edges deferred to 1c; `aliases`/`tags` as MULTI). For `last contact`, emit via a new hub **interaction ingest** path (e.g. the source also yields interaction drafts, or `normalize` returns interactions too — choose the simplest: a separate `ObsidianSource.interactions(record)` consumed by the runner, or extend the hub to accept interaction drafts). Add canonical fields to `fields.py` as needed (`name.full`, `aliases` etc. — reuse existing where possible). Identity keys declared so `SourceContract` + identity resolution work.

**Done when:** I6 + mapping behavior + last-contact→interaction hold. Commit `feat(sources): read-only Obsidian vault connector`.

---

### Task 8: wire durable composition + `whodex sync --vault/--db`

**Behavioral spec (tests first):** CLI behavior via `CliRunner` against a temp vault + temp db: `whodex sync --vault <dir> --db <file>` exits 0 and reports ingested>0; `whodex queue --vault <dir> --db <file>` lists real people from the vault. (Behavioral — assert observable output/exit, not wiring internals.)

**Implementation guidance:** `config/settings.py` `build_app` gains `vault: Path | None`, `db: Path | None`; when `db` set, wire `SqliteLedgerStore(db, jsonl_dir=vault/.whodex/events)` + `SqliteProjectionStore(db)` + `SqliteEntityStore(db)` + `StoreIdentityResolver`; when `vault` set, add `ObsidianSource(vault)`. CLI `sync`/`queue` gain `--vault`/`--db` options (default to config). `run_sync` builds `kinds` from the EntityStore (not an in-memory dict) and persists projection via the durable store.

**Done when:** the CLI behaviors pass; defaults still work for `--demo`. Commit `feat(cli,config): durable SQLite wiring + --vault/--db`.

---

### Task 9: end-to-end invariants + real-vault fixture smoke (I1, I2, I3 end-to-end)

**Behavioral spec (tests first) — the increment's acceptance, all invariant-style:**
```python
# tests/test_e2e_phase1b.py
def test_resync_is_idempotent_no_duplicate_entities_and_zero_changes(tmp_path):
    vault = _write_min_vault(tmp_path)          # a few People notes
    db = tmp_path / "whodex.db"
    r1 = _run_sync_cli(vault, db); r2 = _run_sync_cli(vault, db)   # two independent runs
    assert _entity_count(db) == _person_note_count(vault)          # no dup entities (I1)
    assert r2.changes == 0                                         # I1: nothing changed on re-run

def test_state_rebuilds_identically_from_ledger_and_from_jsonl(tmp_path):
    # I3: project(SQLite ledger) == project(JSONL-rebuilt ledger) == persisted projection
    ...

def test_identity_stable_across_separate_runs(tmp_path):
    # I2 end-to-end: a person's entity_id is identical after a second independent sync
    ...

def test_smoke_against_people_network_fixture():
    # parse the copied fixtures/people-network-min subset: every Person note -> one person entity,
    # no exceptions, deterministic entity set across two runs
    ...
```
Create `fixtures/people-network-min/` — a SMALL copied subset of representative notes from `../people-network` (a couple People, an Organisation, a Location, an Event), committed to the repo so CI is self-contained. (Copy real examples, lightly anonymized if needed.)

**Implementation guidance:** thin test helpers (`_run_sync_cli`, `_entity_count` via a read-only query, `_write_min_vault`). No new production code expected beyond what Tasks 1–8 provide; if an invariant fails, fix the cause (don't weaken the test).

**Done when:** I1–I3 hold end-to-end against both a synthetic temp vault and the people-network fixture; gate green incl. coverage. Commit `test(e2e): Phase-1b durable + Obsidian-read invariants`.

---

## Self-review checklist (run after drafting tasks)
- Every task leads with behavior/invariant tests; no test asserts a private helper or intermediate shape.
- I1–I6 each have an owning test. Parametric/property tests used for routing (I5), parse fidelity (I4), identity consistency (I2).
- Durable identity + projection + JSONL all proven across *fresh instances* (cross-run proxy), not just within one process.
- import-linter layering preserved (`vault`/`store`/`sources` → `domain` only).
- No write-back, edges, or Google scope crept in.
- Real-vault fixture committed so CI is self-contained.
