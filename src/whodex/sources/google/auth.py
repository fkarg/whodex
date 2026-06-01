"""Google OAuth2 credentials config and token provider.

This is the ONLY module in whodex that imports google-auth.  The connector
(next task) accepts a ``Callable[[], str]`` token factory so it never needs
to import google-auth and remains fully unit-testable.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from pydantic import BaseModel

__all__ = [
    "GoogleCredentialsConfig",
    "GoogleTokenProvider",
]


class GoogleCredentialsConfig(BaseModel):
    """Immutable value object holding the four OAuth2 fields we need."""

    client_id: str
    client_secret: str
    refresh_token: str
    token_uri: str = "https://oauth2.googleapis.com/token"

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> GoogleCredentialsConfig | None:
        """Read config from an env-like mapping.

        Returns ``None`` (rather than raising) when any required variable is
        absent so that callers can skip Google wiring gracefully.
        """
        client_id = env.get("WHODEX_GOOGLE_CLIENT_ID")
        client_secret = env.get("WHODEX_GOOGLE_CLIENT_SECRET")
        refresh_token = env.get("WHODEX_GOOGLE_REFRESH_TOKEN")

        if not (client_id and client_secret and refresh_token):
            return None

        return cls(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
        )


class GoogleTokenProvider:
    """Fetches a fresh access token using the stored refresh token.

    Parameters
    ----------
    config:
        OAuth2 credentials (client ID/secret + refresh token).
    refresh_fn:
        Injectable transport hook — receives a ``google.oauth2.credentials.Credentials``
        object and must populate ``creds.token`` (without making a real HTTP call).
        Defaults to ``google.auth.transport.requests.Request()``, which performs
        the real token-refresh network request.  Pass a fake in tests.
    """

    def __init__(
        self,
        config: GoogleCredentialsConfig,
        *,
        refresh_fn: Callable[[Credentials], None] | None = None,
    ) -> None:
        self._config = config
        self._refresh_fn = refresh_fn

    def access_token(self) -> str:
        """Return a fresh access token.

        A new ``Credentials`` object is constructed on every call so that the
        provider never holds a stale cached token — the refresh transport is
        responsible for deciding whether to issue a network request.
        """
        creds = Credentials(  # type: ignore[no-untyped-call]
            token=None,
            refresh_token=self._config.refresh_token,
            client_id=self._config.client_id,
            client_secret=self._config.client_secret,
            token_uri=self._config.token_uri,
        )

        if self._refresh_fn is not None:
            self._refresh_fn(creds)
        else:
            creds.refresh(Request())  # type: ignore[no-untyped-call]

        token: str = creds.token  # type: ignore[assignment]
        return token
