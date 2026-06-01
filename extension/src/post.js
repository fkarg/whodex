/**
 * post.js — pure, testable HTTP posting helper.
 *
 * Sends a single whodex ingest record to the configured endpoint.
 * The `fetchFn` parameter is injectable so this module can be tested
 * in Node without a real network or browser environment.
 */

/**
 * POST a single record to `${endpoint}/ingest`.
 *
 * @param {object} record          — the assembled record (from buildRecord)
 * @param {object} opts
 * @param {string} opts.endpoint   — base URL, e.g. "http://localhost:8000"
 * @param {string} opts.token      — bearer token
 * @param {Function} [opts.fetchFn] — injectable fetch implementation; defaults to globalThis.fetch
 * @returns {Promise<{ok: boolean, status: number}>}
 */
export async function postRecord(record, { endpoint, token, fetchFn }) {
  const fn = fetchFn ?? globalThis.fetch;
  const url = `${endpoint}/ingest`;

  const response = await fn(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ records: [record] }),
  });

  return { ok: response.ok, status: response.status };
}
