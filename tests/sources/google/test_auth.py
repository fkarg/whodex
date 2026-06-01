"""Tests for GoogleCredentialsConfig and GoogleTokenProvider.

No live network or OAuth calls — only config parsing and the fake-refresh path.
"""

from __future__ import annotations

import pytest

from whodex.sources.google.auth import GoogleCredentialsConfig, GoogleTokenProvider

# ---------------------------------------------------------------------------
# GoogleCredentialsConfig.from_env
# ---------------------------------------------------------------------------

_FULL_ENV = {
    "WHODEX_GOOGLE_CLIENT_ID": "cid",
    "WHODEX_GOOGLE_CLIENT_SECRET": "csecret",
    "WHODEX_GOOGLE_REFRESH_TOKEN": "rtoken",
}


def test_from_env_returns_config_when_all_vars_present() -> None:
    cfg = GoogleCredentialsConfig.from_env(_FULL_ENV)
    assert cfg is not None
    assert cfg.client_id == "cid"
    assert cfg.client_secret == "csecret"
    assert cfg.refresh_token == "rtoken"
    assert cfg.token_uri == "https://oauth2.googleapis.com/token"


@pytest.mark.parametrize(
    "missing_key",
    [
        "WHODEX_GOOGLE_CLIENT_ID",
        "WHODEX_GOOGLE_CLIENT_SECRET",
        "WHODEX_GOOGLE_REFRESH_TOKEN",
    ],
)
def test_from_env_returns_none_when_any_var_missing(missing_key: str) -> None:
    env = {k: v for k, v in _FULL_ENV.items() if k != missing_key}
    assert GoogleCredentialsConfig.from_env(env) is None


def test_from_env_returns_none_for_empty_env() -> None:
    assert GoogleCredentialsConfig.from_env({}) is None


# ---------------------------------------------------------------------------
# GoogleTokenProvider — fake-refresh path (no network)
# ---------------------------------------------------------------------------


def _make_fake_refresh(token: str):
    """Return a refresh_fn that sets creds.token without any network call."""

    def fake_refresh(creds) -> None:  # type: ignore[no-untyped-def]
        creds.token = token

    return fake_refresh


def test_token_provider_returns_token_via_fake_refresh() -> None:
    cfg = GoogleCredentialsConfig(
        client_id="cid",
        client_secret="csecret",
        refresh_token="rtoken",
    )
    provider = GoogleTokenProvider(cfg, refresh_fn=_make_fake_refresh("fake-access-token"))
    assert provider.access_token() == "fake-access-token"


def test_token_provider_calls_refresh_fn_each_time() -> None:
    """access_token() must invoke the refresh_fn (not cache stale tokens)."""
    tokens = ["tok-1", "tok-2"]
    calls: list[str] = []

    def counting_refresh(creds) -> None:  # type: ignore[no-untyped-def]
        t = tokens[len(calls)]
        creds.token = t
        calls.append(t)

    cfg = GoogleCredentialsConfig(
        client_id="cid",
        client_secret="csecret",
        refresh_token="rtoken",
    )
    provider = GoogleTokenProvider(cfg, refresh_fn=counting_refresh)

    assert provider.access_token() == "tok-1"
    assert provider.access_token() == "tok-2"
    assert calls == ["tok-1", "tok-2"]
