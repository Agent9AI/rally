import pytest
from fastapi import HTTPException

import user_auth


def claims(**overrides):
    value = {
        "iss": "https://accounts.google.com",
        "aud": "rally-client.apps.googleusercontent.com",
        "sub": "google-user-123",
        "email": "terry@example.com",
        "email_verified": True,
        "name": "Terry",
        "picture": "https://example.com/avatar.png",
        "hd": "example.com",
    }
    value.update(overrides)
    return value


def install_verifier(monkeypatch, payload):
    monkeypatch.setenv(
        "RALLY_GOOGLE_WEB_CLIENT_IDS", "rally-client.apps.googleusercontent.com"
    )
    monkeypatch.setattr(
        user_auth.google_id_token,
        "verify_oauth2_token",
        lambda token, request, audience=None: payload,
    )


def test_google_subject_is_the_durable_user_identifier(monkeypatch):
    install_verifier(monkeypatch, claims())

    identity = user_auth.verify_google_id_token("signed-token")

    assert identity.uid == "google-user-123"
    assert identity.email == "terry@example.com"
    assert identity.hosted_domain == "example.com"
    assert "terry@example.com" not in repr(identity)


@pytest.mark.parametrize(
    "payload,detail",
    [
        (claims(aud="attacker.apps.googleusercontent.com"), "another application"),
        (claims(iss="https://attacker.example"), "issuer"),
        (claims(sub="bad/subject"), "subject"),
        (claims(email_verified=False), "verified email"),
    ],
)
def test_invalid_identity_claims_fail_closed(monkeypatch, payload, detail):
    install_verifier(monkeypatch, payload)

    with pytest.raises(HTTPException, match=detail) as error:
        user_auth.verify_google_id_token("signed-token")

    assert error.value.status_code == 401


def test_email_and_workspace_allowlists_are_independent(monkeypatch):
    install_verifier(monkeypatch, claims())
    monkeypatch.setenv("RALLY_ALLOWED_USER_EMAILS", "other@example.com")
    with pytest.raises(HTTPException) as email_error:
        user_auth.verify_google_id_token("signed-token")
    assert email_error.value.status_code == 403

    monkeypatch.delenv("RALLY_ALLOWED_USER_EMAILS")
    monkeypatch.setenv("RALLY_ALLOWED_GOOGLE_DOMAINS", "other.example")
    with pytest.raises(HTTPException) as domain_error:
        user_auth.verify_google_id_token("signed-token")
    assert domain_error.value.status_code == 403


def test_dedicated_identity_header_is_required(monkeypatch):
    with pytest.raises(HTTPException) as missing:
        user_auth.require_user(None)

    expected = user_auth.UserIdentity(uid="google-user-123", email="terry@example.com")
    received = []
    monkeypatch.setattr(
        user_auth,
        "verify_google_id_token",
        lambda token: received.append(token) or expected,
    )

    assert missing.value.status_code == 401
    assert missing.value.headers == {"WWW-Authenticate": "Bearer"}
    assert user_auth.require_user("signed-token") == expected
    assert received == ["signed-token"]


def test_unconfigured_identity_is_unavailable(monkeypatch):
    monkeypatch.delenv("RALLY_GOOGLE_WEB_CLIENT_IDS", raising=False)

    with pytest.raises(HTTPException) as error:
        user_auth.verify_google_id_token("signed-token")

    assert error.value.status_code == 503
