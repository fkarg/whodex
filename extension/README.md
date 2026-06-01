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

## Load in Firefox (development)

1. Start your whodex server (`whodex serve`).
2. Open Firefox and navigate to `about:debugging`.
3. Click **This Firefox** in the left sidebar.
4. Click **Load Temporary Add-on…**.
5. Select `extension/manifest.json` from this repository.
6. Open the extension's **Options** page (right-click the toolbar icon →
   Manage Extension → Options) and enter:
   - **Endpoint URL** — e.g. `http://localhost:8000/ingest`
   - **API key** — your whodex API key (if configured)

## Options page

_Implemented in P1h-3._  Saves the whodex endpoint URL and API key to
`browser.storage.sync`.

## End-to-end test

_Implemented in P1h-3._  Headless Playwright (or web-ext) smoke test that
verifies a LinkedIn profile page triggers a POST to the whodex `/ingest`
endpoint with the correct payload shape.

## Host permissions

`*://*.linkedin.com/*` is declared in `host_permissions` so scraping works
without an additional prompt.  The ingestion endpoint host is requested at
runtime via `optional_host_permissions: ["*://*/*"]`; Firefox will prompt the
user once when the extension first calls that host.

## Node test harness

Tests live in `test/` and run with:

```sh
cd extension
node --test
```

No npm install required — tests use only Node built-ins.
