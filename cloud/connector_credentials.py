"""Provider credential primitives for Rally connector adapters.

This module deliberately knows nothing about connector policy or MCP sessions. It
only owns profile-scoped credential persistence and authenticated HTTP request
construction, which keeps provider OAuth additions out of the gateway's policy
boundary.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

import httpx


class ConnectorCredentialError(RuntimeError):
    """Credential storage or validation failed without exposing secret material."""


_IDENTIFIER: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_TOOLSET: Final = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_HEADER_NAME: Final = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_KEYCHAIN_NOT_FOUND: Final = 44
_KEYCHAIN_TIMEOUT_SECONDS: Final = 15
_SECURITY_EXECUTABLE: Final = "/usr/bin/security"
_MAX_CLIENT_ID_BYTES: Final = 4096
_MAX_CLIENT_SECRET_BYTES: Final = 16 * 1024
_MAX_TOKEN_BYTES: Final = 64 * 1024
_MAX_SCOPE_BYTES: Final = 16 * 1024

_CLIENT_ACCOUNT: Final = "oauth-client"
_TOKEN_ACCOUNT: Final = "oauth-token"
# Pre-registered providers use Rally's normalized account names. Providers that
# support dynamic client registration are stored by the MCP SDK under its
# historical ``client``/``tokens`` names. Disconnect must erase both forms so a
# customer never sees "disconnected" while usable OAuth material remains.
_CREDENTIAL_ACCOUNTS: Final = (
    _CLIENT_ACCOUNT,
    _TOKEN_ACCOUNT,
    "client",
    "tokens",
)

_GITHUB_HEADERS: Final = {
    "x-mcp-toolsets": "X-MCP-Toolsets",
    "x-mcp-readonly": "X-MCP-Readonly",
    "x-mcp-lockdown": "X-MCP-Lockdown",
}
DEFAULT_GITHUB_TOOLSETS: Final = (
    "context",
    "repos",
    "issues",
    "pull_requests",
    "users",
)


def _validate_identifier(value: str, label: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ConnectorCredentialError(f"invalid {label}")
    return value


def _validate_secret(value: str, label: str, max_bytes: int) -> str:
    if not isinstance(value, str) or not value:
        raise ConnectorCredentialError(f"invalid {label}")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ConnectorCredentialError(f"invalid {label}")
    if len(value.encode("utf-8")) > max_bytes:
        raise ConnectorCredentialError(f"invalid {label}")
    return value


def _optional_secret(value: str | None, label: str, max_bytes: int) -> str | None:
    return None if value is None else _validate_secret(value, label, max_bytes)


@dataclass(frozen=True, repr=False)
class OAuthClientCredentials:
    """A provider-owned OAuth client registration."""

    client_id: str
    client_secret: str | None = None

    def __post_init__(self) -> None:
        _validate_secret(self.client_id, "OAuth client ID", _MAX_CLIENT_ID_BYTES)
        _optional_secret(self.client_secret, "OAuth client secret", _MAX_CLIENT_SECRET_BYTES)


@dataclass(frozen=True, repr=False)
class OAuthTokenMaterial:
    """The minimum refreshable token state needed by an external bearer client."""

    access_token: str
    refresh_token: str | None = None
    token_type: str = "Bearer"
    expires_at: float | None = None
    scope: str | None = None

    def __post_init__(self) -> None:
        _validate_secret(self.access_token, "OAuth access token", _MAX_TOKEN_BYTES)
        _optional_secret(self.refresh_token, "OAuth refresh token", _MAX_TOKEN_BYTES)
        if not isinstance(self.token_type, str) or self.token_type.casefold() != "bearer":
            raise ConnectorCredentialError("unsupported OAuth token type")
        if self.expires_at is not None and (
            isinstance(self.expires_at, bool) or not isinstance(self.expires_at, (int, float))
        ):
            raise ConnectorCredentialError("invalid OAuth token expiry")
        if self.expires_at is not None:
            try:
                finite_expiry = math.isfinite(self.expires_at)
            except OverflowError:
                finite_expiry = False
            if not finite_expiry:
                raise ConnectorCredentialError("invalid OAuth token expiry")
        _optional_secret(self.scope, "OAuth scope", _MAX_SCOPE_BYTES)


class ProfileKeychainStore:
    """Store one connector user's OAuth state in a namespaced macOS Keychain service."""

    def __init__(self, service: str, profile_id: str):
        base = _validate_identifier(service, "Keychain service")
        profile = _validate_identifier(profile_id, "credential profile")
        self.service = f"{base}-{profile}"

    @classmethod
    def from_namespaced_service(cls, service: str) -> ProfileKeychainStore:
        """Open a service name that was already isolated by Rally's policy snapshot."""
        instance = cls.__new__(cls)
        instance.service = _validate_identifier(service, "Keychain service")
        return instance

    def __repr__(self) -> str:
        return f"{type(self).__name__}(service={self.service!r})"

    def _read(self, account: str) -> str | None:
        try:
            result = subprocess.run(
                [
                    _SECURITY_EXECUTABLE,
                    "find-generic-password",
                    "-w",
                    "-s",
                    self.service,
                    "-a",
                    account,
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=_KEYCHAIN_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ConnectorCredentialError("could not read connector credentials") from exc
        if result.returncode == _KEYCHAIN_NOT_FOUND:
            return None
        if result.returncode != 0:
            raise ConnectorCredentialError("could not read connector credentials")
        return result.stdout.rstrip("\r\n") or None

    def _write(self, account: str, value: str) -> None:
        # Passing -w without an argument makes security(1) read the password from
        # stdin. This prevents OAuth secrets from appearing in process arguments.
        try:
            result = subprocess.run(
                [
                    _SECURITY_EXECUTABLE,
                    "add-generic-password",
                    "-U",
                    "-s",
                    self.service,
                    "-a",
                    account,
                    "-w",
                ],
                check=False,
                input=value + "\n",
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=_KEYCHAIN_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ConnectorCredentialError("could not store connector credentials") from exc
        if result.returncode != 0:
            raise ConnectorCredentialError("could not store connector credentials")

    def _delete(self, account: str) -> bool:
        try:
            result = subprocess.run(
                [
                    _SECURITY_EXECUTABLE,
                    "delete-generic-password",
                    "-s",
                    self.service,
                    "-a",
                    account,
                ],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=_KEYCHAIN_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ConnectorCredentialError("could not delete connector credentials") from exc
        if result.returncode == _KEYCHAIN_NOT_FOUND:
            return False
        if result.returncode != 0:
            raise ConnectorCredentialError("could not delete connector credentials")
        return True

    def save_client(self, credentials: OAuthClientCredentials) -> None:
        payload = {"client_id": credentials.client_id}
        if credentials.client_secret is not None:
            payload["client_secret"] = credentials.client_secret
        self._write(_CLIENT_ACCOUNT, json.dumps(payload, separators=(",", ":")))

    def load_client(self) -> OAuthClientCredentials | None:
        value = self._read(_CLIENT_ACCOUNT)
        if value is None:
            return None
        try:
            payload = json.loads(value)
            if not isinstance(payload, dict) or set(payload) - {"client_id", "client_secret"}:
                raise ValueError
            return OAuthClientCredentials(
                client_id=payload["client_id"],
                client_secret=payload.get("client_secret"),
            )
        except (KeyError, TypeError, ValueError, ConnectorCredentialError) as exc:
            raise ConnectorCredentialError("stored OAuth client credentials are invalid") from exc

    def save_tokens(self, tokens: OAuthTokenMaterial) -> None:
        payload: dict[str, str | float] = {
            "access_token": tokens.access_token,
            "token_type": "Bearer",
        }
        if tokens.refresh_token is not None:
            payload["refresh_token"] = tokens.refresh_token
        if tokens.expires_at is not None:
            payload["expires_at"] = tokens.expires_at
        if tokens.scope is not None:
            payload["scope"] = tokens.scope
        self._write(_TOKEN_ACCOUNT, json.dumps(payload, separators=(",", ":")))

    def load_tokens(self) -> OAuthTokenMaterial | None:
        value = self._read(_TOKEN_ACCOUNT)
        if value is None:
            return None
        try:
            payload = json.loads(value)
            allowed = {"access_token", "refresh_token", "token_type", "expires_at", "scope"}
            if not isinstance(payload, dict) or set(payload) - allowed:
                raise ValueError
            return OAuthTokenMaterial(
                access_token=payload["access_token"],
                refresh_token=payload.get("refresh_token"),
                token_type=payload.get("token_type", "Bearer"),
                expires_at=payload.get("expires_at"),
                scope=payload.get("scope"),
            )
        except (KeyError, TypeError, ValueError, ConnectorCredentialError) as exc:
            raise ConnectorCredentialError("stored OAuth token material is invalid") from exc

    def delete(self) -> bool:
        """Delete all profile secrets, returning whether at least one item existed."""
        deleted = False
        first_error: ConnectorCredentialError | None = None
        for account in _CREDENTIAL_ACCOUNTS:
            try:
                deleted = self._delete(account) or deleted
            except ConnectorCredentialError as exc:
                # A failed client-registration delete must not prevent token deletion
                # (or vice versa). Report a generic error after trying every item.
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise ConnectorCredentialError("could not delete connector credentials") from first_error
        return deleted


def github_read_only_headers(
    toolsets: tuple[str, ...] = DEFAULT_GITHUB_TOOLSETS,
) -> dict[str, str]:
    """Return GitHub's server-enforced least-privilege MCP request headers."""
    if not toolsets:
        raise ConnectorCredentialError("GitHub toolsets cannot be empty")
    normalized: list[str] = []
    seen: set[str] = set()
    for toolset in toolsets:
        if not isinstance(toolset, str) or not _TOOLSET.fullmatch(toolset):
            raise ConnectorCredentialError("invalid GitHub MCP toolset")
        if toolset in seen:
            raise ConnectorCredentialError("duplicate GitHub MCP toolset")
        seen.add(toolset)
        normalized.append(toolset)
    return validate_safe_headers(
        {
            "X-MCP-Toolsets": ",".join(normalized),
            "X-MCP-Readonly": "true",
            "X-MCP-Lockdown": "true",
        }
    )


def validate_safe_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Validate the only provider headers Rally allows credentials to inject."""
    validated: dict[str, str] = {}
    seen: set[str] = set()
    for name, value in headers.items():
        if not isinstance(name, str) or not _HEADER_NAME.fullmatch(name):
            raise ConnectorCredentialError("invalid external credential header name")
        lowered = name.casefold()
        if lowered == "authorization":
            raise ConnectorCredentialError("Authorization header overrides are forbidden")
        canonical = _GITHUB_HEADERS.get(lowered)
        if canonical is None:
            raise ConnectorCredentialError("arbitrary external credential headers are forbidden")
        if lowered in seen:
            raise ConnectorCredentialError("duplicate external credential header")
        if not isinstance(value, str) or not value:
            raise ConnectorCredentialError("invalid external credential header value")
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ConnectorCredentialError("invalid external credential header value")
        if lowered in {"x-mcp-readonly", "x-mcp-lockdown"} and value.casefold() != "true":
            raise ConnectorCredentialError(f"{canonical} cannot weaken Rally's safety posture")
        if lowered == "x-mcp-toolsets":
            parts = value.split(",")
            if not parts or any(not _TOOLSET.fullmatch(part) for part in parts):
                raise ConnectorCredentialError("invalid GitHub MCP toolsets header")
            if len(set(parts)) != len(parts):
                raise ConnectorCredentialError("duplicate GitHub MCP toolset")
            value = ",".join(parts)
        seen.add(lowered)
        validated[canonical] = value
    return validated


class ExternalBearerAuth(httpx.Auth):
    """Load a profile token for every request and inject only validated headers."""

    def __init__(
        self,
        store: ProfileKeychainStore,
        *,
        safe_headers: Mapping[str, str] | None = None,
    ):
        self._store = store
        self._safe_headers = validate_safe_headers(safe_headers or {})

    @classmethod
    def for_github(
        cls,
        store: ProfileKeychainStore,
        *,
        toolsets: tuple[str, ...] = DEFAULT_GITHUB_TOOLSETS,
    ) -> ExternalBearerAuth:
        """Create bearer auth with GitHub's complete server-enforced safety posture."""
        return cls(store, safe_headers=github_read_only_headers(toolsets))

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(service={self._store.service!r}, "
            f"headers={tuple(self._safe_headers)!r})"
        )

    def auth_flow(self, request: httpx.Request):
        occupied = {name.casefold() for name in request.headers}
        if "authorization" in occupied:
            raise ConnectorCredentialError("Authorization header overrides are forbidden")
        if occupied.intersection(name.casefold() for name in self._safe_headers):
            raise ConnectorCredentialError("provider safety header overrides are forbidden")
        tokens = self._store.load_tokens()
        if tokens is None:
            raise ConnectorCredentialError("connector OAuth token is not available")
        request.headers["Authorization"] = f"Bearer {tokens.access_token}"
        request.headers.update(self._safe_headers)
        yield request


def delete_profile_credentials(store: ProfileKeychainStore) -> bool:
    """Disconnect one provider profile by deleting every stored secret."""
    return store.delete()
