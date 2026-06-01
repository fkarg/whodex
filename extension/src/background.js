/**
 * background.js — whodex capture extension background (event page).
 *
 * Listens for "capture" messages from content.js and POSTs the record to
 * the user-configured whodex /ingest endpoint using the stored bearer token.
 *
 * Uses the WebExtension `browser` API with a fallback to `chrome`.
 */

import { postRecord } from "./post.js";

const api = globalThis.browser ?? globalThis.chrome;

api.runtime.onMessage.addListener((message, _sender, _sendResponse) => {
  if (message?.type !== "capture") return;

  const { record } = message;

  // Read endpoint + token from local storage, then POST
  api.storage.local.get(["endpoint", "token"]).then(({ endpoint, token }) => {
    if (!endpoint || !token) {
      console.debug("[whodex] capture skipped — endpoint or token not configured");
      return;
    }

    postRecord(record, { endpoint, token })
      .then(({ ok, status }) => {
        if (ok) {
          console.log("[whodex] capture accepted:", record.identity?.linkedin_url, `(${status})`);
        } else {
          console.warn("[whodex] capture rejected:", status, record.identity?.linkedin_url);
        }
      })
      .catch((err) => {
        console.error("[whodex] capture failed:", err);
      });
  });
});
