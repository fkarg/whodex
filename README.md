# whodex

**Know who you know.** whodex is a local-first personal CRM that unifies your Obsidian vault, Google
Contacts, and LinkedIn into one place — so you can see *who to reach out to*, *why now*, and *what changed
about them*, without ever handing your data to anyone else.

It is a **supplemental layer** over a workflow you already have (an Obsidian vault + your real messenger).
Delete whodex tomorrow and your vault and relationships survive intact — your Markdown notes remain the
source of truth.

## What it does

whodex earns its place by doing four things a plain notes folder can't:

- **Prioritized reach-out reminders** — a ranked "reach out today" queue, each with a one-line *why-now*
  ("2.3× overdue · job changed"). One keypress logs "I contacted them" and resets the clock.
- **Freshness / up-to-date-ness checks** — per-field staleness ("when did I last confirm their job/city?").
- **Change detection** — "X changed jobs / moved cities", surfaced as alerts so you don't have to go
  looking on LinkedIn.
- **Graph-aware maintenance** — your people, organisations, locations, and events become a queryable graph
  ("who do I know at Acme?", "who's in Frankfurt?"), with one-click suggestions to fix missing links.

It ingests from **Obsidian** (read *and* write-back — it fills in blanks like emails / LinkedIn URLs / job
titles without clobbering your edits), **Google Contacts**, and **LinkedIn** (via a Firefox extension that
captures profiles you genuinely view, pushed to a local ingestion API). New sources are drop-in plugins.

> **Status:** Phase 1 (MVP) is complete and working end-to-end — CLI + TUI, durable Obsidian sync &
> write-back, Google Contacts, the ingestion API + Firefox extension, prioritization/freshness/reminders,
> the relationship graph, and a background daemon. Push notifications (Telegram/email) are planned for
> Phase 2 (see `docs/superpowers/plans/`).

## Install

Requires **Python 3.12+** and [**uv**](https://docs.astral.sh/uv/).

```bash
git clone git@github.com:fkarg/whodex.git
cd whodex
uv sync          # creates the venv and installs everything
```

Run commands with `uv run whodex …` (or activate the venv and use `whodex …`).

## Quickstart

Point whodex at your Obsidian vault and a database file:

```bash
# Read your vault into a durable local DB and rank who to reach out to
uv run whodex sync  --vault ~/vaults/people --db ~/.whodex/whodex.db
uv run whodex queue --vault ~/vaults/people --db ~/.whodex/whodex.db

# Or just explore the interactive terminal UI
uv run whodex tui   --vault ~/vaults/people --db ~/.whodex/whodex.db

# Kick the tyres with a built-in demo (no vault needed)
uv run whodex queue --demo
```

Re-running `sync` is **idempotent** — it never duplicates contacts and only reports genuine changes.

## Commands

| Command | What it does |
|---|---|
| `whodex sync [--vault P] [--db P] [--write-back] [--demo] [--config F]` | Ingest sources → durable DB. `--write-back` enriches vault frontmatter (fills blanks only, never clobbers). |
| `whodex queue [--vault P] [--db P]` | Print the ranked reach-out queue with why-now. |
| `whodex tui [--vault P] [--db P]` | Interactive Textual UI: priority queue, contact detail, contact-points, review/maintenance, log-interaction. |
| `whodex who-at <name> [--vault P] [--db P]` | List the people at an organisation or location. |
| `whodex serve [--vault P] [--db P] [--once] [--interval N]` | Daemon: sync + dispatch notifications on a loop (`--once` for a single tick). |
| `whodex token issue --label <x> [--db P]` | Mint a bearer token for the ingestion API (printed once; only its hash is stored). |

Most commands accept `--config whodex.toml`; explicit `--vault`/`--db` flags override config values.

## Configuration

Settings load from a `whodex.toml` (via `--config`) and/or `WHODEX_*` environment variables (env wins).
A missing file → sensible defaults.

```toml
# whodex.toml
vault_path = "~/vaults/people"
db_path    = "~/.whodex/whodex.db"

[trust_overrides]        # override per-source precedence (defaults: obsidian 80 > google 60 > linkedin 50)
google_contacts = 70

[freshness_ttl_days]     # per-field staleness windows
job_title = 90
location  = 120
```

**Secrets are environment-only (never committed):**

- **Google Contacts** (optional) — see the step-by-step in
  `docs/superpowers/plans/2026-06-01-phase-1e-google.md` (Google Cloud OAuth Desktop client + consent
  screen). Set `WHODEX_GOOGLE_CLIENT_ID`, `WHODEX_GOOGLE_CLIENT_SECRET`, `WHODEX_GOOGLE_REFRESH_TOKEN`.
  When absent, Google sync is silently skipped.

## Obsidian vault format

whodex adopts the existing vocabulary of a people-network vault (see the reference templates in
`fixtures/people-network-min/`) — it does **not** impose a parallel schema. Notes are typed by folder/`type`/
tags into **People / Organisations / Locations / Events**, and `[[wikilinks]]` form the relationship graph.

A person note whodex reads (and *enriches* the blank lines of):

```yaml
---
type: Person
aliases: [Jane]
organisations: ["[[Organisations/Acme|Acme]]"]   # → member_of edge
lives: "[[Locations/Berlin|Berlin]]"             # → lives_in edge
last contact: 2026-01-15                          # feeds the reach-out clock
# --- whodex fills these in from Google/LinkedIn, never overwriting your edits ---
linkedin: "https://www.linkedin.com/in/janedoe"
emails: [jane@acme.com]
job_title: Staff Engineer
whodex: { uid: 01J8X..., managed_fields: [linkedin, emails, job_title] }
---
## Notes
- Kennenlernen: …
```

Write-back is opt-in (`whodex sync --write-back`), fills only empty managed fields, injects a stable `uid`
once, and produces byte-identical files on a no-op re-run (clean git diffs).

## LinkedIn (Firefox extension)

LinkedIn has no usable contacts API, so whodex captures **profiles you genuinely view** via a Firefox MV3
extension under `extension/`. It extracts the profile and POSTs it to your local ingestion API
(`whodex serve` / the FastAPI app), authenticated with a bearer token (`whodex token issue`). See
`extension/README.md` for load-unpacked + manual setup. This is passive capture on your own session; the
(low, nonzero, user-accepted) LinkedIn-ToS tradeoff is discussed in `docs/DESIGN.md` §14.

## How it works

Everything hangs off one bet: an **append-only event ledger** is the only thing the world writes to; both
the SQLite projection **and** your Obsidian frontmatter are deterministic *folds* over it. A manual Obsidian
edit is just a high-trust observation, so it always wins over a connector — and nothing is ever destroyed
(delete the DB, replay the ledger, you're back). Sources emit observations; a pure projector resolves
conflicts by trust precedence and detects changes; a pure engine scores priority and freshness. The full
architecture is in **`docs/DESIGN.md`**.

**Privacy:** local-first (your SQLite + git-tracked vault); the ingestion API is token-gated and bound to
localhost / your own host; no third-party analytics; paid-API lookups (if ever enabled) are opt-in per
lookup.

## Development

```bash
uv run pytest -q                 # ~570 tests
uv run ruff check . && uv run ruff format --check .
uv run mypy --strict src
uv run lint-imports              # enforces the layered architecture
cd extension && node --test      # the Firefox extension's JS unit tests
```

- **Architecture & design:** `docs/DESIGN.md` (the living spec).
- **Working conventions & status:** `AGENTS.md`.
- **Implementation plans (per increment):** `docs/superpowers/plans/`.
- Code is layered (`domain` is pure; SQLModel only in `store`; UI/connectors depend inward) — enforced by
  `import-linter`. Tests favor behavior/invariants over implementation.

## Roadmap

- **Phase 1 — MVP:** ✅ complete (Obsidian read/write, Google, ingestion API + Firefox ext, engine, graph,
  TUI, `serve`).
- **Phase 2 — Push notifiers:** Telegram + email sinks, a Telegram bot client (`/queue`, `/log`, inline
  snooze/dismiss). Detailed plan: `docs/superpowers/plans/2026-06-02-phase-2-push-notifiers.md`.
- **Phase 3+** — web dashboard, local-LLM enrichment lane, advanced graph (centrality, intro paths). See
  `docs/DESIGN.md` §13.

## License

See [LICENSE](LICENSE).
