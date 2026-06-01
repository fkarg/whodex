/**
 * Tests for extension/src/post.js
 * Run with: node --test  (from the extension/ directory)
 * Uses only Node built-ins — no external dependencies.
 */

import { test, describe } from "node:test";
import assert from "node:assert/strict";

import { postRecord } from "../src/post.js";

// ---------------------------------------------------------------------------
// Fixture record (minimal; shape matches buildRecord output)
// ---------------------------------------------------------------------------

const SAMPLE_RECORD = {
  source: "linkedin_ext",
  identity: { linkedin_url: "https://www.linkedin.com/in/jane-doe" },
  payload: { name: "Jane Doe", linkedin_url: "https://www.linkedin.com/in/jane-doe" },
  observed_at: "2026-06-01T12:00:00.000Z",
  capture_context: { page_url: "https://www.linkedin.com/in/jane-doe", capture: "passive_view" },
};

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

/**
 * Build a fake fetch function that returns the given status.
 * Records the last call's URL and RequestInit for inspection.
 *
 * @param {number} status
 * @returns {{ fakeFetch: Function, calls: Array<{url: string, init: object}> }}
 */
function makeFakeFetch(status = 200) {
  const calls = [];
  const fakeFetch = async (url, init) => {
    calls.push({ url, init });
    return {
      ok: status >= 200 && status < 300,
      status,
    };
  };
  return { fakeFetch, calls };
}

// ---------------------------------------------------------------------------
// H3: postRecord tests
// ---------------------------------------------------------------------------

describe("postRecord", () => {
  test("H3: calls fetch with the correct URL", async () => {
    const { fakeFetch, calls } = makeFakeFetch(200);

    await postRecord(SAMPLE_RECORD, {
      endpoint: "https://h",
      token: "T",
      fetchFn: fakeFetch,
    });

    assert.equal(calls.length, 1, "fetch should be called exactly once");
    assert.equal(calls[0].url, "https://h/ingest");
  });

  test("H3: uses POST method", async () => {
    const { fakeFetch, calls } = makeFakeFetch(200);

    await postRecord(SAMPLE_RECORD, {
      endpoint: "https://h",
      token: "T",
      fetchFn: fakeFetch,
    });

    assert.equal(calls[0].init.method, "POST");
  });

  test("H3: sends Authorization header as Bearer token", async () => {
    const { fakeFetch, calls } = makeFakeFetch(200);

    await postRecord(SAMPLE_RECORD, {
      endpoint: "https://h",
      token: "T",
      fetchFn: fakeFetch,
    });

    assert.equal(calls[0].init.headers["Authorization"], "Bearer T");
  });

  test("H3: sends Content-Type application/json", async () => {
    const { fakeFetch, calls } = makeFakeFetch(200);

    await postRecord(SAMPLE_RECORD, {
      endpoint: "https://h",
      token: "T",
      fetchFn: fakeFetch,
    });

    assert.equal(calls[0].init.headers["Content-Type"], "application/json");
  });

  test("H3: body serialises record into {records:[record]}", async () => {
    const { fakeFetch, calls } = makeFakeFetch(200);

    await postRecord(SAMPLE_RECORD, {
      endpoint: "https://h",
      token: "T",
      fetchFn: fakeFetch,
    });

    const body = JSON.parse(calls[0].init.body);
    assert.ok(Array.isArray(body.records), "body.records should be an array");
    assert.equal(body.records.length, 1);
    assert.deepEqual(body.records[0], SAMPLE_RECORD);
  });

  test("H3: returns {ok:true, status:200} on a successful response", async () => {
    const { fakeFetch } = makeFakeFetch(200);

    const result = await postRecord(SAMPLE_RECORD, {
      endpoint: "https://h",
      token: "T",
      fetchFn: fakeFetch,
    });

    assert.equal(result.ok, true);
    assert.equal(result.status, 200);
  });

  test("H3: returns {ok:false, status:401} on a non-ok response", async () => {
    const { fakeFetch } = makeFakeFetch(401);

    const result = await postRecord(SAMPLE_RECORD, {
      endpoint: "https://h",
      token: "wrong",
      fetchFn: fakeFetch,
    });

    assert.equal(result.ok, false);
    assert.equal(result.status, 401);
  });

  test("H3: returns {ok:false, status:500} on a server error response", async () => {
    const { fakeFetch } = makeFakeFetch(500);

    const result = await postRecord(SAMPLE_RECORD, {
      endpoint: "https://h",
      token: "T",
      fetchFn: fakeFetch,
    });

    assert.equal(result.ok, false);
    assert.equal(result.status, 500);
  });
});
