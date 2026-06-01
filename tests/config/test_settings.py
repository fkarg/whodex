"""Tests for F8: TOML config via pydantic-settings (P1g-4)."""

from __future__ import annotations

import textwrap
from pathlib import Path

from whodex.config.toml import build_app_from_settings, load_settings
from whodex.domain.trust import DEFAULT_TRUST

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def write_toml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "whodex.toml"
    p.write_text(textwrap.dedent(content))
    return p


# ---------------------------------------------------------------------------
# F8-1: TOML file is loaded; basic scalar fields are present
# ---------------------------------------------------------------------------


def test_load_settings_from_toml(tmp_path: Path) -> None:
    """Values from a TOML file are surfaced on the Settings object."""
    toml = write_toml(
        tmp_path,
        """\
        vault_path = "/my/vault"
        db_path = "/my/db.sqlite"
        notifiers_enabled = ["tui", "email"]

        [trust_overrides]
        google_contacts = 70

        [freshness_ttl_days]
        "job.title" = 365
        """,
    )
    s = load_settings(toml_path=toml, env={})

    assert s.vault_path == Path("/my/vault")
    assert s.db_path == Path("/my/db.sqlite")
    assert s.notifiers_enabled == ["tui", "email"]
    assert s.trust_overrides == {"google_contacts": 70}
    assert s.freshness_ttl_days == {"job.title": 365}


# ---------------------------------------------------------------------------
# F8-2: Env override wins over TOML value
# ---------------------------------------------------------------------------


def test_env_overrides_toml(tmp_path: Path) -> None:
    """WHODEX_* env vars take precedence over TOML file values."""
    toml = write_toml(
        tmp_path,
        """\
        db_path = "/from/toml.db"
        vault_path = "/from/toml/vault"
        """,
    )
    s = load_settings(toml_path=toml, env={"WHODEX_DB_PATH": "/other.db"})

    assert s.db_path == Path("/other.db")
    # vault_path comes from TOML (not overridden)
    assert s.vault_path == Path("/from/toml/vault")


# ---------------------------------------------------------------------------
# F8-3: Missing TOML file → all defaults
# ---------------------------------------------------------------------------


def test_missing_toml_gives_defaults(tmp_path: Path) -> None:
    """When no TOML file is provided all fields revert to defaults."""
    s = load_settings(toml_path=None, env={})

    assert s.vault_path is None
    assert s.db_path is None
    assert s.notifiers_enabled == ["tui"]
    assert s.trust_overrides == {}
    assert s.cadence_default == {}
    assert s.tier_weight == {}
    assert s.freshness_ttl_days == {}


# ---------------------------------------------------------------------------
# F8-4: build_app_from_settings applies trust_overrides onto DEFAULT_TRUST
# ---------------------------------------------------------------------------


def test_build_app_from_settings_trust_override(tmp_path: Path) -> None:
    """trust_overrides in Settings are merged onto DEFAULT_TRUST in the built App."""
    toml = write_toml(
        tmp_path,
        """\
        [trust_overrides]
        google_contacts = 70
        """,
    )
    s = load_settings(toml_path=toml, env={})
    app = build_app_from_settings(s)

    # Override applied
    assert app.trust["google_contacts"] == 70
    # Other DEFAULT_TRUST keys preserved
    for key, default_val in DEFAULT_TRUST.items():
        if key != "google_contacts":
            assert app.trust[key] == default_val, f"trust[{key!r}] should equal default"


# ---------------------------------------------------------------------------
# F8-5: cadence_default and tier_weight fields are parsed correctly
# ---------------------------------------------------------------------------


def test_cadence_and_tier_weight_parsed(tmp_path: Path) -> None:
    """cadence_default and tier_weight fields load from TOML correctly."""
    toml = write_toml(
        tmp_path,
        """\
        [cadence_default]
        inner = 14
        close = 60

        [tier_weight]
        inner = 3.0
        """,
    )
    s = load_settings(toml_path=toml, env={})

    assert s.cadence_default == {"inner": 14, "close": 60}
    assert s.tier_weight == {"inner": 3.0}
