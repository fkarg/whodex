/**
 * extract.js — pure, browser-safe extraction helpers (no Node-only APIs).
 *
 * Exported functions:
 *   extractProfile(doc)          — scrape a LinkedIn profile DOM
 *   canonicalLinkedinUrl(url)    — normalise a LinkedIn profile URL
 *   buildRecord(profile, pageUrl, nowIso) — assemble the ingest payload
 */

// ---------------------------------------------------------------------------
// Selector lists — try each in order, take the first non-empty text value.
// Keeping them in one place makes maintenance easy when LinkedIn changes markup.
// ---------------------------------------------------------------------------
const SELECTORS = {
  name: [
    // Primary: the <h1> in the profile top-card
    "h1",
    // Fallback generic selectors used in some LinkedIn layouts
    ".pv-text-details__left-panel h1",
    ".text-heading-xlarge",
  ],
  headline: [
    // The short tagline beneath the name
    "[data-generated-suggestion-target]",
    ".text-body-medium.break-words",
    ".pv-text-details__left-panel .text-body-medium",
    ".ph5 .text-body-medium",
  ],
  title: [
    // Current job title from the experience/top-card area
    ".pv-text-details__right-panel .mr1.t-bold span[aria-hidden=true]",
    ".experience-section li:first-child h3",
    ".pvs-list__item--line-separated:first-child .t-bold span[aria-hidden=true]",
  ],
  company: [
    // Current employer
    ".pv-text-details__right-panel .t-14.t-normal span[aria-hidden=true]",
    ".experience-section li:first-child .pv-entity__secondary-title",
    ".pvs-list__item--line-separated:first-child .t-14.t-normal span[aria-hidden=true]",
  ],
  location: [
    ".pv-text-details__left-panel .text-body-small",
    ".ph5 .text-body-small.inline.t-black--light",
    ".top-card-layout__first-subline",
  ],
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Collapse internal whitespace and trim a string.
 * Returns null for falsy / whitespace-only strings.
 * @param {string|null|undefined} text
 * @returns {string|null}
 */
function clean(text) {
  if (!text) return null;
  const s = text.replace(/\s+/g, " ").trim();
  return s.length > 0 ? s : null;
}

/**
 * Try each selector in `selList` against `doc.querySelector`; return the
 * cleaned textContent of the first match that yields a non-empty string.
 * @param {object} doc  — anything with querySelector(sel) → {textContent} | null
 * @param {string[]} selList
 * @returns {string|null}
 */
function firstMatch(doc, selList) {
  for (const sel of selList) {
    const el = doc.querySelector(sel);
    if (el) {
      const val = clean(el.textContent);
      if (val !== null) return val;
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Extract profile fields from a DOM Document (or compatible fake).
 *
 * @param {object} doc — must expose querySelector(sel) returning {textContent} | null
 * @returns {{ name: string|null, headline: string|null, title: string|null,
 *             company: string|null, location: string|null }}
 */
export function extractProfile(doc) {
  return {
    name: firstMatch(doc, SELECTORS.name),
    headline: firstMatch(doc, SELECTORS.headline),
    title: firstMatch(doc, SELECTORS.title),
    company: firstMatch(doc, SELECTORS.company),
    location: firstMatch(doc, SELECTORS.location),
  };
}

/**
 * Normalise a LinkedIn profile URL to canonical form:
 *   https://www.linkedin.com/in/<slug>
 * Strips query string, fragment, trailing slash, lowercases host.
 * Returns null if the URL is not a LinkedIn /in/ profile URL.
 *
 * @param {string} pageUrl
 * @returns {string|null}
 */
export function canonicalLinkedinUrl(pageUrl) {
  let parsed;
  try {
    parsed = new URL(pageUrl);
  } catch {
    return null;
  }

  // Must be linkedin.com (any sub-domain accepted for robustness)
  if (!parsed.hostname.toLowerCase().endsWith("linkedin.com")) return null;

  // Path must be /in/<slug> (with optional trailing slash / extra segments)
  const match = parsed.pathname.match(/^\/in\/([^/]+)/i);
  if (!match) return null;

  const slug = match[1];
  return `https://www.linkedin.com/in/${slug}`;
}

/**
 * Assemble the whodex ingest record from an extracted profile.
 *
 * @param {{ name, headline, title, company, location }} profile
 * @param {string} pageUrl    — raw page URL
 * @param {string} nowIso     — ISO-8601 timestamp string
 * @returns {object}
 */
export function buildRecord(profile, pageUrl, nowIso) {
  const linkedinUrl = canonicalLinkedinUrl(pageUrl);

  // Build payload, omitting null-valued keys
  const rawPayload = {
    name: profile.name,
    title: profile.title,
    company: profile.company,
    linkedin_url: linkedinUrl,
    headline: profile.headline,
    location: profile.location,
  };

  const payload = Object.fromEntries(
    Object.entries(rawPayload).filter(([, v]) => v !== null)
  );

  return {
    source: "linkedin_ext",
    identity: { linkedin_url: linkedinUrl },
    payload,
    observed_at: nowIso,
    capture_context: {
      page_url: pageUrl,
      capture: "passive_view",
    },
  };
}
