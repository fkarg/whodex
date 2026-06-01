# whodex Phase 2 — Push Notifiers (Telegram + Email) + Telegram bot client

> REQUIRED SUB-SKILL: superpowers:subagent-driven-development. **Testing law (AGENTS §10):** behavior/invariants via public interfaces; HTTP mocked with `respx`, SMTP via an injected sender, bot updates via injected fake updates; never assert internals; parametric/property where a real invariant exists. **Controller runs an INDEPENDENT full-gate checkpoint after EVERY task** (the implementers have repeatedly under-reported — only the controller's `uv run ruff check . && ruff format --check . && mypy --strict src && lint-imports && pytest -q` counts).

**Goal (DESIGN §13 Phase 2):** reach-out prompts and "what changed" alerts reach the user **without opening the TUI** — pushed to **Telegram** and/or **email**, with a Telegram **bot client** (`/queue`, `/log`, inline snooze/dismiss buttons that call the facade). Deliveries are **deduped across sinks** (no double-send across TUI + Telegram), idempotent, and config-selected. Web dashboard is deferred (Phase 3).

**Builds on Phase 1g:** `Notification` persistence, the `Notifier` protocol, `NotificationDispatcher` (idempotent via `delivered_to`), `TUINotifier`, the `Whodex` facade, `serve_tick`, and `pydantic-settings` (`notifiers_enabled`, env secrets). **No new core surface** — Phase 2 adds *sinks* + a *bot client* behind the existing seams.

## Done when (acceptance)
- An overdue contact / a notable change generates a `Notification` that is **pushed to Telegram** with working **inline snooze + dismiss** buttons; pressing a button calls `facade.snooze`/`facade.dismiss_reminder` and acknowledges the callback.
- The same notification is **delivered at most once per enabled sink** (TUI + Telegram + email together → no duplicates), and re-running `serve_tick`/`dispatch` does **not** re-send.
- `notifiers_enabled` in `whodex.toml`/env selects which sinks are active; secrets (`WHODEX_TELEGRAM_BOT_TOKEN`/`_CHAT_ID`, SMTP creds) are env-only, never committed.
- An email sink delivers a rendered digest/alert via an injected SMTP sender (no live SMTP in CI).
- The Telegram bot `/queue` replies with the ranked reach-out list; `/log <name|id>` logs an interaction; all via the facade.

## Cross-cutting decisions
1. **Reuse the Notifier seam.** Each sink is a `Notifier` (`name`, `supports(n)`, `send(n) -> DeliveryResult`). The existing `NotificationDispatcher` already skips sinks present in `n.delivered_to`, so cross-sink dedupe + idempotency are free — Phase 2 must NOT add a parallel delivery path.
2. **All network injected.** Telegram calls go through an injected `httpx.Client` (respx in tests). Email goes through an injected `send_email(msg) -> None` callable (a fake in tests; real impl uses stdlib `smtplib`/`email`). The bot's `getUpdates` loop is a thin wrapper around an injected update source; the **command router/handlers are the tested unit**.
3. **Secrets via `pydantic-settings`/env** (`WHODEX_TELEGRAM_BOT_TOKEN`, `WHODEX_TELEGRAM_CHAT_ID`, `WHODEX_SMTP_HOST/PORT/USER/PASSWORD/FROM/TO`). Absent config → the sink is silently not constructed (like Google in 1e).
4. **Rendering shared.** A pure `render_notification(n) -> RenderedNotification{title, body, actions}` so Telegram/email/TUI format consistently; sinks adapt the rendered form to their medium.
5. **Bot = client, not a new core.** Handlers call the `Whodex` facade only. Long-poll (`getUpdates`) over webhook (no public URL needed); the infinite loop is thin/untested, `handle_update(update, facade) -> list[Action]` is pure-ish and tested.
6. **Layering:** notifiers/bot sit at/above `notifiers`; they import `domain`/`facade`/(injected httpx) — keep `import-linter` green (add a `bot`/`telegram` module placement if needed). TDD; no `Co-Authored-By`; focused commits.

## File structure
```
src/whodex/notifiers/
├── render.py        # render_notification + RenderedNotification
├── telegram.py      # TelegramNotifier (Notifier) + Telegram API client (httpx)
├── email.py         # EmailNotifier (Notifier) + SMTP sender helper
├── digest.py        # build_digest(pending) -> Notification (kind="digest")
└── bot/
    ├── router.py    # handle_update(update, facade) -> list[BotAction] (pure, tested)
    └── runner.py    # long-poll getUpdates loop (thin wrapper; CLI `whodex bot`)
src/whodex/config/   # extend Settings: telegram/smtp blocks; sink selection
```

## Tasks

### Task 1: `render_notification` (shared formatting)
`notifiers/render.py`: `RenderedNotification(title: str, body: str, actions: list[Action])` where `Action(kind: "snooze"|"dismiss"|"open", label, target_id)`. `render_notification(n: Notification) -> RenderedNotification` — from `n.kind` (`change`/`reminder`/`digest`) + `payload`, produce a human title/body (e.g. change → "Anna R. · job.title: Senior → Staff Engineer"; reminder → "Reach out to Anna (2.3× overdue)") and the relevant actions (reminder → snooze+dismiss; change → ack/open). Pure. Parametric tests over the kinds + payloads; property: rendering never raises on any well-formed Notification. Gate checkpoint.

### Task 2: `TelegramNotifier` (the headline sink)
`notifiers/telegram.py`: a thin `TelegramClient(http: httpx.Client, token: str, chat_id: str)` (`send_message(text, *, reply_markup=None)`, `answer_callback(id, text)`), and `TelegramNotifier(client, *, kinds: set[str] | None = None)` implementing `Notifier` (`name="telegram"`): `supports(n)` = True (or filtered to high-signal kinds per config); `send(n)` → `render_notification(n)` → `client.send_message(title+body, reply_markup=<inline keyboard with snooze/dismiss buttons whose callback_data encodes "snooze:<entity>"/"dismiss:<fingerprint>">)`; return `DeliveryResult(delivered=resp.ok)`. respx tests: `send` posts to `https://api.telegram.org/bot<token>/sendMessage` with the chat_id, text, and an inline keyboard JSON containing snooze+dismiss buttons; a non-200 → `delivered=False`. Gate checkpoint.

### Task 3: `EmailNotifier`
`notifiers/email.py`: `EmailConfig(host, port, username, password, sender, recipient)` + `make_smtp_sender(config) -> Callable[[EmailMessage], None]` (stdlib `smtplib.SMTP`/`SMTP_SSL`; not unit-tested live). `EmailNotifier(send: Callable[[EmailMessage], None], *, sender, recipient)` (`name="email"`): `send(n)` builds an `email.message.EmailMessage` (subject=title, body=body) from `render_notification(n)` and calls the injected `send`; `DeliveryResult(delivered=True)` on success, capture exceptions → `delivered=False`. Tests with a fake sender (records messages): asserts subject/body/recipient; a sender that raises → `delivered=False` (no crash). Gate checkpoint.

### Task 4: digest notification kind
`notifiers/digest.py`: `build_digest(items: Sequence[Notification], *, id, now) -> Notification` (kind="digest", payload summarizing N pending alerts; stable `dedupe_key` over the included ids/day). A `Whodex.build_and_store_digest()` or a dispatcher mode that, instead of N individual sends, emits one digest Notification when `notifiers` are in "digest" mode (config `notify_mode: "each"|"digest"`). `render_notification` handles kind="digest" (a bulleted summary). Behavioral: 3 pending → one digest notification whose body lists all 3; dispatched once. Gate checkpoint.

### Task 5: Telegram bot client (`/queue`, `/log`, inline buttons)
`notifiers/bot/router.py`: `handle_update(update: dict, facade) -> list[BotAction]` (pure) — parse a Telegram update:
- `/queue` (message text) → `facade.priority_queue(limit=10)` → a `BotAction(kind="send_message", text=<rendered ranked list>)`.
- `/log <name-or-id>` → resolve to an entity (facade lookup) → `facade.log_interaction(id)` → confirm message.
- `callback_query` with `data="snooze:<entity>"` → `facade.snooze(entity, now+7d)` + `BotAction(answer_callback, "Snoozed")` + edit/remove the keyboard.
- `data="dismiss:<fingerprint>"` → `facade.dismiss_reminder(fingerprint)` + answer.
- unknown → help text.
`notifiers/bot/runner.py`: a long-poll loop (`getUpdates` via the `TelegramClient`) that feeds updates to `handle_update` and executes the returned `BotAction`s; `whodex bot --db --vault` CLI starts it; `--once`/injected-updates path for testing. **Tested unit = `handle_update`** (feed canned update dicts + a spy facade, assert the BotActions + facade calls). Gate checkpoint.

### Task 6: config-driven sink wiring + dedupe (acceptance core)
Extend `Settings`/`build_app`: a `telegram` block (token/chat_id from env) and `smtp` block; build `TelegramNotifier`/`EmailNotifier` only when configured; `notifiers_enabled` (already parsed in 1g) selects which `Notifier`s populate `app.notifiers`. Thread `app.notifiers` into the dispatcher used by `Whodex.dispatch_notifications()`/`serve_tick`. Behavioral: with TUI+Telegram both enabled (Telegram respx-mocked), a notification is delivered to each exactly once; a second `dispatch` sends nothing new (the `delivered_to` invariant across multiple real sinks). Secrets via env only. Gate checkpoint.

### Task 7: e2e + gate + review
`tests/test_e2e_phase2.py` (respx for Telegram, fake SMTP, in-memory app): drive a sync that yields a notable change + a due reminder → `dispatch_notifications()` → Telegram `sendMessage` called once **with inline snooze/dismiss buttons**, email sent once; dispatch again → zero new sends (dedupe). Then feed a `callback_query` `snooze:<entity>` to `handle_update` → `facade.snooze` called and the contact leaves the priority queue. Full gate + coverage. Controller dispatches a review subagent (cross-sink dedupe + secret-handling + bot-action correctness) and independent gate verify before merge.

## Risks & user-supplied config (document in AGENTS/README on completion)
- **Telegram:** the user creates a bot via @BotFather → `WHODEX_TELEGRAM_BOT_TOKEN`; gets their chat id → `WHODEX_TELEGRAM_CHAT_ID`. Long-poll needs no public URL. (Webhook mode = a Phase-3/deploy follow-up.)
- **Email/SMTP:** `WHODEX_SMTP_HOST/PORT/USER/PASSWORD/FROM/TO` (e.g. an app-password for Gmail). TLS via `SMTP_SSL`/`starttls`.
- **No live network in CI** (respx + fake SMTP + injected updates). The runner loop + real SMTP send are thin and manually verified.
- **Privacy:** notification bodies contain PII about real people — they go only to the user's own bot/inbox; tokens are env-only.

## Self-review (run after drafting): every task leads with behavior/invariant tests; reuses the Notifier seam (no parallel delivery path); cross-sink dedupe + idempotency proven; secrets env-only and absent→skip; the bot is a facade client with a pure tested router; HTTP/SMTP fully mocked. This is one cohesive subsystem (one plan); subsequent phases (3 web, 4 LLM, 5 graph) get their own plans.
