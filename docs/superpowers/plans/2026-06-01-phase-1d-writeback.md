# whodex Phase 1d — Obsidian Write-Back (anti-clobber)

> REQUIRED SUB-SKILL: superpowers:subagent-driven-development. **Testing law (AGENTS §10):** behavior/invariants via public interfaces; property tests for round-trip; never assert internals. Controller runs an INDEPENDENT full-gate checkpoint after every task. This is the highest-risk increment — most paranoid tests + a dedicated final review.

**Goal:** whodex writes *learned/enriched* facts (and a one-time `whodex.uid`) back into Obsidian frontmatter **without ever clobbering hand edits**, keeping the body byte-identical and producing byte-identical files on a no-op re-write (clean git diff). Write-back is opt-in and limited to managed enrichment scalars.

**Builds on:** 1b (vault parser, ObsidianSource, VaultFile), 1c. `ruamel.yaml` round-trip.

## Crucial design fact (simplifies anti-clobber)
Obsidian has the highest connector trust (80) vs Google (60)/LinkedIn (50). So for any managed field the note **already has**, the Obsidian observation wins → write-back must **leave it unchanged**. Write-back therefore only **fills blanks** (managed fields the note lacks, where a lower-trust source supplied a value) and injects `whodex.uid` once. The three-way merge additionally guards the out-of-band-edit race.

## Scope
In: markdown **render** (frontmatter+body round-trip); `VaultFileState` persistence + content hashing; the write-back engine (fill-blank + three-way merge + echo suppression + uid injection); ObsidianSource `WRITEBACK` capability + run_sync write phase (opt-in `--write-back`); e2e invariants.
Out (later): `watchdog` daemon watch (1g/serve); applying `GraphRepairSuggestion`s to the vault; `%% whodex:edges %%` block; write-back of wikilink/graph fields (`organisations`/`lives` stay user-curated).

## Invariants (the tests)
- **W1 round-trip fidelity:** `render(parse(text))` preserves the body byte-for-byte and all frontmatter keys/order; property test over arbitrary bodies + representative frontmatter.
- **W2 no-clobber:** a managed field the note already has is NEVER overwritten (Obsidian wins); unknown frontmatter keys and the body survive a write-back.
- **W3 idempotent write:** writing the same projected state twice → byte-identical file (no spurious git diff).
- **W4 echo suppression:** whodex's own write-back is NOT re-ingested as a user edit on the next sync (no phantom observation/Change).
- **W5 uid injection:** `whodex.uid` is written exactly once and is stable across runs; a note that already has a uid is not rewritten for it.
- **W6 fill-blank:** a managed field the note LACKS, for which a (lower-trust) source supplied a value, IS written into frontmatter.

## Tasks

### Task 1: markdown `render` + round-trip (W1)
Extend `vault/markdown.py`: `render_note(note: ParsedNote) -> str` (and/or `render(frontmatter, body) -> str`) using the SAME `ruamel.yaml` round-trip representer so key order/quoting/comments are preserved; body appended verbatim after the closing fence. Behavioral + **property** tests: `parse(render(parse(text))).body == parse(text).body` for arbitrary bodies; unknown keys preserved through a parse→render→parse cycle; a note with no frontmatter renders unchanged. Keep `ParsedNote` carrying enough (the ruamel object or the raw) to round-trip with fidelity — adjust `ParsedNote` if needed (note any change). Independent gate checkpoint.

### Task 2: `VaultFileState` persistence + hashing
`VaultFileStateRow` (path PK, last_content_hash, last_frontmatter_seen JSON, last_mtime, last_written_hash) + mappers + store (in-memory + SQLite) under a contract. A `content_hash(frontmatter_bytes)` helper. Behavioral: save/load round-trip; cross-instance durability. Gate checkpoint.

### Task 3: write-back engine (W2/W3/W5/W6) — pure core
`vault/writeback.py`: a PURE function
```python
def plan_writeback(
    *, current: ParsedNote, projected: dict[str, Any], managed_fields: Sequence[str],
    base_frontmatter: dict[str, Any] | None, uid: str | None,
) -> WriteBackResult   # new_note: ParsedNote | None (None == no change), wrote_fields: list[str]
```
Rules:
- **Fill-blank:** for each managed field, if `current.frontmatter` lacks it (or empty) AND `projected` has a non-empty value → set it.
- **No-clobber / three-way merge:** if the field is present in `current` and differs from `base_frontmatter` (user edited out-of-band) → DO NOT overwrite (leave the user's value). If present and equal to base and projected differs → (still don't clobber a present value in 1d — Obsidian wins; only fill blanks). Net effect for 1d: never overwrite a present managed field.
- **uid:** if `current` lacks `whodex.uid` and `uid` given → inject `whodex: {uid: ...}` (preserve other whodex keys).
- **Idempotent:** if nothing changes, return `new_note=None` (caller writes nothing → byte-identical).
This is the most-tested unit: parametric + property tests for W2 (present field untouched, unknown keys/body survive), W3 (same input twice → same/None), W5 (uid once), W6 (blank filled). Gate checkpoint.

### Task 4: wire write-back + echo suppression (W4)
- ObsidianSource gains `WRITEBACK` capability + a writer that, given an entity's projected managed values, computes `plan_writeback` against the on-disk note and writes the rendered text **only if changed**; updates `VaultFileState.last_written_hash = content_hash(written_frontmatter)`.
- On the IN scan (fetch), skip ingesting a file whose current `content_hash == last_written_hash` (echo suppression) — so our own write isn't re-ingested.
- run_sync gains an opt-in write phase (`--write-back` CLI flag; default off): after projection, for each person entity with a vault_path, write back managed blanks + uid.
Behavioral W4: sync → write-back fills a blank → next sync does NOT emit a new observation/Change from that file (echo suppressed). Gate checkpoint.

### Task 5: e2e write-back invariants + dedicated review (W1–W6)
`tests/test_e2e_phase1d.py` over a tmp copy of `fixtures/people-network-min` + a fake "enrichment" source (e.g. a FakeSource or crafted obs supplying `job.title` for a person whose note lacks it):
- W6: after `sync --write-back`, the note's frontmatter gains `job_title`.
- W2: a managed field the note already has is unchanged; body + unknown keys preserved (diff only the intended line).
- W3: a second `sync --write-back` with no new data → the file is byte-identical (assert file bytes equal).
- W5: `whodex.uid` injected once; second run doesn't change it.
- W4: second sync emits no new Change from the written file.
Full gate + coverage. Then the CONTROLLER dispatches a dedicated review subagent (this is the riskiest code). Independent gate verify before merge.

## Self-review: every task leads with behavior/invariant/property tests; the write-back core is pure and exhaustively tested for no-clobber + idempotency + echo; body byte-fidelity proven; uid-once proven; validated against a copy of the real fixture (never the live vault in tests).
