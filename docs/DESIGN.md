# whodex — Living Design Document

> Status: design spec (pre-implementation). Greenfield repo at `/home/pars/Coding/whodex`. Single technical power-user. This document is the source the implementation plan is built from.

---

## 0. North Star

**whodex tells you *who* to reach out to, *why* now, and *what changed about them* — without ever owning your data.**

It is a supplemental layer over a workflow that already works (Obsidian + a real messenger). If you delete whodex tomorrow, your vault and your relationships survive intact. whodex earns its place by doing four things the plain vault can't: **prioritized reach-out reminders**, **per-field freshness/staleness tracking**, **change detection** ("X changed jobs"), and **graph-maintenance automation** for the people/organisation/location/event network — all falling out naturally of one structural bet: an append-only event ledger that everything else is a deterministic fold over.

### Goals

1. A ranked "reach out today" queue with a one-line, human-readable *why-now* per person.
2. Per-person cadence + one-keypress "I contacted them" that resets the clock.
3. Per-field freshness ("last confirmed") and a "what changed" feed across all contacts.
4. Markdown/Obsidian as a genuine bidirectional source of truth — edits flow in, learned facts flow out, no clobbering.
5. The existing vault graph becomes operational: organisations, locations, and events are first-class contact points, not tags hidden in strings.
6. One-click maintenance for graph drift: missing inverse links, unresolved scalar places/orgs, duplicate notes, placeholder values, stale employee lists.
7. Pluggable sources (Google Contacts, Obsidian, LinkedIn) where adding a new one needs **zero core changes**.
8. One-shot `whodex sync` and an always-on daemon are the *same code*; scheduling is never load-bearing.
9. Headless core; TUI is the first thin client, Telegram/email/web come later for free.

### Non-Goals (deliberate YAGNI — see also §11)

- No multi-user / sharing / auth model. Single user; the ingestion API gets a static token.
- No automated outreach / message sending. whodex says who & why; you message in your real tools.
- No mobile/native app. TUI first.
- No LLM in Phase 1 (entity extraction, dedup, summarization, visual parsing = later lane).
- No CRDTs / fancy conflict-resolution UI. Trust-ranked precedence + manual override is enough.
- No general-purpose graph DB. Edges are rows in SQLite; centrality is a P2 nudge, not a pillar.
- No login-automation / scraping farm for LinkedIn. Passive capture + manual + paid-API fallback.
- No daemon-dependent logic. Everything a daemon does is reachable from a one-shot CLI.
- No web dashboard in Phase 1.

### Priority Order (kept visible throughout)

**modularity → testability → abstractions over shared concerns → simplification (YAGNI).** Every section below is written against this order. Where two fragments disagreed, the **simpler** option was chosen and the reason stated in one line.

---

## 1. The Central Bet: event ledger → projection → two materializations

Everything hangs off one inversion of the usual CRM mindset:

> **The event ledger is the only thing the world writes to. Both the SQLite projection tables AND the Markdown frontmatter are *caches* — deterministic folds over append-only events.**

```
state       = project(events)                # pure fold
score       = rank(state, now)               # pure
reminders   = due(state, now)                # pure
freshness   = staleness(state, now)          # pure
frontmatter = render(state)                  # pure
```

The durable ledger has three append-only streams:
- **Observation** — source assertions about a person/org (`job.title`, `email`, `location.city`, …).
- **Interaction** — touchpoints between the user and one or more contacts (`met`, `call`, `message`, …).
- **UserAction** — user/system decisions over derived state (`pin`, `snooze`, `dismiss`, `ack_change`, `merge`, `archive`, …).

SQLite stores both the durable ledger and derived cache tables. When this document says "replay the ledger," it means replay all durable streams, not just source observations. The ledger is also mirrored as newline-delimited JSON under `vault/.whodex/events/` after each successful append; that is the backup/recovery path if the SQLite file is lost. Frontmatter/git can reconstruct most source observations, but user decisions like dismissed reminders and rejected merge candidates must come from `UserAction`.

Markdown is "a source of truth" **not** because it stores authoritative state, but because it plays **two roles**:
- **Input source** — it emits observations (`source=obsidian`), exactly like LinkedIn or Google.
- **Output projection target** — the projection is rendered back out into frontmatter.

This dual role *dissolves* the central tension: a manual Obsidian edit is not special-cased. It is simply an observation from `source=obsidian` carrying a high trust rank. Delete the projection tables and the frontmatter, replay the ledger, and you are back. If the SQLite file is lost, replay the mirrored JSONL ledger plus vault/git-derived frontmatter observations. Plain-text durability; git as backup history.

The projector is a **pure function**:

```python
def project(events: EventStream, prev: EntityGraphState | None) -> ProjectionResult: ...
```

No DB, no IO, no clock-reading inside it (now is passed in where needed). This is the single most-tested unit in the system. SQLite materialization and Markdown write-out are thin adapters around it.

**Resolved contradiction — user intent (pin/snooze/dismiss/"contacted") storage.** Two fragments offered: (a) intents as `_`-prefixed observations in the same log; (b) a separate `user_action` table. **We choose: observations are only source facts; interactions and user actions get their own append-only streams.** Rationale: this keeps source precedence clean, preserves replayability for non-fact decisions, and avoids pretending that "dismiss this reminder" or "merge these contacts" is a fact about the person. The projector consumes all three streams; the precedence comparator only consumes observations plus the relevant user-action overlays (pins, accepted overrides, anti-merges).

---

## 2. Data Model

Plain pydantic `BaseModel` for domain/event/projection structs. SQLModel rows live in `store.sqlite` and map to/from those domain models; ORM concerns do not leak into `domain`. The snippets below describe the persisted row shape, not the pure domain classes.

**Conventions**
- IDs are **ULIDs** (`str`, 26 chars) — sortable, client-mintable (the browser extension can mint observation IDs offline), no central sequence.
- All timestamps `datetime`, tz-aware UTC.
- A **field** is a dotted path into a **closed, versioned registry** (`name.full`, `job.title`, `person.organisations`, `person.lives`, `org.location`, `org.parent`, `event.participants`, `email`, `linkedin.url`, …). Unknown paths are quarantined at ingest, not silently accepted. Fields that point to another note store an `EntityRef`, not a string. A `custom.*` namespace is the escape hatch (projected, weakly typed; **not** written back to frontmatter in Phase 1 — see open question O1).

```python
class EntityRef(BaseModel):
    entity_id: str | None = None          # set after resolution
    target_path: str | None = None        # Obsidian canonical path, e.g. "Organisations/Kolai.md"
    label: str | None = None              # wikilink display alias, e.g. "Kolai"
    raw: str                              # original scalar/wikilink for lossless round-trip
    resolution: str = "unresolved"        # resolved|ambiguous|missing|placeholder|unresolved
```

### 2.1 The append-only table

```python
class ObsOp(str, Enum):
    set = "set"               # scalar field has this value
    add = "add"               # multi-valued field gains a member (emails, tags)
    remove = "remove"         # multi-valued field loses a member
    assert_absent = "assert_absent"  # source positively reports field empty

class Observation(SQLModel, table=True):
    id: str = Field(primary_key=True)                       # ULID minted at capture
    source_run_id: str = Field(foreign_key="sourcerun.id", index=True)

    # WHO — raw external key kept so re-resolution after merge/unmerge works
    entity_id: str | None = Field(default=None, foreign_key="entity.id", index=True)
    external_ref: str = Field(index=True)                   # LI urn / google resourceName / vault_uid
    external_ref_kind: str

    # WHAT
    field: str = Field(index=True)                          # closed registry path
    op: ObsOp = ObsOp.set
    value: Any = Field(sa_column=Column(JSON), default=None)
    value_hash: str = Field(index=True)                     # sha256(canonical(field,op,value))

    # WHEN — distinct on purpose (see below)
    observed_at: datetime = Field(index=True)               # when the fact was TRUE per the source
    ingested_at: datetime                                   # when WE recorded it

    # HOW SURE / WHERE FROM
    confidence: float = 1.0
    raw_ref: str | None = None                              # pointer to archived raw blob

    __table_args__ = (
        UniqueConstraint(
            "source_run_id", "external_ref_kind", "external_ref", "field", "op", "value_hash"
        ),
    )  # idempotency: same source run + same external entity + same assertion
```

- **Append-only enforced at the service layer** (the repo exposes no update/delete) — not by SQLite. Corrections are new observations (`assert_absent` or a fresh `set`).
- **`observed_at` vs `ingested_at` are distinct on purpose.** Precedence uses `observed_at` (the newest *fact* wins). Freshness/staleness uses `ingested_at` (when we last *saw* it). A LinkedIn capture today of a job that started 6 months ago has `observed_at`≈start-date-if-known else capture-time, `ingested_at`=now.
- **`raw_ref` not raw blob in-row** — keep rows small; archive captured HTML/JSON to `vault/.whodex/raw/<run>/<obs>.json`. Enables re-extraction later (local-LLM lane) without re-fetching.

### 2.2 Source & provenance

```python
class Source(SQLModel, table=True):
    id: str = Field(primary_key=True)
    kind: SourceKind          # obsidian|google_contacts|linkedin_ext|linkedin_api|linkedin_rss|manual_cli|webhook|user|llm
    name: str                 # "Obsidian: ~/vault"
    trust: int                # base precedence rank — DATA, not code (see §6)
    config: dict = Field(sa_column=Column(JSON), default_factory=dict)
    enabled: bool = True

class SourceRun(SQLModel, table=True):
    id: str = Field(primary_key=True)
    source_id: str = Field(foreign_key="source.id", index=True)
    started_at: datetime
    finished_at: datetime | None = None
    status: RunStatus         # running|ok|partial|failed
    stats: dict = Field(sa_column=Column(JSON), default_factory=dict)
```

`trust` lives on `Source` so the precedence ranking is configuration, not a code constant.

### 2.3 Entity graph + contact profile

The existing `people-network` vault is already a typed graph:
- `People/*.md` are contactable people.
- `Organisations/*.md` are contact points with `parent`, `location`, `strategic tier`, and `employees`.
- `Locations/*.md` are first-class places with aliases.
- `Events/*.md` connect organizers, locations, participants, and follow-ups.

whodex should preserve and automate that shape. A person is not the only node type; it is the only node type that normally enters the reach-out queue. Organisations and locations are **contact points**: "who do I know at Kolai?", "who is in Frankfurt?", "which people around ALU have gone stale?" are graph queries, not string filters.

Routing uses folder, `type`, and tags together because the real vault is already useful but not perfectly normalized:

| Vault evidence | Entity kind/subtype |
|---|---|
| `People/**.md` or `type: Person` | `person` |
| `Organisations/**.md`, `type: Organisation`, or `tags` containing `Organisation` | `organisation`; `type` may be the subtype (`Startup`, university, association, ...). |
| `Locations/**.md` or `type: Location`/`City`/`Country`/`Address` | `location` with subtype from `type`. |
| `Events/**.md` or `type: Event` | `event`. |

The ingest layer must accept current drift as input: nested people folders, bare wikilinks (`[[Kolai]]`), aliased canonical links (`[[Organisations/Kolai|Kolai]]`), scalar placeholders (`Location`, `Unknown`), and mixed person-location keys (`lives`, `city`, `country`). The projector normalizes these into `EntityRef`s and `Edge`s; vault write-back proposes repairs instead of silently reshaping hand-written notes.

```python
class Entity(SQLModel, table=True):
    id: str = Field(primary_key=True)                       # ULID, stable, survives merges
    kind: EntityKind                                        # person|organisation|location|event
    subtype: str | None = None                              # Startup|University|City|Country|Event|...
    created_at: datetime
    merged_into: str | None = Field(default=None, foreign_key="entity.id", index=True)  # cache of merge UserAction
    archived: bool = False                                  # cache of archive UserAction; survives re-ingest (see §10)

    # --- projected current-state cache (all derived; nullable) ---
    display_name: str | None = None

    # --- obsidian binding ---
    vault_path: str | None = None
    vault_uid: str | None = Field(default=None, index=True)

class ContactProfile(SQLModel, table=True):                 # person-only reach-out cache
    entity_id: str = Field(foreign_key="entity.id", primary_key=True)
    job_title: str | None = None
    primary_email: str | None = None
    linkedin_url: str | None = None
    last_interaction_at: datetime | None = None
    next_reminder_at: datetime | None = None
    importance: int = 3
    cadence_days: int | None = None
```

Every denormalized field is reconstructable from the ledger; they exist purely so the TUI/scorer don't re-fold on every query. Existing `ContactState` naming in examples means "person `EntityState` plus `ContactProfile`" unless otherwise stated.

Organisations, locations, and events get lightweight projected summaries rather than person-style reminders: member count, stale-member count, unresolved-edge count, strategic tier, nearby/child locations, recent events, and open repair count. These summaries power contact-point dashboards without making every graph node a contact.

```python
class EntityIdentifier(SQLModel, table=True):        # normalized match keys for all node types
    id: str = Field(primary_key=True)
    entity_id: str = Field(foreign_key="entity.id", index=True)
    kind: IdKind            # email|phone|linkedin_url|google_resource|vault_uid|vault_path|canonical_name|wikilink
    value: str = Field(index=True)   # NORMALIZED: lowercased email, E.164 phone, canonical LI url, canonical note path/name
    asserted_by_run: str = Field(foreign_key="sourcerun.id")
    pinned: bool = False    # cache of identifier_pin UserAction; protects against auto-unmerge
    __table_args__ = (UniqueConstraint("kind", "value", "entity_id"),)
```

### 2.4 Interaction (touchpoints — NOT observations)

Observations describe *attributes of a person*; interactions describe *events between you and a person*. Distinct query patterns + many-to-many shape (a coffee with 3 people) earn them a table.

```python
class Interaction(SQLModel, table=True):
    id: str = Field(primary_key=True)
    kind: InteractionKind        # met|call|message|email|note|introduced
    occurred_at: datetime
    direction: Direction | None = None   # inbound|outbound|mutual
    channel: str | None = None           # "signal"|"linkedin_dm"|"irl"
    summary: str | None = None
    source_run_id: str | None = Field(default=None, foreign_key="sourcerun.id")
    created_at: datetime

class InteractionParticipant(SQLModel, table=True):
    interaction_id: str = Field(foreign_key="interaction.id", primary_key=True)
    entity_id: str = Field(foreign_key="entity.id", primary_key=True)
    role: str | None = None      # "introducer"|"introduced"
```

### 2.5 UserAction (replayable decisions)

User actions are not observations about a person. They are durable decisions over the system's derived state and must replay cleanly after rebuilding projections.

```python
class UserAction(SQLModel, table=True):
    id: str = Field(primary_key=True)
    action_type: UserActionType    # entity_create|pin|unpin|snooze|dismiss|ack_change|merge|unmerge|archive|cadence_set|identifier_pin|anti_merge|apply_graph_repair
    target_type: str               # entity|field|reminder|change|merge_candidate|identifier|graph_repair
    target_id: str = Field(index=True)
    entity_id: str | None = Field(default=None, foreign_key="entity.id", index=True)
    payload: dict = Field(sa_column=Column(JSON), default_factory=dict)
    created_at: datetime
    actor: str = "user"            # user|system
```

Examples:
- Pinning `job.title` writes `UserAction(action_type="pin", target_type="field", payload={"field": "job.title", "value": "Staff Engineer"})`.
- Dismissing a reminder writes `dismiss` against that reminder fingerprint; a future fingerprint can surface again.
- Accepting a merge writes `merge`; the current `Entity.merged_into` row is just the materialized cache of that action.
- Archiving an entity writes `archive`; `Entity.archived` is derived and re-ingest must respect it.
- Creating a new entity during identity resolution writes a system `entity_create` action so replay preserves stable entity IDs even before all source observations are re-folded.

### 2.6 Reminder, Change, ConflictSuggestion, GraphRepairSuggestion, Edge

```python
class Reminder(SQLModel, table=True):
    id: str = Field(primary_key=True)
    entity_id: str = Field(foreign_key="entity.id", index=True)  # normally person entities
    due_at: datetime = Field(index=True)
    reason: ReminderReason       # cadence_lapsed|data_stale|change_detected|manual
    status: ReminderStatus       # pending|done|snoozed|dismissed|satisfied
    snooze_until: datetime | None = None
    fingerprint: str             # hash of reasons — anti-spam dedup key
    payload: dict = Field(sa_column=Column(JSON), default_factory=dict)
    created_at: datetime

class Change(SQLModel, table=True):           # winner flipped in the projection
    id: str = Field(primary_key=True)
    entity_id: str = Field(foreign_key="entity.id", index=True)
    field: str
    old_value: Any = Field(sa_column=Column(JSON), default=None)
    new_value: Any = Field(sa_column=Column(JSON), default=None)
    caused_by_observation: str = Field(foreign_key="observation.id")
    detected_at: datetime
    significance: Significance   # trivial|minor|notable  (job/org change = notable)
    seen: bool = False
    notified: bool = False

class ConflictSuggestion(SQLModel, table=True):  # non-winning disagreement worth surfacing
    id: str = Field(primary_key=True)
    entity_id: str = Field(foreign_key="entity.id", index=True)
    field: str
    winning_observation_id: str = Field(foreign_key="observation.id")
    disagreeing_observation_id: str = Field(foreign_key="observation.id")
    reason: str                 # lower_trust_disagrees|pinned_disagrees|manual_review
    fingerprint: str = Field(index=True)
    status: str                 # open|accepted|dismissed
    detected_at: datetime
    last_seen_at: datetime

class GraphRepairSuggestion(SQLModel, table=True):  # deterministic vault graph maintenance
    id: str = Field(primary_key=True)
    repair_type: str             # missing_inverse|broken_wikilink|unresolved_ref|placeholder_ref|duplicate_entity|stale_membership|missing_note|template_drift
    src_entity_id: str | None = Field(default=None, foreign_key="entity.id", index=True)
    dst_entity_id: str | None = Field(default=None, foreign_key="entity.id", index=True)
    payload: dict = Field(sa_column=Column(JSON), default_factory=dict)
    fingerprint: str = Field(index=True)
    status: str                  # open|applied|dismissed
    detected_at: datetime
    last_seen_at: datetime

class Edge(SQLModel, table=True):             # the graph — plain edge list (§5)
    id: str = Field(primary_key=True)
    src_entity_id: str = Field(foreign_key="entity.id", index=True)
    dst_entity_id: str = Field(foreign_key="entity.id", index=True)
    type: EdgeType               # knows|introduced_by|met_at|works_at|member_of|lives_in|located_in|part_of|hosted_at|organized_by|attended|mentions|family|same_org|same_city|colleague
    directed: bool = True
    weight: float = 1.0
    source_run_id: str | None = Field(default=None, foreign_key="sourcerun.id")
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None         # null = current; set = historical
    __table_args__ = (UniqueConstraint("src_entity_id", "dst_entity_id", "type"),)
```

`Reminder`, `Change`, `ConflictSuggestion`, and `GraphRepairSuggestion` are **derived but materialized** so the user can snooze/dismiss/mark-seen/apply. Those state changes are stored as `UserAction` rows; status columns are caches for fast UI queries.

### 2.7 Vault file state (out-of-band edit + loop detection)

```python
class VaultFileState(SQLModel, table=True):
    path: str = Field(primary_key=True)
    whodex_uid: str | None = Field(index=True)
    last_content_hash: str                                  # authority for "did it change"
    last_frontmatter_seen: dict = Field(sa_column=Column(JSON))   # base for 3-way merge
    last_mtime: float                                       # cheap pre-filter only
    last_written_hash: str | None = None                    # what WE last wrote (echo suppression)
```

---

## 3. Markdown ↔ Log Reconciliation (the crux — unambiguous)

### 3.1 Vault schemas (typed notes, not person-only files)

The `people-network` templates become the Phase-1 compatibility target. whodex must read the current loose schema, normalize it internally, and write back minimal changes without forcing a vault-wide migration.

**Person note**

```yaml
---
type: Person
aliases: [Jane Doe]
source: [LinkedIn, Email]
organisations:
  - "[[Organisations/Kolai|Kolai]]"
lives: "[[Locations/Frankfurt am Main|Frankfurt]]"   # preferred over legacy city/country pair
city: "[[Locations/Frankfurt am Main|Frankfurt]]"     # accepted legacy input
country: "[[Locations/Germany|Germany]]"              # accepted legacy input
next contact: 2026-06-10
last contact: 2026-05-20
tags: [Person]
whodex:
  uid: 01J8X...
  last_sync: 2026-06-01T10:00:00Z
  projection_hash: "sha256:..."
  managed_fields: [organisations, lives, next contact, last contact]
---
```

**Organisation note**

```yaml
---
type: Startup                    # subtype; tag still includes Organisation
aliases: [Kolai]
parent: "[[Organisations/Parent Org]]"
location:
  - "[[Locations/Frankfurt am Main|Frankfurt]]"
industry: [GenAI]
strategic tier: key              # key|growth|maintain|none|no connection
employees:
  - "[[People/Felix Karg|Felix]]"
tags: [Organisation]
---
```

**Location note**

```yaml
---
type: City                       # City|Country|Address|Region
aliases: [Frankfurt, Frankfurt a. M.]
parent: "[[Locations/Germany|Germany]]"
city: "[[Locations/Freiburg|Freiburg]]"       # address notes only
country: "[[Locations/Germany|Germany]]"
tags: [Location]
---
```

**Event note**

```yaml
---
type: Event
datetime: 2026-06-01T18:00:00+02:00
location: "[[Locations/Frankfurt am Main|Frankfurt]]"
organizer: "[[Organisations/Kolai|Kolai]]"
tags: [Event]
---

### Participants
- [[People/Felix Karg|Felix Karg]]

### Follow-Up
- [ ] Message [[People/Jane Doe|Jane]]
```

Rules:
- The **body is never touched** except the marked edges block.
- Only frontmatter keys in a **known mapping** are read/written. Unknown keys are preserved verbatim.
- Use **`ruamel.yaml`** (not pyyaml/python-frontmatter's default dumper) so key order and comments survive — clean git diffs are load-bearing for the "git as history" bet. *(Resolved contradiction: fragments variously suggested `python-frontmatter` and `ruamel`; we pick `ruamel.yaml` for round-trip fidelity, wrapping it in our own frontmatter split so the body is byte-preserved.)*
- **Quote any value containing `[[`, `:`, or YAML specials** — unquoted wikilinks/colons break Obsidian's parser.
- Write everything to **frontmatter, not Dataview inline fields**, so both Dataview and the native **Bases** plugin give the user editable tables for free.
- Parse Obsidian wikilinks as structured refs: `[[path/to/Note|Alias]]` stores both canonical target path and display alias. The canonical path is the identity key; the alias is presentation. Bare links are resolved through an index of path stem, aliases, folder, and type; ambiguous bare links are quarantined as `GraphRepairSuggestion(repair_type="unresolved_ref")`.
- Preserve existing spelling (`next contact`, `last contact`, `strategic tier`) on write-back. Internally map to canonical dotted fields (`contact.next_at`, `contact.last_at`, `org.strategic_tier`).
- Prefer `lives` for person location write-back, but continue reading legacy `city`/`country`. If only `city`/`country` exist, do not rewrite them to `lives` without an explicit migration action.
- Maintain inverse graph facts as suggestions first, writes second: if a person lists `[[Kolai]]` in `organisations` and Kolai lacks that person in `employees`, create a `GraphRepairSuggestion`. Auto-write inverse lists only for opted-in managed fields.
- Treat placeholders (`Location`, `Organisation`, `Unknown`, `TODO`) and missing linked notes as repair candidates, not authoritative node names. Applying the repair can create a new note from the matching template, replace the scalar with a wikilink, or dismiss the placeholder.
- Do not trust inverse lists blindly: `employees` and event participant bodies may lag behind person-owned fields. The projection keeps provenance for both directions and marks the weaker/staler side as `stale_membership` instead of deleting it.

### 3.2 IN: Obsidian → log

The Obsidian connector is just another source emitting observations:

1. On `sync` (or a debounced `watchdog` event in daemon mode), scan `*.md` with frontmatter.
2. Compute `content_hash = sha256(frontmatter_bytes)`. Compare against `VaultFileState.last_content_hash`. **mtime is a cheap pre-filter; the hash is the authority** (git pulls and Obsidian sync can change mtime without content change and vice-versa).
3. **Echo suppression:** if `content_hash == last_written_hash`, this change was *our own* write-back → do **not** ingest.
4. Otherwise, diff the mapped frontmatter fields against the **current projection**. For each field where the file value differs, emit `Observation(source=obsidian, field, value=file_value, observed_at=git_commit_time_or_mtime, confidence=1.0)`. No diff → no observations (idempotent, no log spam).
5. New file with no `whodex.uid` → infer `Entity.kind` from `type`/folder, append system `entity_create`, then write the uid back (the one write even on a pure-read sync).

`observed_at` preference: `git log -1 --format=%cI <file>` when the vault is a git repo, else file mtime.

### 3.3 OUT: projection → Obsidian (anti-clobber, three-way merge)

When projection produces a new winning value for a *managed* field, for each such field hold three versions:
- `base` = `last_frontmatter_seen` (what whodex last read)
- `theirs` = current file value
- `ours` = new projected value

Then:

```
if theirs == base:                     # user didn't touch it since we last read
    write ours
else:                                  # user edited out-of-band since our last read
    ingest theirs as an obsidian observation FIRST   # the user's edit becomes a fact
    re-project                          # precedence decides the winner (obsidian trust 80)
    write the (possibly new) winner
```

**The anti-clobber invariant:** *never overwrite a field whose current file value has not already been ingested as an observation.* After writing, recompute and store `last_written_hash`. On the next IN scan, a hash match means "our echo" → skip (§3.2 step 3). Combined with the three-way base comparison, neither side clobbers the other, and there are no feedback loops.

This is the riskiest single piece of code in the system. It gets the most paranoid tests (§12, Layer 4) and **write-back is opt-in per managed field** initially. The `%% whodex:edges %%` block (§5) is simpler: whodex owns it, last-write-wins, no three-way merge (YAGNI; open question O4).

### 3.4 Why this is coherent

A user's Obsidian edit flows in as a trust-80 observation and beats a LinkedIn (trust-50) value for the same field by precedence rule §6.2. LinkedIn's contradicting value is still recorded and surfaces as a `ConflictSuggestion`. If the user *pins* the field, the pin action makes it permanent until an explicit unpin/accept action. Nothing is ever destroyed; both materializations are rebuildable folds.

---

## 4. Connectors & the Ingestion Hub

Every source — pull or push — collapses into one funnel:

```
producer → RawRecord → normalize → list[ObservationDraft] → hub-finalized Observations → append-only ledger → projection → Changes + ConflictSuggestions
```

Connectors differ *only* in how they acquire raw data and how they map fields. Everything downstream is shared. This is the "abstraction over shared concerns" layer.

### 4.1 The wire/transport types

```python
class RawRecord(BaseModel):
    """What a producer emits BEFORE field-mapping. Also the ingestion API wire format."""
    source: str                          # connector id, e.g. "google_contacts"
    identity: dict[str, str]             # identity keys → values, e.g. {"linkedin_url": "...", "email": "..."}
    payload: dict[str, Any]              # raw source-native fields, untouched
    observed_at: datetime
    capture_context: dict[str, Any] = Field(default_factory=dict) # {"page_url": ..., "ext_version": ...}
```

`RawRecord.identity` is separate from the resolved `entity_id`. **Identity resolution happens once, centrally, in the hub** — connectors never invent entity IDs; they only assert "here are the identity keys I can see." Dedup logic lives in exactly one place.

Connectors return observation drafts, not persisted observations. The hub owns IDs, source run binding, external refs, hashes, ingest timestamps, quarantine handling, and final validation.

```python
class ObservationDraft(BaseModel):
    field: str
    op: ObsOp = ObsOp.set
    value: Any = None
    observed_at: datetime | None = None
    confidence: float = 1.0
```

If `draft.observed_at` is absent, the hub uses `RawRecord.observed_at`. The observation factory canonicalizes values, computes `value_hash`, validates the field registry, mints the ULID, stamps `ingested_at`, and applies the idempotency key.

### 4.2 The Source protocol (capabilities, not a god-object)

We use a `Protocol` (not ABC): a connector is *any object with the right shape* — trivial to fake in tests, no inheritance ceremony. Capabilities are an explicit flag the hub checks (not `hasattr`).

```python
class Capability(Flag):
    PULL = auto(); PUSH = auto(); WRITEBACK = auto(); WATCH = auto()

class FieldSpec(BaseModel):
    canonical: str                       # "job.title"
    freshness_ttl_days: int | None = None  # feeds the freshness engine

@runtime_checkable
class Source(Protocol):
    id: str
    capabilities: Capability
    identity_keys: tuple[str, ...]       # keys this source can populate, priority order
    provides: tuple[FieldSpec, ...]      # declarative: drives freshness + "who can tell me X"
    def normalize(self, record: RawRecord) -> list[ObservationDraft]: ...   # ONLY mandatory method

class PullSource(Source, Protocol):
    def fetch(self, since: datetime | None) -> Iterable[RawRecord]: ...      # generator; `since` = incremental
class WatchSource(Source, Protocol):
    def watch(self, emit: Callable[[RawRecord], None]) -> AbstractContextManager: ...
class WritebackSource(Source, Protocol):
    def write_back(self, entity_id: str, state: dict[str, Any]) -> None: ...
```

**Key design move:** `fetch` returns the *same* `RawRecord` type the Firefox extension POSTs. So a pull source and a push source converge at `normalize`, and everything after is identical. A pull source just polls instead of being polled.

### 4.3 Declarative field mapping (most connectors are one line)

```python
@dataclass
class FieldMap:
    source_path: str                     # dotted path into payload, "organizations.0.title"
    canonical: str                       # "job.title"
    transform: Callable[[Any], Any] | None = None
    skip_if_empty: bool = True

def apply_map(record, fields) -> list[ObservationDraft]: ...
```

```python
class GoogleContacts:
    MAP = [
        FieldMap("names.0.displayName", "name.full"),
        FieldMap("emailAddresses.0.value", "email", transform=str.lower),
        FieldMap("organizations.0.title", "job.title"),
        FieldMap("organizations.0.name", "job.org"),
    ]
    def normalize(self, record): return apply_map(record, self.MAP)
```

The map is an **implementation detail of the connector**, never a core registry. The only shared vocabulary is the append-only canonical field list in one `fields.py`. Connectors with weird payloads (LinkedIn HTML) just write imperative `normalize`.

### 4.4 The hub

```python
class IngestionHub:
    def ingest(self, record: RawRecord, source_run_id: str) -> IngestResult:
        source = self.registry.get(record.source)        # KeyError → 422 unknown source
        raw_ref = self.raw_store.put(record)              # archive FIRST, always
        drafts = source.normalize(record)
        entity_id = self.identity.resolve(record.identity, hint_source=record.source)
        obs = [
            self.observation_factory.from_draft(
                draft=d,
                source_run_id=source_run_id,
                entity_id=entity_id,
                external_ref=self.identity.primary_ref(record.identity),
                raw_ref=raw_ref,
            )
            for d in drafts
        ]
        self.ledger.append_observations(obs)              # immutable append
        result = self.projector.apply(obs)                # projection changes + conflict suggestions
        for event in result.events_to_publish: self.bus.publish(event)
        return result
```

The hub is a plain library object; **FastAPI is just one caller**:

```python
@app.post("/ingest", status_code=202)
def ingest(records: list[RawRecord], _=Depends(require_token)):
    try:
        result = hub.ingest_batch(records)
    except KeyError as e:
        raise HTTPException(422, f"unknown source: {e}")
    return {"accepted": len(records), "changes": result.change_count, "conflicts": result.conflict_count}
```

**Push and pull use the exact same `hub.ingest`.** A pull connector's `fetch()` yields `RawRecord`s; the runner loops them through `ingest`. One normalization/projection/change-detection path.

> **Resolved contradiction — DTO vs domain `Observation`.** The connectors fragment had `normalize` return `Observation` directly; the layout fragment insisted the API wire shape (`RawRecord`/schemas) stay separate from `domain.Observation`. We keep both boundaries clean: `RawRecord` is the wire/source boundary, `ObservationDraft` is the connector output, and the hub is the only place that creates persisted `Observation`s. This stops browser-extension JSON and connector partials from leaking into core persistence types.

### 4.5 Plugin discovery — entry points (not folder scanning)

```python
class Registry:
    def load(self):
        for ep in entry_points(group="whodex.sources"):
            src = ep.load()()                # factory
            self._sources[src.id] = src
    def with_capability(self, cap): return [s for s in self._sources.values() if cap in s.capabilities]
```

Entry points make a connector a real installable package, are introspectable, and need zero core changes. Built-in connectors register the same way in whodex's own `pyproject.toml` — no first-party special-casing.

### 4.6 Worked example — add a brand-new source, zero core changes

```python
# whodex_mastodon/__init__.py
class Mastodon:
    id = "mastodon"
    capabilities = Capability.PULL
    identity_keys = ("mastodon_acct", "name.full")
    provides = (FieldSpec("social.mastodon", freshness_ttl_days=90), FieldSpec("name.full"))
    MAP = [FieldMap("acct", "social.mastodon"), FieldMap("display_name", "name.full")]
    def fetch(self, since):
        for acct in following_since(since):
            yield RawRecord(source="mastodon", identity={"mastodon_acct": acct["acct"]},
                            payload=acct, observed_at=now())
    def normalize(self, record): return apply_map(record, self.MAP)

def make(): return Mastodon()
```

```toml
# plugin package pyproject.toml
[project.entry-points."whodex.sources"]
mastodon = "whodex_mastodon:make"
```

`pip install whodex-mastodon` → appears in `whodex sync` automatically. The only conceivable shared touch is adding a canonical field to the append-only `fields.py` vocabulary.

### 4.7 Phase-1 connectors (grounded in research)

**Google Contacts — `PULL`.** OAuth2 auth-code + offline (refresh token). Scope `contacts.readonly`. **Set the OAuth consent screen to Production** (Personal-Use allowance, no verification review needed) to avoid the 7-day refresh-token expiry in Testing mode. `people.connections.list` with `personFields=names,emailAddresses,phoneNumbers,organizations,addresses,urls,metadata`. Use `requestSyncToken=true` → store `nextSyncToken` → incremental sync returns only changed/deleted contacts (Google does the diffing). Map `metadata.sources[].updateTime → observed_at`. On `EXPIRED_SYNC_TOKEN` fall back to a full sync. Lib: `google-api-python-client` + `google-auth-oauthlib`. Identity keys: `("google_resource", "email")`.

**Obsidian vault — `PULL + WATCH + WRITEBACK`.** The bidirectional one (§3). `watchdog` for daemon mode, debounced, loop-guarded. Identity keys: `("vault_uid", "email", "linkedin_url")`.

**LinkedIn — a strategy bundle, all prongs emit `RawRecord(source="linkedin", …)`:**
- **(c) Firefox WebExtension (PRIMARY, `PUSH`)** — passive capture of profiles you genuinely view; lowest ban risk of the active options (§9).
- **(a) Third-party content API (FALLBACK, `PULL`)** — Proxycurl-style, paid, cost-gated, on-demand only. *Note: Proxycurl was sued by LinkedIn and shut down in 2025; treat any such vendor as volatile — this is exactly why it sits behind the connector interface.*
- **(d) RSS (OPPORTUNISTIC, `PULL`)** — largely gone for individual profiles; viable at most for company/job-posting feeds. Not a job-change source. Job-change detection comes from the extension capturing `job.org/job.title` over time → projection diffs it.

Identity key: canonical `linkedin_url`; `name.full` only as a weak tie-break, never a hard match.

---

## 5. The Graph

Edges live in the SQLite `Edge` table — a plain edge list over typed `Entity` nodes, correct for a single-user graph of hundreds–low-thousands of contacts. No graph DB (YAGNI). Queries (mutual connections, "introduced by Y", "who do I know at Acme", "who is in Frankfurt", "which events created these ties") are `WHERE`/self-joins or a tiny on-demand `networkx` load.

- Edges are **projected from observations and vault structure**: person `organisations` → `member_of`, organisation `employees` → inverse `member_of`, person `lives`/`city`/`country` → `lives_in`, organisation `location` → `located_in`, organisation `parent` → `part_of`, event `location` → `hosted_at`, event `organizer` → `organized_by`, event participants block → `attended`, body `[[wikilinks]]` → low-confidence `knows`/`mentions`.
- `same_org`, `same_city`, and `colleague` are derived edges from shared contact points. They are generated/cached, never written to frontmatter as authoritative facts.
- All explicit edges carry provenance and **bitemporal validity** (`observed_at`, `valid_from`, `valid_to`) so "worked together 2019–2022" is expressible and a past `member_of` becomes historical, not deleted.
- Graph repair is a first-class automation lane. The projector emits `GraphRepairSuggestion`s for missing inverse links, stale organisation employee lists, broken wikilinks, duplicate location notes (`Frankfurt` vs `Locations/Frankfurt am Main`), unresolved scalar places (`Sydney` without `[[Locations/Sydney]]`), and unknown placeholder nodes.
- Applying a repair is a `UserAction`; the vault writer then performs the minimal frontmatter/body edit. This lets whodex speed up maintenance without silently restructuring the vault.
- Repair suggestions are deterministic and batchable: each has a fingerprint from `(repair_type, src_ref, dst_ref, proposed_patch_hash)`. Re-running sync updates `last_seen_at` only, so a review queue can safely offer "apply all missing inverse links" or "create all missing locations" without generating duplicates.
- Suggested note creation uses the existing vault templates, with the smallest safe frontmatter: `type`, `aliases`, inferred parent/location links, and `whodex.uid`. It never invents body prose.
- **Surfaced in Obsidian (optional, append-only)** in a marked block whodex solely owns:
  ```markdown
  %% whodex:edges:start %%
  - knows: [[John Smith]] (met at PyCon 2024)
  - attended: [[Events/CloudFest 2025]]
  - contact point: [[Organisations/Kolai]] · [[Locations/Frankfurt am Main|Frankfurt]]
  %% whodex:edges:end %%
  ```
- Graph **centrality is a P2 nudge** in scoring, never a pillar.

### 5.1 Contact-point queries

The user-facing payoff of the graph is maintenance plus retrieval:
- **By organisation:** "show people at/near Kolai", "who do I know at ALU?", "which key organisations have no warm contact?"
- **By location:** "who is in Frankfurt this week?", "who moved cities?", "which locations contain stale unknowns?"
- **By event:** "who did I meet at Entrepreneurship?", "what follow-ups are still open?"
- **By repair queue:** "add missing inverse employee links", "turn plain `Sydney` into `[[Locations/Sydney]]`", "create missing organisation/location note from template."

These are graph operations over `Entity`/`Edge`, not text search. The TUI should expose them as filtered views and review actions, while Obsidian remains the editable source.

### 5.2 Graph maintenance automation

The maintenance loop is:

1. Build a vault index: canonical path, basename, aliases, `type`, tags, outgoing refs, and incoming refs.
2. Normalize each mapped frontmatter/body reference to `EntityRef`, preserving the raw spelling.
3. Project explicit edges with provenance from both directions.
4. Derive contact-point summaries (`org -> people`, `location -> people/orgs/events`, `event -> participants`).
5. Emit graph repairs for any deterministic mismatch.

Initial repair types:

| Type | Example | Proposed action |
|---|---|---|
| `missing_inverse` | person has `organisations: [[Kolai]]`, Kolai lacks employee | append person to `employees` |
| `stale_membership` | org lists employee but person no longer lists org and LinkedIn says new org | mark historical or remove inverse after review |
| `unresolved_ref` | `[[Kolai]]` matches multiple notes or none | choose canonical note or create one |
| `placeholder_ref` | `location: Location` | replace with selected location link or dismiss |
| `broken_wikilink` | link target missing after rename | update to resolved canonical path |
| `duplicate_entity` | `Sydney` and `Locations/Sydney` both exist | merge/archive after review |
| `missing_note` | Google/LinkedIn names an org not in vault | create organisation note from template |
| `template_drift` | org note has `type: Startup` but no `tags: [Organisation]` | add missing routing tag |

Repairs are allowed to touch only the field/block they propose. If a proposed patch would rewrite unrelated YAML or body bytes, it is invalid.

---

## 6. Precedence / Conflict Resolution

### 6.1 The comparator

For one scalar field of one contact, the winning observation is the **max under this lexicographic key** (higher wins) over all live observations for that `(contact, field)`:

```
key(obs) = (
  1 if field/value is pinned by UserAction else 0,  # (A) manual lock beats everything
  source.trust,                              # (B) configurable trust rank (DATA, not code)
  obs.observed_at,                           # (C) newest fact wins
  obs.ingested_at,                           # (D) tie: most recently learned
  obs.confidence,                            # (E) tie: surest
  obs.id,                                    # (F) ULID — total deterministic order
)
```

### 6.2 Default trust ranks (all overridable in config)

| Source | Trust |
|---|---|
| manual_cli | 100 (pin lock comes from `UserAction` field A) |
| obsidian | 80 |
| google_contacts | 60 |
| linkedin_ext (browser) | 50 |
| linkedin_api (paid) | 40 |
| linkedin_rss | 30 |
| webhook / unknown | 20 |
| llm (later) | 25 |

### 6.3 Rules in prose

1. **Manual/pinned > everything.** A pinned value cannot be overwritten by any connector; the connector's newer fact is still logged and surfaces as a `ConflictSuggestion`/"LinkedIn disagrees — accept?" item, but does not win until the user unpins or accepts it.
2. **Otherwise higher trust wins, regardless of recency** — a fresh LinkedIn scrape does not override what the user typed in Obsidian for the same field.
3. **Within equal trust, newest `observed_at` wins.**
4. Ties broken by `ingested_at` → `confidence` → `id`, so projection is **fully deterministic and reproducible** (replaying the ledger always yields identical state — essential for testability).
5. Multi-valued fields union across sources; a higher-or-equal-trust `remove`/`assert_absent` dated after the latest `add` deletes a member.
6. A `Change` is emitted **only when the winning projected value flips**. A non-winning but materially different value emits/updates a `ConflictSuggestion` instead. Re-ingesting the same data produces neither.

### 6.4 What counts as a notifiable "change"

- `null → value` (first-ever observation): **not** a "changed" alert — it's an initial fill.
- `value → different-value`: a `Change` (notable if the field is volatile: job title, organisations, location/contact points).
- `value → null` (`assert_absent` wins): a minor `Change`.
- Normalization-only diffs ("SWE @ X" vs "Software Engineer at X"): **not** a change — values are compared after canonicalization. (This rule is the most-tested-yet-underspecified one; nailed down in projection tests.)

### 6.5 What counts as a conflict suggestion

- A lower-trust source reports a materially different value from the winner on a user-visible field.
- A pinned/manual value blocks a newer source value.
- Multiple strong identifiers point at different contacts during identity resolution.
- The suggestion is fingerprinted by `(contact, field, winning_hash, disagreeing_hash, source)` so repeated syncs update `last_seen_at` but do not spam the review queue.

### 6.6 `observed_at` honesty for date-less sources

Google rarely says *when* a field became true. Policy: when a source can't provide a real `observed_at`, it falls back to `ingested_at` **but** its effective recency is discounted (per-source flag `observed_at_is_unknown`) so a stale Google sync doesn't out-rank an older-but-correct value of equal trust. (Open question O2 — exact discount rule to finalize before projection tests.)

---

## 7. Identity Resolution

Goal: one stable `Entity` per real person, organisation, location, or event across Google + LinkedIn + Obsidian, with safe auto-merge and an escape hatch. Person identity is stricter than organisation/location identity; never merge across different `Entity.kind`.

**Match keys** (normalized): email (lowercased, gmail dot/plus-stripped), phone (E.164), canonical LinkedIn URL, Google `resourceName`, `vault_uid`. **Name alone is never a hard key** — at most a tie-break.

**`resolve(identity, hint_source) -> entity_id | NEW | QUARANTINE`:**
1. Exact hit on a strong identifier → that entity.
2. Multiple strong identifiers in the incoming record map to *different* existing entities → **do not auto-merge.** Resolve to the highest-trust one, record a `MergeCandidate` for user confirmation.
3. Strong key with no hit → append system `entity_create`, create identifiers, and resolve to the new stable entity.
4. No strong key at all → **Phase-1 policy: quarantine** with a `needs_review` flag surfaced in the TUI (cheaper and cleaner than auto-creating duplicate contacts; deterministic dedup with `rapidfuzz` name+org as a *suggestion* only).
5. Follow `merged_into` tombstones transitively so old external refs resolve to the survivor.

```python
class MergeCandidate(SQLModel, table=True):
    id: str = Field(primary_key=True)
    entity_a: str; entity_b: str        # same Entity.kind only — never merge across kinds
    score: float
    reasons: dict = Field(sa_column=Column(JSON), default_factory=dict)   # {"shared_email":..., "name_sim":...}
    status: str                                     # suggested|accepted|rejected
```

**Merge (UserAction + tombstone projection, not history rewrite).** Accepting a merge appends `UserAction(action_type="merge", payload={"loser": ..., "survivor": ...})`; materialization sets loser's `merged_into = survivor`. Observation rows stay immutable (their `entity_id` may still point at the loser); the projector resolves through the chain. Identifiers and edges are projected/queried through the survivor; no history rewrite. *(Resolved contradiction: the purist "emit identity.merge observations" alternative is wrong vocabulary — a merge is a user decision, not a fact from a source.)*

**Unmerge / false-merge:** reversible because observations keep their `external_ref` — append an `unmerge` action, rematerialize `merged_into`, and re-partition observations by original ref. Users can `pin` an identifier (force "same") or append an `anti_merge` action (force "never same") so the heuristic never re-suggests a rejected pair. Pinned decisions always beat heuristics.

---

## 8. Engine: Prioritization, Freshness, Reminders, Notifications

The engine reads only the projection (`EntityState`/person `ContactProfile`), never connectors or the raw ledger.

### 8.1 Prioritization — one pure, explainable function

```python
def score_contact(c: ContactProfileState, cfg: ScoringConfig, now: datetime) -> Score: ...
```

| Signal | Derivation | Role |
|---|---|---|
| `overdue_ratio` | `days_since_last_interaction / cadence_days` | primary driver; 1.0 = due |
| `tier_weight` | `cfg.tier_weight[tier]` | inner-circle multiplier |
| `event_boost` | Σ over `open_changes` of `cfg.event_weight[kind]` | decaying bump for job/move/birthday — makes it feel smart |
| `centrality` | graph projection | mild P2 tie-breaker |
| `pin` | user | **floor** — pinned never sinks below threshold |
| `snooze` | user | **gate** — `snoozed_until > now` ⇒ excluded |

```python
if c.snoozed_until and c.snoozed_until > now:
    return Score(NEG_INF, reasons=["snoozed"])
base = (cfg.w_overdue   * clamp(overdue_ratio, 0, cfg.overdue_cap)
      + cfg.w_event     * event_boost
      + cfg.w_centrality* c.centrality) * tier_weight
value = max(base, cfg.pin_floor) if c.pinned else base
```

Design rules: **linear weighted sum, not ML** (explainable — every `Score` carries `reasons: list[str]` driving the TUI's *why-now*). `overdue_ratio` not raw days (comparable across cadences). `overdue_cap` (~3.0) stops a 5-year-abandoned contact pinning the top forever. **Gates (snooze) vs floors (pin) vs additive (event)** model different intents and stay distinct. Pins are a *separate top bucket*, not a giant number. Weights live in config; resist adding signals until the simple set proves insufficient. A future `llm_signal` plugs in as one more weighted addend with **zero change to the function's shape** — the proof the abstraction is right.

### 8.2 Freshness — per-field, config-driven, independent of priority

A stale field means "re-verify the data," not necessarily "reach out."

```toml
[freshness.job_title]  ttl_days = 90   recheck = true
[freshness.location]   ttl_days = 120  recheck = true
[freshness.email]      ttl_days = 365  recheck = false
[freshness.birthday]   ttl_days = 0    # never stale
```

```python
def staleness(fs: FieldState, cfg, now) -> Staleness:   # FRESH | STALE | EXPIRED
    ttl = cfg.ttl_days[fs.field]
    if ttl == 0: return FRESH
    age = (now - fs.ingested_at).days        # freshness uses ingested_at (when WE last saw it)
    if age < ttl: return FRESH
    return STALE if age < ttl * cfg.grace_factor else EXPIRED
```

**Lifecycle stale → re-check → changed → notify/review.** A `RecheckTask` (rows in a `task` table: `contact, field, connector, state, attempts, next_attempt_at`) is enqueued when a field goes STALE *and* a pull-capable connector provides it (passive sources like the extension need no re-check — they push when you browse). Both daemon and one-shot `sync` drain the same queue → scheduling stays non-load-bearing. A re-check that **confirms** the value refreshes freshness but emits **no** `Change`; a re-check that **differs and wins** emits a `Change`; a re-check that **differs but loses** emits/updates a `ConflictSuggestion`. **Expensive sources (paid LinkedIn API) are never auto-rechecked** — on-demand / user-approved only (cost + privacy).

**What "confirmed" means** (two separate clocks): re-seeing the same value (e.g. on LinkedIn) refreshes the *field's* `last_confirmed` but does **not** reset the *reach-out clock* — only a logged interaction does that.

### 8.3 Reminders — idempotent, anti-spam

Generated during a `sync`/daemon tick after scoring; keyed by person `entity_id` with a `fingerprint` = hash of reasons.

- `score >= cfg.reminder_threshold and not snoozed` → **upsert** a Reminder (never duplicate an open one for the same contact).
- Re-notify only if `fingerprint` changes (a new reason appeared, e.g. job change on top of overdue) or on first fire. `sync` ten times in a row → at most one notification.
- **"I contacted them" resets the clock with no special case:** logging an interaction recomputes `last_interaction_at` → `overdue_ratio` drops below threshold → next scoring marks the reminder `satisfied`. It falls out of the score dropping.
- **Snooze** = time-based hard gate. **Dismiss** = reason-based suppression until `fingerprint` changes. (Kept distinct; flagged O-engine for a usability check — collapse to snooze-only if confusing.)

### 8.4 Change / ConflictSuggestion → Notification

```
Change / ConflictSuggestion    Reminder fired (from engine)
             \                  /
              ▼                ▼
   Notification(kind, entity_id, payload, dedupe_key, created_at)   # append-only, state=PENDING
                         │
              NotificationDispatcher.dispatch(pending)
              ┌──────────┼─────────────┐
              ▼          ▼             ▼
        TUINotifier  TelegramNotifier  EmailNotifier
        (Phase 1)    (later)           (later)
```

- `dedupe_key = f"{kind}:{entity_id}:{fingerprint}"`; dispatcher skips an already-`SENT` key (second idempotency layer: engine dedupes *generation*, dispatcher dedupes *delivery*).
- Notifications are **decoupled in time from generation**: a one-shot `sync` may generate while nothing is listening; they sit `PENDING` and dispatch when the TUI opens or the daemon's Telegram sink runs. `delivered_to: set[sink]` lets the same event go to TUI now and Telegram later without re-firing. This is what makes "run irregularly" and "always-on" the *same mechanism*.

Conflict suggestions are usually TUI/review-queue items, not push notifications, unless the field is configured as high-signal (`job.title`, `person.organisations`, `person.lives`, `org.location`) or the current value is pinned and the new source is recent.

A change notification renders as:
```
Anna R. · title · "Senior Engineer" → "Staff Engineer"
   source: linkedin-ext · observed 2026-05-30 · prev confirmed 2026-01-12
   suggested: reach out to congratulate
```

---

## 9. Front-ends, the Headless Facade, and the Firefox Extension

### 9.1 The facade — the only thing any client calls

```python
class Whodex:                       # constructed with a Session + config; NO UI imports
    # reads → plain pydantic DTOs (never ORM rows, never UI types)
    def priority_queue(self, limit=50, include_snoozed=False) -> list[RankedContact]: ...
    def contact(self, id) -> ContactDetail: ...             # person entity + ContactProfile
    def entity(self, id) -> EntityDetail: ...                # person|organisation|location|event
    def timeline(self, id) -> list[TimelineItem]: ...        # interactions + changes interleaved
    def review_queue(self) -> list[ReviewItem]: ...        # MergeCandidate + ConflictSuggestion + GraphRepairSuggestion + quarantined records
    def people_at(self, entity_id) -> list[RankedContact]: ...       # organisation/location/event contact point
    def contact_points(self, id) -> list[EntitySummary]: ...         # orgs/locations/events around a person
    def graph_repairs(self) -> list[GraphRepairSuggestion]: ...
    def open_changes(self) -> list[Change]: ...
    def pending_notifications(self) -> list[Notification]: ...
    # writes → each appends an Observation/task, returns new projected state
    def log_interaction(self, id, kind, note, when=None) -> ContactDetail: ...
    def pin(self, id, on: bool) -> RankedContact: ...
    def snooze(self, id, until) -> RankedContact: ...
    def dismiss_reminder(self, id) -> None: ...
    def acknowledge_change(self, change_id) -> None: ...
    def apply_graph_repair(self, repair_id) -> None: ...
    def resolve_merge(self, candidate_id, decision) -> None: ...
    def set_cadence(self, id, days) -> RankedContact: ...
    # orchestration — what `sync` and the daemon call
    def ingest(self, records: list[RawRecord]) -> IngestResult: ...
    def run_sync(self, sources: list[str] | None = None) -> SyncReport: ...
    def drain_tasks(self, max=...) -> None: ...
    def dispatch_notifications(self) -> None: ...
```

CLI `whodex sync` = `run_sync()` + `drain_tasks()` + `dispatch_notifications()`. Daemon = the same three on a loop. FastAPI's `/ingest` is a thin wrapper around `ingest`. Web and Telegram (later) only ever call these methods and only ever implement `Notifier` — adding a front-end is a new adapter module + a config entry, **zero engine/schema change**.

### 9.2 The Notifier protocol

```python
class Notifier(Protocol):
    name: str
    def supports(self, n: Notification) -> bool: ...
    def send(self, n: Notification) -> DeliveryResult: ...   # idempotent per dedupe_key
```

`NotificationDispatcher` holds `list[Notifier]`, asks `supports()`, calls `send()`, records `delivered_to`. Sinks are configured: `[notifiers] enabled = ["tui", "telegram"]`.

### 9.3 Textual TUI (Phase 1, minimal but useful)

Five screens, all through `Whodex`:
1. **Priority Queue (home)** — ranked rows: name, tier, why-now (`"2.3× overdue · job changed"`), days-since. Keys: `enter` detail, `l` log, `s` snooze, `p` pin, `j/k` nav. Banner shows pending-notification/open-change count.
2. **Contact Detail** — projected fields with per-field freshness dot (fresh/stale/expired), contact points (organisations, locations, events), interleaved timeline (interactions + changes), open changes with `a` to acknowledge, `e` edit cadence.
3. **Contact Points** — organisation/location/event views: people at this node, stale people, open follow-ups, missing inverse links, and "create note from template" actions.
4. **Review / Maintenance Queue** — `MergeCandidate`s + `ConflictSuggestion`s + `GraphRepairSuggestion`s + quarantined unmatched records; accept/reject/apply.
5. **Log Interaction** (modal, one keypress from anywhere) — kind + note + date, optionally attach organisation/location/event context.

Out of Phase-1 TUI: force-directed graph viz, analytics, config editing (edit TOML/frontmatter directly — Obsidian-first). YAGNI.

### 9.4 Firefox WebExtension

- **Manifest V3, Event Pages.** Content script on `*.linkedin.com/in/*` reads already-rendered DOM (name, headline, current title+company, location, profile URL) on a real page view; debounced; one profile → one `RawRecord`.
- **MV3 request pattern:** content script extracts → `runtime.sendMessage` → **background Event Page does the cross-origin `fetch` POST** (MV3 content-script requests are subject to page CORS; background fetch is the reliable route).
- **Endpoint:** POST to the **VPS ingestion endpoint over HTTPS** (recommended primary; MV3's `upgrade-insecure-requests` rewrites `http://localhost` → https, so localhost needs HTTPS/CSP handling).
- **Auth:** a long-lived bearer token issued by `whodex token issue --label firefox`, pasted into the extension options, stored in `browser.storage.local`, sent as `Authorization: Bearer …`, validated against a small revocable token table.
- **Posts a `RawRecord`** `{source:"linkedin", identity:{linkedin_url}, payload:{name,headline,title,company,location}, observed_at, capture_context:{page_url, ext_version, capture:"passive_view"}}`.
- **Keep it fully separable** so it can be dropped for the paid API without touching core.

---

## 10. Edge Cases Worth Designing For

1. **Conflicting sources** (Google=Berlin, LinkedIn=Munich): both kept in the log; projection picks by §6; detail view shows "also seen: Berlin (Google, 4mo ago)." Conflicts are *visible*, never hidden.
2. **Manual edit vs ingestion** (the core promise): user/Obsidian values are high trust and never silently overwritten; a contradicting ingestion becomes a `Change`/"accept?" suggestion, not a clobber.
3. **Two writers on a git-tracked file**: Obsidian authoritative on read; whodex writes idempotent + minimal (re-write same state → byte-identical file → clean git diff); re-read before writing if the file changed.
4. **Unmatched LinkedIn captures**: land in the quarantine/review queue, not the main graph, until promoted — casual browsing doesn't pollute the contact list.
5. **Future-dated/tentative facts** ("moving to Lisbon in fall"): store the note verbatim; don't build temporal-validity logic in Phase 1; let the user confirm when real. Don't lose the info.
6. **Deletion / "don't track this entity"**: append an `archive` UserAction keyed by entity/external ID; `Entity.archived` is the materialized tombstone and survives re-ingestion (a re-sync must not resurrect it).
7. **Privacy**: this is a dossier on real people. Local-first SQLite + git vault; ingestion API token-gated, bound to localhost or the user's own HTTPS endpoint, never public; no third-party analytics ever; paid-API lookups are explicit/opt-in per lookup (they send PII to a vendor), never a silent sweep.

---

## 11. Package / Module Tree & Dependency Directions

Dependency rule, enforced in CI by **`import-linter`**: **`domain` depends on nothing beyond pydantic/stdlib; SQLModel/SQLAlchemy live only in `store.sqlite`; everything depends on `domain`; UI/connectors/api never depend on each other; no cycles.**

```
src/whodex/
├── domain/          # PURE. pydantic models + value objects. zero IO, no ORM.
│   ├── models.py    #   Entity, EntityRef, Observation, ObservationDraft, Interaction, UserAction, EntityState, ContactProfileState, FieldState, Reminder, Change, ConflictSuggestion, GraphRepairSuggestion, Edge
│   ├── fields.py    #   the closed, append-only canonical field registry
│   ├── clock.py     #   Clock protocol, SystemClock, FixedClock
│   └── ids.py       #   IdFactory protocol + impls (ULID; Sequential for tests)
├── projection/      # PURE fold: event streams -> EntityState (+ Changes/ConflictSuggestions/GraphRepairs)
│   ├── project.py
│   └── conflict.py  #   the §6 precedence comparator
├── engine/          # PURE decisions over projected state
│   ├── scoring.py · reminders.py · freshness.py · identity.py
├── store/           # persistence behind interfaces; ORM rows + mappers live here
│   ├── interfaces.py · memory.py · sqlite.py · rows.py · mappers.py
├── sources/         # ingress connectors; each depends on domain only
│   ├── base.py      #   Source protocol, Capability, apply_map helper
│   ├── google.py · obsidian.py
│   └── linkedin/    #   ext.py (ingestion-fed) · api.py · rss.py
├── vault/           # Obsidian FS adapter + markdown (de)serialization
│   ├── interface.py · fs.py · markdown.py   # render/parse — the round-trip core (ruamel)
├── ingestion/       # FastAPI app: universal POST ingress
│   ├── app.py (create_app(deps)) · routes.py · schemas.py   # RawRecord/API wire types ≠ domain
├── sync/            # ORCHESTRATION; daemon & one-shot share this
│   └── engine.py    #   run_sync(...), the IngestionHub + runner
├── notifiers/       # output side effects behind Notifier protocol
│   ├── interface.py · impls.py   # TUINotifier/Console p1; telegram/email later
├── enrich/          # LATER LANE seam, stubbed now
│   └── interface.py #   Enricher/Embedder protocols + NullEnricher
├── tui/             # Textual app; depends on engine/store interfaces only
├── cli/             # Typer: whodex sync | serve | tui | token | merge
└── config/          # pydantic-settings; THE composition root (only module allowed to import widely)
    └── settings.py
```

| Module | Responsibility | Depends on |
|---|---|---|
| `domain` | vocabulary: immutable pydantic models + Clock/Id protocols | **stdlib + pydantic only** |
| `projection` | fold event streams → entity graph state + Changes/ConflictSuggestions/GraphRepairs; precedence | `domain` |
| `engine` | score/reminders/freshness/identity (pure) | `domain` |
| `store` | persist/read ledger events & projections; map SQLModel rows ↔ domain models | `domain`, SQLModel/SQLAlchemy |
| `sources` | normalize external data → ObservationDrafts | `domain` (+ injected `httpx`, `vault`) |
| `vault` | Obsidian FS + markdown round-trip | `domain` |
| `ingestion` | HTTP ingress for arbitrary producers | `domain`, `store`, `engine` (via DI) |
| `sync` | orchestrate a run (the hub + runner) | all of the above |
| `notifiers` | deliver reminders/changes/conflict alerts | `domain` |
| `tui` | presentation | `engine`, `store` interfaces |
| `cli` | process entrypoints | `sync`, `ingestion`, `tui`, `config` |
| `config` | load settings, assemble the graph | everything (wiring) |

Key boundaries: `ingestion/schemas.py` (wire) is deliberately separate from `domain/models.py` (a tested mapping converts between them). `sync` is the **only** place daemon vs one-shot differ — both call `run_sync`; scheduling is a thin wrapper (systemd `OnCalendar=hourly → whodex sync`, or an APScheduler loop in `serve`). `config` is the composition root; tests build their own graph from fakes without going through it.

---

## 12. Testing Strategy

**The one idea:** push impurity (clocks, HTTP, disk, SQLite, LinkedIn, LLMs) to the edges; keep the middle pure; test the middle exhaustively with `given events → assert X`. If a piece of logic needs a DB, network, or `datetime.now()` to test, that's a design smell — refactor.

**Principles.** Behavior over implementation (assert *decisions*, not internals — lets you swap in-memory fold for incremental SQL projection without touching tests). Domain vocabulary in test names (`test_obsidian_edit_wins_over_stale_linkedin_value`). **The event ledger is the fixture format** — tiny builders like `obs(...)`, `interaction(...)`, and `action(...)` are the highest-leverage testing investment. Determinism mandatory: time and IDs are always injected; a flaky test is a seam bug.

**The seams (the only abstractions needed for testability):**
1. **Clock** — `Clock` protocol; `FixedClock(t)` with `.advance()`. Prefer passing `now: datetime` directly into pure functions; inject `Clock` only into orchestration. `freezegun` only as a fallback for code we don't own.
2. **Source protocol** — `FakeSource(records=[...])` emits canned `RawRecord`s, can raise, can record that `since` was honored.
3. **Vault** — interface over a directory; tests point at `tmp_path` (real temp dir, catches real YAML/encoding bugs — no `open()` mocking).
4. **HTTP** — injected `httpx.Client`; `respx` mocks at transport level (real serialization, no live calls).
5. **Stores** — `LedgerStore`/`ProjectionStore` interfaces; in-memory list-backed for unit tests, real SQLite (`:memory:` / temp file) for integration.
6. **IdFactory** — `SequentialIdFactory` for stable snapshots.
7. **Enricher/Embedder** — stubbed now (`NullEnricher`), so the LLM lane drops in later; tests inject `FakeEnricher`.

**Layers (rough proportions: 70% pure unit / 20% integration / 10% e2e+TUI):**
- **L1 pure unit (bulk):** projection (precedence, recency, multi-field, conflicting same-timestamp, change semantics §6.4, conflict suggestions §6.5), scoring, reminders/freshness (FixedClock pays off), identity resolution, conflict policy.
- **L2 connector contract:** one parametrized `SourceContract` suite every `Source` must pass — `yields_valid_observation_drafts`, `drafts_immutable`, `observed_at_tz_aware_when_present`, `name_stable_nonempty`, `honors_since_or_documents_full_scan`, `idempotent_for_same_input`. **Idempotency is load-bearing** — re-ingesting identical data must manufacture no fake "changes" or duplicate suggestions. This is what makes "drop-in plugin, no core changes" enforceable.
- **L3 ingestion API:** FastAPI `TestClient` over in-memory SQLite — valid→202+appended, malformed→422, auth rejection, duplicate POST idempotent, batch. DI-override the clock and stores.
- **L4 Markdown round-trip / bidirectional sync (most paranoid):** `parse(render(note)) == note`; no-clobber (unknown keys + body survive); out-of-band edit detection → ingested as obsidian observation and wins by precedence; idempotent write (same state twice → byte-identical file → clean git diff); graph repair patching touches only the proposed field/block; conflict surface (documented resolution, never silent overwrite).
- **L5 e2e golden paths** (few but complete, real SQLite + fakes): "who do I reach out to," "someone's job changed → notification + frontmatter update," "freshness → goes stale → surfaces."
- **L6 TUI (thin):** Textual `Pilot` smoke + `pytest-textual-snapshot` on two key screens. All real logic is tested headless; TUI tests only prove wiring.

**Property tests (Hypothesis, 6 places only):** markdown round-trip; wikilink parse/render; graph repair fingerprint stability; projection order-independence + latest-`observed_at`-wins; identity resolution reflexive/stable; idempotent ingest (twice == once, no duplicate change/suggestion/repair spam). Scoring numbers stay as readable example tests.

**Tooling:** `uv` + `hatchling`, src-layout, single `pyproject.toml`. `pytest` (+`-cov`, markers `unit/integration/e2e/tui/property`), `respx`, `syrupy` + `pytest-textual-snapshot`, `hypothesis`, `pytest-asyncio`, `ruff` (lint+format), `mypy --strict` (pydantic plugin), `import-linter` (dependency contracts), `pydantic-settings` (TOML + env; tokens via env, never committed). CI: `ruff check`/`format --check`, `mypy`, `import-linter`, `pytest -m "not tui" --cov`, separate `pytest -m tui` job.

---

## 13. Phased Roadmap

### Phase 0 — Walking Skeleton

**Goal:** an end-to-end vertical slice through every architectural seam with one fake source — prove the bet compiles and is testable before any real integration.

**Deliverables**
- Repo scaffolding: `uv`, `hatchling`, src-layout, `ruff`, `mypy --strict`, `import-linter` contracts, CI green.
- `domain`: `Entity`, `EntityRef`, `Observation`, `ObservationDraft`, `Interaction`, `UserAction`, `EntityState`, `ContactProfileState`, `FieldState`, `Change`, `ConflictSuggestion`, `GraphRepairSuggestion`, `Clock`/`FixedClock`, `IdFactory`, the closed `fields.py` (~20 fields).
- `projection.project()` — pure fold + the §6 comparator, with change detection (§6.4), conflict suggestions (§6.5), and graph repair suggestions.
- `store`: in-memory + SQLite (recompute-on-read projection — see O5) implementing the same interfaces.
- `sources.base`: `Source`/`Capability` protocol + `apply_map`; a `FakeSource`.
- `sync.run_sync` wiring FakeSource → hub → ledger → projection.
- `cli`: `whodex sync` runs the slice; prints a trivial projected-state dump.
- The `obs()`/`interaction()`/`action()` test-builder DSL; L1 projection tests + the L2 `SourceContract` skeleton.

**Explicitly deferred:** any real connector, Obsidian write-back, scoring, reminders, FastAPI, TUI.

**Done when:** `whodex sync` ingests FakeSource records, materializes SQLite + in-memory identically, a job-change fixture produces exactly one `Change` and no spurious change/suggestion on re-run; `import-linter`, `mypy --strict`, and the projection/contract tests pass in CI.

---

### Phase 1 — MVP (the reason whodex exists)

**Goal:** the daily loop works on real data — ranked reach-out queue, "I contacted them," per-field freshness, "what changed," Obsidian as bidirectional source of truth, one+ real connectors, in a usable TUI; one-shot `sync` and daemon both work.

**Deliverables**
- **Event ledger + projection + SQLite** hardened from Phase 0; reproducible replay from SQLite and mirrored JSONL.
- **Obsidian connector (PULL + WATCH + WRITEBACK)** — the full §3 contract over the current `people-network` templates: typed Entity notes, wikilink `EntityRef`s, `ruamel` frontmatter round-trip, three-way anti-clobber write-back (opt-in per field), inverse-link repair suggestions, `VaultFileState` hashing, echo suppression, `watchdog` debounced daemon watch. L4 paranoid tests.
- **Google Contacts connector (PULL)** — OAuth2 (Production consent screen), `connections.list` + sync tokens, `metadata.updateTime → observed_at`. `respx` contract tests.
- **Engine:** `score_contact` (overdue/tier/event/pin/snooze), per-field `staleness`, idempotent reminders with fingerprint dedup, `Change`/`ConflictSuggestion → Notification/ReviewItem` with `TUINotifier`.
- **Identity resolution:** strong-key auto-link for people, path/alias resolution for organisations/locations/events, system `entity_create` actions, `MergeCandidate` + quarantine for weak/no-key, `rapidfuzz` suggestions, archive tombstones.
- **Ingestion API (FastAPI)** — `POST /ingest` (token-gated), the universal funnel; `whodex token issue`.
- **Firefox WebExtension (MV3)** — passive LinkedIn capture → POST `RawRecord`; unmatched captures → quarantine. *(Could slip to early Phase 2 if time-boxed; the ingestion API it depends on ships in Phase 1 regardless.)*
- **TUI** — the five screens (§9.3), including contact-point and graph-maintenance views.
- **CLI/daemon:** `whodex sync` (one-shot = run_sync + drain_tasks + dispatch) and `whodex serve` (same on a loop + FastAPI + watch); systemd-timer-compatible.
- **Config:** TOML (paths, tokens, cadence tiers, trust ranks, freshness TTLs, notifier toggles).

**Explicitly deferred:** Telegram/email push, web dashboard, any LLM, paid LinkedIn API, RSS, graph centrality in scoring, temporal-validity for future-dated facts, `custom.*` write-back.

**Done when:**
- `whodex sync` pulls Google + reads the vault, materializes entity graph state, writes learned facts back to frontmatter **without** clobbering a hand-edited field (a hand edit wins; lower-trust disagreement surfaces as a conflict suggestion), and produces byte-identical files on a no-op re-run.
- Existing `people-network` notes for people, organisations, locations, and events are parsed into typed entities/edges; missing inverse links and unresolved scalar locations appear as graph repair suggestions.
- The TUI priority queue is ranked with a readable why-now; `l` resets the clock and drops the person; `s`/`p` work.
- A job-change fixture (LinkedIn ext POST) appears in "what changed" and bumps priority; congratulate + `c` confirms it and refreshes `last_confirmed`.
- A field past its TTL shows stale and (for a pull connector) enqueues a re-check drained by both `sync` and `serve`.
- Running `sync` ten times produces at most one notification per change/reminder.
- Deleting the SQLite DB and replaying the mirrored JSONL ledger plus vault-derived observations reproduces identical state, including archived contacts, merges, pins, snoozes, and dismissed reminders.

---

### Phase 2 — Push notifiers (Telegram/email)

**Goal:** reach-out prompts and change alerts reach the user without opening the TUI. **Deliverables:** `TelegramNotifier` + `EmailNotifier` implementing `Notifier`; Telegram bot as a *client* (`/queue`, `/log`, inline snooze/dismiss → facade calls); digest notification kind. **Deferred:** web. **Done when:** an overdue/changed contact is pushed to Telegram with working inline snooze/dismiss, deduped (no double-send across TUI + Telegram).

### Phase 3 — Web dashboard

**Goal:** a read/light-write web view reusing the facade. **Deliverables:** FastAPI read/write routes returning the same DTOs; a thin front-end consuming that JSON. **Done when:** the priority queue + contact detail render in a browser and "log interaction" round-trips through the same `Whodex` methods the TUI uses — no engine/schema change.

### Phase 4 — Local-LLM lane (powerful local PC)

**Goal:** higher-quality dedup, entity extraction, summaries — all behind the `Enricher`/`Embedder` seam, all landing as `Observation(source="llm", confidence<1)`, never authoritative. **Deliverables (gated by a feature flag):** Ollama default; embedding-based candidate dedup (Qwen3-Embedding / BGE-M3; FAISS only if volume demands) feeding `MergeCandidate`; entity/relationship extraction from note bodies → observations/edges; reach-out summaries; optionally visual-LLM parsing of LinkedIn screenshots (DOM-churn-robust). **Done when:** the lane is toggleable off with zero core dependency, LLM output is auditable/overridable as observations, and dedup suggestions improve over the deterministic baseline without auto-merging on weak signals.

### Phase 5 — Advanced graph features

**Goal:** move beyond the Phase-1 operational graph into deeper analysis. **Deliverables:** on-demand `networkx` centrality cached on `EntityState`; shortest-path/explainable-introduction queries; org/location cluster views; stale-subgraph detection; optional visual graph export. **Done when:** centrality nudges priority without dominating, recomputed lazily (not every sync), and advanced queries answer "who can introduce me to X?" without changing the Phase-1 entity/edge schema.

---

## 14. Risks & Open Questions

**Genuine risks**
- **LinkedIn ToS / account ban (user-accepted, values decision).** Even the *passive* extension is technically a ToS-prohibited scraping extension; enforcement intensified in 2025 (Proxycurl sued & shut down). Passive capture generates none of the velocity/biometric signals that trigger bans, lowering — not eliminating — risk. Mitigation: keep the extension fully separable; the user explicitly accepts the (low, nonzero) risk to their own account.
- **Obsidian write-back loop / clobber** — the single most bug-prone piece. Mitigated by the three-way merge + `last_written_hash` echo suppression + opt-in-per-field + the most paranoid test layer. Still warrants careful real-vault validation before trusting it on the live vault.
- **Identity-resolution false merges.** Mitigation: only auto-link on strong keys; quarantine weak/no-key; reversible unmerge; `anti_merge` actions; never auto-merge on name alone.
- **Vendor volatility (paid LinkedIn API).** Proven catastrophic (Proxycurl). It is fallback-only behind the connector interface; never build on it.
- **Privacy.** A dossier on real people: local-first, token-gated ingestion bound to localhost/own-HTTPS, no third-party analytics, opt-in-per-lookup paid APIs.

**Open questions (flagged, not papered over)**
- **O1 `custom.*` write-back.** Closed field registry (~20) is clean but will grow; allow `custom.*` projected-but-untyped. Decide whether `custom.*` may be written back to frontmatter (lean: **no** in Phase 1).
- **O2 `observed_at` for date-less sources** (Google). Falling back to `ingested_at` lets a stale sync out-rank an older-correct value. Need a concrete recency-discount rule for `observed_at_is_unknown` (§6.6) before writing projection tests.
- **O3 Google consent posture.** Confirm Production publishing (Personal-Use allowance) vs Workspace `Internal` to kill the 7-day refresh-token expiry.
- **O4 Body-block anti-clobber.** The `%% whodex:edges %%` block assumes the user won't hand-edit inside the markers. Lean: whodex owns the block, last-write-wins (no three-way merge there) — confirm.
- **O5 Projection materialization timing.** Recompute-on-read (pure, trivially testable, identical across memory/SQLite) vs incremental SQL. Lean: **recompute-on-read for Phase 1**, revisit only if the log grows large.
- **O6 Cadence default vs explicit.** Lean: tier-based default cadence with opt-in per-person override (less setup friction).
- **O7 Snooze vs dismiss.** Split (time-based vs reason-based) is implemented; collapse to snooze-only if it confuses in practice — usability check.
- **O8 Reminder-threshold vs weak-tier cadence.** Ensure a tier-4 weak tie (365-day cadence) can ever clear `reminder_threshold`, or weak ties become invisible — needs a sanity-test fixture.
- **O9 Contact-event granularity.** Single `contacted` event with an optional channel tag (lean) vs distinct channel event types.
- **O10 Wikilink-as-graph-edge visual behavior.** whodex parses quoted frontmatter wikilinks itself, so correctness does not depend on Obsidian's graph renderer. Still verify the installed Obsidian version so the optional visual graph and Bases views behave as expected.
- **O11 Managed graph repairs.** Decide which repair classes may be auto-applied in Phase 1 after review (`missing_inverse`, `template_drift` seem safe) and which must remain manual (`duplicate_entity`, `stale_membership`).
