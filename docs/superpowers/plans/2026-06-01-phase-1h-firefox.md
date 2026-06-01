# whodex Phase 1h — Firefox WebExtension (MV3, passive LinkedIn capture)

> REQUIRED SUB-SKILL: superpowers:subagent-driven-development. **Testing law (AGENTS §10):** behavior/invariants via the public extractor API; the **extractor** is a pure, `node --test`-tested unit against saved HTML fixtures; content/background/options are thin wiring verified manually. This increment is OUTSIDE the Python CI gate — the controller verifies (a) the Python gate still passes (extension lives under `extension/`, not `src/`) and (b) `node --test` passes.

**Goal:** a Manifest-V3 Firefox extension that, while you genuinely browse a LinkedIn profile, extracts the profile fields and POSTs a `RawRecord(source="linkedin_ext")` to the whodex ingestion API (1f) — passive capture, lowest ban risk. ToS risk user-accepted (DESIGN §14).

**Builds on:** 1f ingestion API (`POST /ingest`, bearer token, `linkedin_ext` source mapping `{name,title,company,linkedin_url}`).

## Scope
In: `extension/` MV3 package (manifest, content script, background event page, options page); a PURE `extract.js` (DOM/HTML → profile payload) with `node --test` unit tests against committed HTML fixtures; README (load unpacked, set endpoint+token, manual E2E). 
Out: Chrome packaging, store submission, auto-scraping beyond the active tab, headless automation.

## Invariants / behaviors (tested where possible)
- **H1 extractor:** given representative LinkedIn profile HTML fixtures, `extractProfile(doc)` returns `{name, headline, title, company, location, linkedin_url}` (best-effort; missing fields → null/omitted). `node --test` over committed fixtures. Deterministic.
- **H2 record shape:** `buildRecord(profile, pageUrl)` returns `{source:"linkedin_ext", identity:{linkedin_url}, payload:{name,title,company,linkedin_url,headline,location}, observed_at:<ISO>, capture_context:{page_url, capture:"passive_view"}}` matching what `/ingest` + the `linkedin_ext` source expect (canonical mapping is server-side; the extension sends the raw payload keys the source maps). Unit-tested.
- **H3 post:** the background posts `{records:[record]}` to the configured endpoint with `Authorization: Bearer <token>` (logic unit-testable by injecting a fake `fetch`; full network is manual).
- **H4 python gate unaffected:** `extension/` is excluded from `src/` so ruff/mypy/import-linter/pytest are unchanged.

## Tasks

### Task 1: extension scaffold + manifest + node test harness
`extension/` with: `manifest.json` (MV3: `manifest_version:3`, name, version, permissions `["storage"]`, host_permissions for the configured endpoint + `*://*.linkedin.com/*`, `background.service_worker`/event page, `content_scripts` matching `*://*.linkedin.com/in/*`, `options_ui`), `package.json` (`"type":"module"`, `"scripts":{"test":"node --test"}`), a `README.md` (load-unpacked in Firefox `about:debugging`, set endpoint+token in options, browse a profile). Ensure `extension/` is NOT picked up by ruff/mypy (they target `src`/`tests`; confirm). Controller verifies `node --test` runs (even if 0 tests yet) + python gate green.

### Task 2: pure `extract.js` + `buildRecord` (H1/H2) + node tests
`extension/src/extract.js` (ES module): `extractProfile(doc)` (takes a DOM `Document`; uses `querySelector`s with resilient fallbacks for name/headline/current-position title+company/location; returns the object, fields null when absent) and `buildRecord(profile, pageUrl, nowIso)` (H2 shape; `linkedin_url` canonicalized from pageUrl — strip query/fragment, lowercase host). `extension/test/extract.test.js` (`node --test` + a tiny HTML→Document via `linkedom` OR a hand-built fake `doc` with the querySelector methods the extractor uses — prefer a fake `doc` object to avoid a dep, OR add `linkedom` as an extension dev dep and parse committed `extension/test/fixtures/*.html`). Tests: H1 (fields extracted from fixture incl. missing-field fallbacks), H2 (record shape + canonical linkedin_url). Controller runs `cd extension && node --test`.

### Task 3: content script + background + options + manual-E2E README (H3)
- `content.js`: on a profile page (debounced, once per profile view), `extractProfile(document)` → `runtime.sendMessage({type:"capture", record})`.
- `background.js` (event page/service worker): on `capture` message, read endpoint+token from `storage.local`, `fetch(endpoint+"/ingest", {method:POST, headers:{Authorization:Bearer, Content-Type}, body:JSON.stringify({records:[record]})})`; log result. Factor the POST into a pure `postRecord(record, {endpoint, token, fetchFn})` in a module so it's unit-testable with a fake `fetch` (H3 test: asserts URL, Authorization header, body `{records:[...]}`).
- `options.html`/`options.js`: inputs for endpoint URL + bearer token, saved to `storage.local`.
- README: step-by-step manual E2E (run `whodex serve`/the ingestion app locally or on VPS, `whodex token issue`, paste endpoint+token, browse a profile, confirm ingestion via `whodex queue`). Note source id is `linkedin_ext` and ToS risk is user-accepted.
Controller verifies `node --test` (H3 included) + python gate green.

## Self-review: extractor + record-builder + post are pure & node-tested; content/background/options are thin wiring; `extension/` doesn't touch the Python gate; README enables manual E2E against the 1f API; source id `linkedin_ext` matches the server.
