/**
 * options.js — Options page logic for whodex capture extension.
 *
 * Loads the stored endpoint URL and bearer token from browser.storage.local,
 * populates the form inputs, and saves updated values on button click.
 *
 * Uses the WebExtension `browser` API with a fallback to `chrome`.
 */

const api = globalThis.browser ?? globalThis.chrome;

const endpointInput = document.getElementById("endpoint");
const tokenInput = document.getElementById("token");
const saveButton = document.getElementById("save");
const statusEl = document.getElementById("status");

/** Populate form from storage on page load. */
api.storage.local.get(["endpoint", "token"]).then(({ endpoint, token }) => {
  if (endpoint) endpointInput.value = endpoint;
  if (token) tokenInput.value = token;
});

/** Save values to storage on button click. */
saveButton.addEventListener("click", () => {
  const endpoint = endpointInput.value.trim();
  const token = tokenInput.value.trim();

  if (!endpoint) {
    showStatus("Endpoint URL is required.", true);
    return;
  }

  api.storage.local.set({ endpoint, token }).then(() => {
    showStatus("Options saved.");
  }).catch((err) => {
    showStatus(`Failed to save: ${err.message}`, true);
  });
});

/**
 * Show a transient status message.
 * @param {string} msg
 * @param {boolean} [isError=false]
 */
function showStatus(msg, isError = false) {
  statusEl.textContent = msg;
  statusEl.className = isError ? "error" : "";
  setTimeout(() => { statusEl.textContent = ""; statusEl.className = ""; }, 3000);
}
