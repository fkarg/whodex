/**
 * Tests for extension/src/extract.js
 * Run with: node --test  (from the extension/ directory)
 * Uses only Node built-ins — no external dependencies.
 */

import { test, describe } from "node:test";
import assert from "node:assert/strict";

import {
  extractProfile,
  canonicalLinkedinUrl,
  buildRecord,
} from "../src/extract.js";

// ---------------------------------------------------------------------------
// Test helper: fake DOM document
// ---------------------------------------------------------------------------

/**
 * Build a minimal fake document whose querySelector returns an element-like
 * object {textContent} when the selector is in `map`, else null.
 *
 * querySelectorAll returns a single-element array when the selector is present,
 * otherwise an empty array.
 *
 * @param {Record<string, string>} map  selector → textContent
 */
function fakeDoc(map) {
  return {
    querySelector(sel) {
      if (Object.prototype.hasOwnProperty.call(map, sel)) {
        return { textContent: map[sel] };
      }
      return null;
    },
    querySelectorAll(sel) {
      if (Object.prototype.hasOwnProperty.call(map, sel)) {
        return [{ textContent: map[sel] }];
      }
      return [];
    },
  };
}

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

/** A fully-populated profile fixture. */
const FULL_PROFILE_DOC = fakeDoc({
  h1: "Jane Doe",
  "[data-generated-suggestion-target]": "  Software Engineer · Building things  ",
  ".pv-text-details__right-panel .mr1.t-bold span[aria-hidden=true]": "Senior Engineer",
  ".pv-text-details__right-panel .t-14.t-normal span[aria-hidden=true]": "Acme Corp",
  ".pv-text-details__left-panel .text-body-small": "  San Francisco, CA  ",
});

/** A profile where headline/title/company/location are absent. */
const SPARSE_PROFILE_DOC = fakeDoc({
  h1: "  John   Smith  ", // whitespace to test trimming
});

/** A profile where no recognised selectors match at all. */
const EMPTY_PROFILE_DOC = fakeDoc({});

// ---------------------------------------------------------------------------
// extractProfile tests
// ---------------------------------------------------------------------------

describe("extractProfile", () => {
  test("H1: returns all fields from a fully-populated document", () => {
    const profile = extractProfile(FULL_PROFILE_DOC);
    assert.equal(profile.name, "Jane Doe");
    assert.equal(profile.headline, "Software Engineer · Building things");
    assert.equal(profile.title, "Senior Engineer");
    assert.equal(profile.company, "Acme Corp");
    assert.equal(profile.location, "San Francisco, CA");
  });

  test("H1: missing fields are null in a sparse document", () => {
    const profile = extractProfile(SPARSE_PROFILE_DOC);
    assert.equal(profile.name, "John Smith"); // whitespace collapsed + trimmed
    assert.equal(profile.headline, null);
    assert.equal(profile.title, null);
    assert.equal(profile.company, null);
    assert.equal(profile.location, null);
  });

  test("H1: all fields are null when no selectors match", () => {
    const profile = extractProfile(EMPTY_PROFILE_DOC);
    assert.equal(profile.name, null);
    assert.equal(profile.headline, null);
    assert.equal(profile.title, null);
    assert.equal(profile.company, null);
    assert.equal(profile.location, null);
  });

  test("H1: internal whitespace is collapsed", () => {
    const doc = fakeDoc({ h1: "  Alice   Wonderland  " });
    const profile = extractProfile(doc);
    assert.equal(profile.name, "Alice Wonderland");
  });

  test("H1: whitespace-only textContent yields null", () => {
    const doc = fakeDoc({ h1: "   " });
    const profile = extractProfile(doc);
    assert.equal(profile.name, null);
  });

  test("H1: falls back to second selector when first is absent", () => {
    // The headline selectors list starts with [data-generated-suggestion-target].
    // Provide only the second selector to verify fallback works.
    const doc = fakeDoc({
      h1: "Fallback Test",
      ".text-body-medium.break-words": "Fallback headline",
    });
    const profile = extractProfile(doc);
    assert.equal(profile.headline, "Fallback headline");
  });
});

// ---------------------------------------------------------------------------
// canonicalLinkedinUrl tests
// ---------------------------------------------------------------------------

describe("canonicalLinkedinUrl", () => {
  test("strips query string and fragment, returns canonical form", () => {
    const result = canonicalLinkedinUrl(
      "https://www.linkedin.com/in/jane-doe/?utm=x#exp"
    );
    assert.equal(result, "https://www.linkedin.com/in/jane-doe");
  });

  test("handles URL without query or fragment", () => {
    assert.equal(
      canonicalLinkedinUrl("https://www.linkedin.com/in/johndoe"),
      "https://www.linkedin.com/in/johndoe"
    );
  });

  test("handles URL with trailing slash", () => {
    assert.equal(
      canonicalLinkedinUrl("https://www.linkedin.com/in/johndoe/"),
      "https://www.linkedin.com/in/johndoe"
    );
  });

  test("returns null for a non-profile LinkedIn URL", () => {
    assert.equal(
      canonicalLinkedinUrl("https://www.linkedin.com/feed/"),
      null
    );
  });

  test("returns null for a non-LinkedIn URL", () => {
    assert.equal(canonicalLinkedinUrl("https://example.com/in/person"), null);
  });

  test("returns null for a malformed URL string", () => {
    assert.equal(canonicalLinkedinUrl("not-a-url"), null);
  });

  test("handles mobile linkedin subdomain", () => {
    // linkedin.com sub-domains should be accepted
    const result = canonicalLinkedinUrl(
      "https://m.linkedin.com/in/mobile-user"
    );
    assert.equal(result, "https://www.linkedin.com/in/mobile-user");
  });
});

// ---------------------------------------------------------------------------
// buildRecord tests
// ---------------------------------------------------------------------------

describe("buildRecord", () => {
  const PAGE_URL =
    "https://www.linkedin.com/in/jane-doe/?utm_source=test#section";
  const NOW = "2026-06-01T12:00:00.000Z";

  test("H2: shape is correct and source equals 'linkedin_ext'", () => {
    const profile = {
      name: "Jane Doe",
      headline: "Engineer",
      title: "Senior Engineer",
      company: "Acme Corp",
      location: "San Francisco, CA",
    };
    const record = buildRecord(profile, PAGE_URL, NOW);

    assert.equal(record.source, "linkedin_ext");
    assert.ok(typeof record.identity === "object");
    assert.ok(typeof record.payload === "object");
    assert.equal(record.observed_at, NOW);
    assert.ok(typeof record.capture_context === "object");
  });

  test("H2: identity.linkedin_url is canonical", () => {
    const profile = { name: "Jane", headline: null, title: null, company: null, location: null };
    const record = buildRecord(profile, PAGE_URL, NOW);
    assert.equal(
      record.identity.linkedin_url,
      "https://www.linkedin.com/in/jane-doe"
    );
  });

  test("H2: null payload values are omitted", () => {
    const profile = {
      name: "Jane Doe",
      headline: null,
      title: null,
      company: null,
      location: null,
    };
    const record = buildRecord(profile, PAGE_URL, NOW);

    assert.ok(Object.prototype.hasOwnProperty.call(record.payload, "name"));
    assert.ok(!Object.prototype.hasOwnProperty.call(record.payload, "headline"));
    assert.ok(!Object.prototype.hasOwnProperty.call(record.payload, "title"));
    assert.ok(!Object.prototype.hasOwnProperty.call(record.payload, "company"));
    assert.ok(!Object.prototype.hasOwnProperty.call(record.payload, "location"));
  });

  test("H2: capture_context.capture equals 'passive_view'", () => {
    const profile = { name: null, headline: null, title: null, company: null, location: null };
    const record = buildRecord(profile, PAGE_URL, NOW);
    assert.equal(record.capture_context.capture, "passive_view");
    assert.equal(record.capture_context.page_url, PAGE_URL);
  });

  test("H2: payload linkedin_url matches canonical form", () => {
    const profile = { name: "Jane", headline: null, title: null, company: null, location: null };
    const record = buildRecord(profile, PAGE_URL, NOW);
    assert.equal(
      record.payload.linkedin_url,
      "https://www.linkedin.com/in/jane-doe"
    );
  });

  test("H2: all non-null fields appear in payload", () => {
    const profile = {
      name: "Jane Doe",
      headline: "Engineer",
      title: "Senior Engineer",
      company: "Acme Corp",
      location: "San Francisco, CA",
    };
    const record = buildRecord(profile, PAGE_URL, NOW);
    assert.equal(record.payload.name, "Jane Doe");
    assert.equal(record.payload.headline, "Engineer");
    assert.equal(record.payload.title, "Senior Engineer");
    assert.equal(record.payload.company, "Acme Corp");
    assert.equal(record.payload.location, "San Francisco, CA");
    assert.equal(record.payload.linkedin_url, "https://www.linkedin.com/in/jane-doe");
  });
});
