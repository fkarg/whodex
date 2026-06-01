/**
 * content.js — LinkedIn profile capture content script.
 *
 * Runs on *://*.linkedin.com/in/* pages (declared in manifest.json).
 * Extracts the visible profile, builds a whodex record, and forwards it
 * to background.js via runtime messaging.
 *
 * Uses the WebExtension `browser` API with a fallback to `chrome` so the
 * same file works in Firefox (where `browser` is the standard global) and
 * Chromium-based browsers (where `chrome` is the standard global).
 */

// NOTE: MV3 content scripts are classic scripts and cannot statically `import`
// an ES module. We load the pure extractor (a web-accessible ES module — see
// `web_accessible_resources` in manifest.json) via dynamic import inside capture().

const api = globalThis.browser ?? globalThis.chrome;

// ---------------------------------------------------------------------------
// Debounce — only capture once per URL per session (or after a quiet period).
// A simple "last captured URL" guard is enough for passive capture.
// ---------------------------------------------------------------------------

let lastCapturedUrl = null;
let debounceTimer = null;
const DEBOUNCE_MS = 5_000; // 5 seconds

/**
 * Attempt to capture the current profile page.
 * Guards: URL must be a LinkedIn /in/ page; identity.linkedin_url must resolve.
 */
async function capture() {
  const currentUrl = location.href;

  // Already captured this URL in this session
  if (currentUrl === lastCapturedUrl) return;

  // Dynamic-import the web-accessible extractor module (MV3-compatible).
  const { extractProfile, buildRecord } = await import(api.runtime.getURL("src/extract.js"));

  const profile = extractProfile(document);
  const rec = buildRecord(profile, currentUrl, new Date().toISOString());

  // Only forward if we have a resolvable LinkedIn URL
  if (!rec.identity.linkedin_url) return;

  lastCapturedUrl = currentUrl;
  api.runtime.sendMessage({ type: "capture", record: rec });
}

/**
 * Schedule a debounced capture.
 * Resets the timer on each call so rapid SPA navigation only fires once.
 */
function scheduledCapture() {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(capture, DEBOUNCE_MS);
}

// ---------------------------------------------------------------------------
// Trigger: fire once on load, then watch for SPA navigations via popstate /
// History API mutations (LinkedIn is a single-page app).
// ---------------------------------------------------------------------------

// Initial page load
scheduledCapture();

// SPA navigation: listen for history changes
window.addEventListener("popstate", scheduledCapture);

// Patch pushState / replaceState to detect programmatic navigation
(function patchHistory() {
  for (const method of ["pushState", "replaceState"]) {
    const original = history[method];
    history[method] = function (...args) {
      const result = original.apply(this, args);
      scheduledCapture();
      return result;
    };
  }
})();
