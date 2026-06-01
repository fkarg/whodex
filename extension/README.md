# whodex capture — Firefox Extension

## Overview

A Firefox MV3 WebExtension that captures LinkedIn profile data and pushes it to
your local [whodex](https://github.com/fkarg/whodex) instance via the `/ingest`
HTTP API.

Fields captured from LinkedIn profile pages and sent as `linkedin_ext` records:

| Extension field  | Canonical field  |
|------------------|------------------|
| `name`           | `name.full`      |
| `title`          | `job.title`      |
| `company`        | `job.org`        |
| `linkedin_url`   | `linkedin.url`   |

## Manual End-to-End Walkthrough

### 1. Expose the ingestion API

The `whodex serve` CLI command runs a sync/dispatch loop but does **not** yet
mount an HTTP server — the FastAPI `/ingest` route is wired inside
`whodex.ingestion.app` and a `whodex serve --http` flag is a planned follow-up.

**For now, start the HTTP API directly via uvicorn:**

```sh
# From the repository root (activate your virtualenv / uv shell first)
uv run uvicorn whodex.ingestion.app:app --host 127.0.0.1 --port 8000
```

`whodex.ingestion.app:app` is the FastAPI application instance exported from
the ingestion module.  It exposes:

```
POST /ingest
Authorization: Bearer <token>
Content-Type: application/json

{"records": [ <RawRecord>, ... ]}
```

Successful response (HTTP 200):

```json
{"accepted": 1, "changes": 1, "conflicts": 0}
```

You can verify it manually with curl:

```sh
curl -s -X POST http://localhost:8000/ingest \
  -H "Authorization: Bearer <your-token>" \
  -H "Content-Type: application/json" \
  -d '{"records":[{"source":"linkedin_ext","identity":{"linkedin_url":"https://www.linkedin.com/in/test-user"},"payload":{"name":"Test User"},"observed_at":"2026-01-01T00:00:00Z","capture_context":{"page_url":"https://www.linkedin.com/in/test-user","capture":"passive_view"}}]}'
```

> **Note:** `whodex serve` (sync loop) and the HTTP API are independent entry
> points.  A unified `whodex serve --http` command that runs both is a
> forthcoming follow-up task.

### 2. Issue a bearer token

```sh
uv run whodex token issue --label firefox --db /path/to/whodex.db
```

Copy the printed token — it is shown only once.

### 3. Load the extension in Firefox

1. Open Firefox and navigate to `about:debugging`.
2. Click **This Firefox** in the left sidebar.
3. Click **Load Temporary Add-on…**.
4. Select `extension/manifest.json` from this repository.

The extension is now active.

### 4. Configure the extension

1. Click the whodex toolbar icon and choose **Manage Extension → Options**
   (or right-click the icon → **Manage Extension** → **Options** tab).
2. Enter:
   - **Ingestion endpoint URL** — `http://localhost:8000` (no trailing slash)
   - **Bearer token** — the token from step 2
3. Click **Save**.

### 5. Browse a LinkedIn profile

Navigate to any LinkedIn profile URL, e.g.
`https://www.linkedin.com/in/someone`.

The content script fires automatically (debounced by ~5 s) and sends the
profile to background.js, which POSTs it to your whodex instance.

Check the browser console in **about:debugging → Inspect** (background script)
for `[whodex] capture accepted:` log lines.

### 6. Verify ingestion

```sh
uv run whodex queue --db /path/to/whodex.db
```

The captured person should appear in the priority queue output.  You can also
run a full sync to see their resolved fields:

```sh
uv run whodex sync --db /path/to/whodex.db
```

### Notes

- **Source id:** all records sent by this extension have `source: "linkedin_ext"`.
- **Capture mode:** passive — the extension only captures profiles you actively
  browse; it does not crawl or automate any LinkedIn navigation.
- **ToS acknowledgement:** passive browser-based capture is governed by
  LinkedIn's terms of service.  Per DESIGN §14, the risk is user-accepted;
  whodex does not facilitate bulk or automated scraping.
- **Optional host permissions:** the ingestion endpoint host (e.g.
  `localhost:8000`) is covered by `optional_host_permissions: ["*://*/*"]`.
  Firefox will prompt you once when the extension first contacts that host.

---

## Load in Firefox (development — quick reference)

1. `about:debugging` → **This Firefox** → **Load Temporary Add-on…** →
   select `extension/manifest.json`.
2. Open Options, paste endpoint (`http://localhost:8000`) and token, Save.
3. Browse a LinkedIn `/in/` profile page.
4. Confirm via `uv run whodex queue --db <db>` that the person appears.

## Options page

Saves the whodex ingestion endpoint URL and bearer token to
`browser.storage.local`.  Inputs are pre-populated from storage on page load.

## Node test harness

Tests live in `test/` and run with:

```sh
cd extension
node --test
```

No npm install required — tests use only Node built-ins.

Current test coverage:

| Suite             | Tests | What is tested                                    |
|-------------------|-------|---------------------------------------------------|
| `extractProfile`  | 6     | DOM selector fallbacks, whitespace normalisation  |
| `canonicalLinkedinUrl` | 7 | URL normalisation, edge cases, null paths       |
| `buildRecord`     | 6     | Record shape, canonical URL, null-value omission  |
| `postRecord`      | 8     | HTTP method, headers, body envelope, ok/fail paths|

## Architecture

```
content.js          — runs in the LinkedIn tab; extracts + sends message
    ↓  runtime.sendMessage({type:"capture", record})
background.js       — receives message; reads storage; calls postRecord
    ↓  POST /ingest
whodex HTTP API     — accepts {records:[...]} envelope; stores raw observations
```

Pure/testable modules (`extract.js`, `post.js`) contain no browser globals and
are fully exercised by the `node --test` suite.  Browser wiring (`content.js`,
`background.js`, `options.js`) is kept as thin glue code.
