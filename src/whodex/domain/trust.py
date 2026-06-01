from __future__ import annotations

# Default precedence ranks (DESIGN §6.2). Config may override; never baked into the ledger.
DEFAULT_TRUST: dict[str, int] = {
    "manual_cli": 100,
    "obsidian": 80,
    "google_contacts": 60,
    "linkedin_ext": 50,
    "linkedin_api": 40,
    "linkedin_rss": 30,
    "llm": 25,
    "webhook": 20,
    "fake": 10,  # Phase-0 test source
}
