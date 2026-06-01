"""F8: TOML + env-based settings for whodex (pydantic-settings).

Public API
----------
load_settings(toml_path, env)  -> Settings
build_app_from_settings(settings, *, clock, ids)  -> App

Load order (highest wins)
-------------------------
1. Explicit env mapping (WHODEX_* keys) — passed as ``env`` arg; in production
   callers pass ``os.environ``; tests pass an explicit dict.
2. TOML file values (stdlib ``tomllib``).
3. Pydantic field defaults.

``Settings`` is a ``BaseSettings`` subclass so it can also be constructed
directly (e.g. ``Settings(vault_path=...)``) or fed from the merged dict.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from whodex.config.settings import App, build_app
from whodex.domain.trust import DEFAULT_TRUST

# ---------------------------------------------------------------------------
# Settings model
# ---------------------------------------------------------------------------


class Settings(BaseSettings):
    """Application-wide configuration.

    Field names mirror TOML keys directly; env names are ``WHODEX_<FIELD>``.
    """

    model_config = SettingsConfigDict(
        env_prefix="WHODEX_",
        extra="ignore",
    )

    vault_path: Path | None = None
    db_path: Path | None = None

    # trust source weights — merged ONTO DEFAULT_TRUST
    trust_overrides: dict[str, int] = {}

    # scoring overrides (merged onto ScoringConfig defaults)
    cadence_default: dict[str, int] = {}
    tier_weight: dict[str, float] = {}

    # freshness overrides (merged onto FreshnessConfig.ttl_days)
    freshness_ttl_days: dict[str, int] = {}

    # notifier sinks
    notifiers_enabled: list[str] = ["tui"]


# ---------------------------------------------------------------------------
# Loader — the clean, testable entry point
# ---------------------------------------------------------------------------


def _read_toml(toml_path: Path) -> dict[str, Any]:
    """Read *toml_path* with stdlib tomllib; return empty dict on error."""
    try:
        with open(toml_path, "rb") as fh:
            return tomllib.load(fh)
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        return {}


def _extract_env_overrides(env: Mapping[str, str]) -> dict[str, Any]:
    """Strip ``WHODEX_`` prefix, lowercase, and return matching pairs."""
    prefix = "WHODEX_"
    return {
        k[len(prefix) :].lower(): v for k, v in env.items() if k.upper().startswith(prefix) and v
    }


def load_settings(
    toml_path: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> Settings:
    """Build a ``Settings`` object from a TOML file and an env mapping.

    Parameters
    ----------
    toml_path:
        Optional path to a ``whodex.toml`` file.  Missing file → silently
        ignored.
    env:
        Mapping of environment variables.  Pass ``os.environ`` in production;
        pass an explicit dict in tests (never reads real ``os.environ``).
    """
    if env is None:
        import os

        env = os.environ

    # Step 1: TOML base
    merged: dict[str, Any] = {}
    if toml_path is not None:
        merged.update(_read_toml(toml_path))

    # Step 2: env overrides (higher priority)
    merged.update(_extract_env_overrides(env))

    return Settings(**merged)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def build_app_from_settings(
    settings: Settings,
    *,
    clock: object = None,
    ids: object = None,
) -> App:
    """Construct an ``App`` from a ``Settings`` object.

    Applies ``trust_overrides`` onto ``DEFAULT_TRUST``.  The
    ``cadence_default``, ``tier_weight``, and ``freshness_ttl_days`` overrides
    are stored on the ``App`` as ``scoring_config`` / ``freshness_config``
    attributes (recorded-but-not-yet-threaded into the facade — the facade
    currently constructs ``ScoringConfig()`` inline; threading is tracked as
    P1g-4 follow-up).
    """
    from whodex.engine.freshness import FreshnessConfig
    from whodex.engine.scoring import ScoringConfig

    kwargs: dict[str, Any] = {}
    if clock is not None:
        kwargs["clock"] = clock
    if ids is not None:
        kwargs["ids"] = ids

    app = build_app(
        vault=settings.vault_path,
        db=settings.db_path,
        **kwargs,
    )

    # Apply trust overrides onto DEFAULT_TRUST copy
    trust = dict(DEFAULT_TRUST)
    trust.update(settings.trust_overrides)
    app.trust = trust

    # Build merged scoring / freshness configs and store on app for facade use.
    # NOTE: the facade (queue command, serve_tick) currently calls
    # ScoringConfig() inline; threading these through is a follow-up task.
    scoring_cfg = ScoringConfig()
    if settings.cadence_default:
        scoring_cfg = scoring_cfg.model_copy(
            update={"cadence_default": {**scoring_cfg.cadence_default, **settings.cadence_default}}
        )
    if settings.tier_weight:
        scoring_cfg = scoring_cfg.model_copy(
            update={"tier_weight": {**scoring_cfg.tier_weight, **settings.tier_weight}}
        )

    freshness_cfg = FreshnessConfig()
    if settings.freshness_ttl_days:
        freshness_cfg = freshness_cfg.model_copy(
            update={"ttl_days": {**freshness_cfg.ttl_days, **settings.freshness_ttl_days}}
        )

    # Attach configs to app for downstream facade use.
    # App is a plain dataclass; we attach extra attrs via __dict__ since
    # the dataclass doesn't declare these fields.  Threading into the facade's
    # inline ScoringConfig() calls is a tracked follow-up (P1g-4 notes).
    app.__dict__["scoring_config"] = scoring_cfg
    app.__dict__["freshness_config"] = freshness_cfg

    return app
