"""Verified Google user identity for Rally's public control plane."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Final

from fastapi import Header, HTTPException
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

_MAX_ID_TOKEN_BYTES: Final = 16 * 1024
_SUBJECT: Final = re.compile(r"^[A-Za-z0-9._:-]{1,255}$")


@dataclass(frozen=True, repr=False)
class UserIdentity:
    """Authenticated account data; ``uid`` is the only durable identifier."""

    uid: str
    email: str
    name: str | None = None
    picture: str | None = None
    hosted_domain: str | None = None


def _csv_env(name: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in os.getenv(name, "").split(",") if item.strip())


def _unauthorized(detail: str = "authentication required") -> HTTPException:
    return HTTPException(
        status_code=401,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def verify_google_id_token(token: str) -> UserIdentity:
    """Verify a Google Identity Services ID token and return a stable account."""

    audiences = _csv_env("RALLY_GOOGLE_WEB_CLIENT_IDS")
    if not audiences:
        raise HTTPException(status_code=503, detail="user authentication is not configured")
    if (
        not isinstance(token, str)
        or not token
        or len(token.encode("utf-8")) > _MAX_ID_TOKEN_BYTES
        or any(ord(character) < 33 or ord(character) == 127 for character in token)
    ):
        raise _unauthorized("invalid identity token")

    try:
        claims: dict[str, Any] = google_id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            audience=None,
        )
    except (ValueError, TypeError, OSError):
        raise _unauthorized("invalid identity token") from None

    if claims.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}:
        raise _unauthorized("invalid identity issuer")
    if claims.get("aud") not in audiences:
        raise _unauthorized("identity token was issued for another application")

    uid = claims.get("sub")
    email = claims.get("email")
    if not isinstance(uid, str) or not _SUBJECT.fullmatch(uid):
        raise _unauthorized("identity token has no valid subject")
    if not isinstance(email, str) or not email or claims.get("email_verified") is not True:
        raise _unauthorized("a verified email address is required")

    allowed_emails = {item.casefold() for item in _csv_env("RALLY_ALLOWED_USER_EMAILS")}
    if allowed_emails and email.casefold() not in allowed_emails:
        raise HTTPException(status_code=403, detail="this account is not approved for Rally")

    allowed_domains = {item.casefold() for item in _csv_env("RALLY_ALLOWED_GOOGLE_DOMAINS")}
    hosted_domain = claims.get("hd")
    if allowed_domains and (
        not isinstance(hosted_domain, str)
        or hosted_domain.casefold() not in allowed_domains
    ):
        raise HTTPException(status_code=403, detail="this Google Workspace is not approved")

    return UserIdentity(
        uid=uid,
        email=email,
        name=claims.get("name") if isinstance(claims.get("name"), str) else None,
        picture=claims.get("picture") if isinstance(claims.get("picture"), str) else None,
        hosted_domain=hosted_domain if isinstance(hosted_domain, str) else None,
    )


def require_user(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> UserIdentity:
    """FastAPI dependency that accepts exactly one HTTPS bearer credential."""

    if not authorization:
        raise _unauthorized()
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.casefold() != "bearer" or not token or " " in token:
        raise _unauthorized("invalid authorization header")
    return verify_google_id_token(token)
