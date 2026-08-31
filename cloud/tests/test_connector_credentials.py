import json
import subprocess

import httpx
import pytest

import connector_credentials as credentials_module
from connector_credentials import (
    ConnectorCredentialError,
    ExternalBearerAuth,
    OAuthClientCredentials,
    OAuthTokenMaterial,
    ProfileKeychainStore,
    delete_profile_credentials,
    github_read_only_headers,
    validate_safe_headers,
)


class FakeSecurity:
    def __init__(self):
        self.items = {}
        self.calls = []
        self.fail_command = None
        self.fail_account = None

    def __call__(self, args, **kwargs):
        self.calls.append((list(args), dict(kwargs)))
        command = args[1]
        service = args[args.index("-s") + 1]
        account = args[args.index("-a") + 1]
        if command == self.fail_command or account == self.fail_account:
            return subprocess.CompletedProcess(args, 51, stdout="")
        key = (service, account)
        if command == "add-generic-password":
            self.items[key] = kwargs["input"].rstrip("\n")
            return subprocess.CompletedProcess(args, 0, stdout="")
        if command == "find-generic-password":
            if key not in self.items:
                return subprocess.CompletedProcess(args, 44, stdout="")
            return subprocess.CompletedProcess(args, 0, stdout=self.items[key] + "\n")
        if command == "delete-generic-password":
            if key not in self.items:
                return subprocess.CompletedProcess(args, 44, stdout="")
            del self.items[key]
            return subprocess.CompletedProcess(args, 0, stdout="")
        raise AssertionError(f"unexpected security command: {command}")


@pytest.fixture
def fake_security(monkeypatch):
    runner = FakeSecurity()
    monkeypatch.setattr(credentials_module.subprocess, "run", runner)
    return runner


def test_store_is_profile_namespaced_and_rejects_unsafe_identifiers():
    first = ProfileKeychainStore("rally-connector-github", "p-123")
    second = ProfileKeychainStore("rally-connector-github", "p-456")
    assert first.service == "rally-connector-github-p-123"
    assert first.service != second.service

    with pytest.raises(ConnectorCredentialError, match="invalid Keychain service"):
        ProfileKeychainStore("bad\nservice", "p-123")
    with pytest.raises(ConnectorCredentialError, match="invalid credential profile"):
        ProfileKeychainStore("rally-connector-github", "../other")

    resolved = ProfileKeychainStore.from_namespaced_service("rally-connector-github-p-123")
    assert resolved.service == "rally-connector-github-p-123"
    with pytest.raises(ConnectorCredentialError, match="invalid Keychain service"):
        ProfileKeychainStore.from_namespaced_service("bad/service")


def test_client_credentials_round_trip_without_secret_in_process_arguments(fake_security):
    store = ProfileKeychainStore("rally-connector-github", "p-123")
    client = OAuthClientCredentials("client-123", "super-secret")
    store.save_client(client)

    add_args, add_kwargs = fake_security.calls[0]
    assert add_args[0] == "/usr/bin/security"
    assert add_args[-1] == "-w"
    assert "super-secret" not in " ".join(add_args)
    assert "client-123" not in " ".join(add_args)
    assert "super-secret" in add_kwargs["input"]
    assert add_kwargs["stdout"] is subprocess.DEVNULL
    assert add_kwargs["stderr"] is subprocess.DEVNULL
    assert "super-secret" not in repr(client)

    assert store.load_client() == client


def test_public_client_overwrites_and_removes_a_previous_secret(fake_security):
    store = ProfileKeychainStore("rally-connector-google", "p-123")
    store.save_client(OAuthClientCredentials("client", "old-secret"))
    store.save_client(OAuthClientCredentials("client"))

    loaded = store.load_client()
    assert loaded == OAuthClientCredentials("client")
    assert "old-secret" not in fake_security.items[(store.service, "oauth-client")]


def test_token_material_round_trip_and_repr_are_redaction_safe(fake_security):
    store = ProfileKeychainStore("rally-connector-github", "p-123")
    tokens = OAuthTokenMaterial(
        access_token="access-secret",
        refresh_token="refresh-secret",
        expires_at=1234.5,
        scope="repo read:org",
    )
    store.save_tokens(tokens)

    assert store.load_tokens() == tokens
    assert "access-secret" not in repr(tokens)
    assert "refresh-secret" not in repr(tokens)
    assert "access-secret" not in repr(store)
    add_args, _ = fake_security.calls[0]
    assert "access-secret" not in " ".join(add_args)


@pytest.mark.parametrize(
    "tokens,error",
    [
        ({"access_token": "secret", "token_type": "Basic"}, "unsupported OAuth token type"),
        ({"access_token": "secret", "token_type": 7}, "unsupported OAuth token type"),
        ({"access_token": "bad\nvalue"}, "invalid OAuth access token"),
        ({"access_token": "secret", "expires_at": True}, "invalid OAuth token expiry"),
        ({"access_token": "secret", "expires_at": float("nan")}, "invalid OAuth token expiry"),
        ({"access_token": "secret", "expires_at": float("inf")}, "invalid OAuth token expiry"),
    ],
)
def test_token_material_validation(tokens, error):
    with pytest.raises(ConnectorCredentialError, match=error):
        OAuthTokenMaterial(**tokens)


def test_missing_keychain_items_are_none_but_other_failures_are_generic(fake_security):
    store = ProfileKeychainStore("rally-connector-github", "p-123")
    assert store.load_client() is None
    assert store.load_tokens() is None

    fake_security.fail_command = "find-generic-password"
    with pytest.raises(ConnectorCredentialError, match="could not read") as error:
        store.load_tokens()
    assert "secret" not in str(error.value).casefold()


def test_malformed_stored_values_are_rejected_without_echoing_them(fake_security):
    store = ProfileKeychainStore("rally-connector-github", "p-123")
    poisoned = '{"access_token":"do-not-echo","unexpected":"value"}'
    fake_security.items[(store.service, "oauth-token")] = poisoned

    with pytest.raises(ConnectorCredentialError, match="stored OAuth token material") as error:
        store.load_tokens()
    assert "do-not-echo" not in str(error.value)


def test_disconnect_deletes_all_profile_secrets_and_is_idempotent(fake_security):
    store = ProfileKeychainStore("rally-connector-github", "p-123")
    store.save_client(OAuthClientCredentials("client", "secret"))
    store.save_tokens(OAuthTokenMaterial("token"))

    assert delete_profile_credentials(store) is True
    assert fake_security.items == {}
    assert delete_profile_credentials(store) is False
    delete_accounts = [
        call[0][call[0].index("-a") + 1]
        for call in fake_security.calls
        if call[0][1] == "delete-generic-password"
    ]
    assert delete_accounts == ["oauth-client", "oauth-token", "client", "tokens"] * 2


def test_disconnect_surfaces_keychain_errors_without_secret_values(fake_security):
    store = ProfileKeychainStore("rally-connector-github", "p-123")
    store.save_tokens(OAuthTokenMaterial("never-print-me"))
    fake_security.fail_command = "delete-generic-password"

    with pytest.raises(ConnectorCredentialError, match="could not delete") as error:
        delete_profile_credentials(store)
    assert "never-print-me" not in str(error.value)


def test_disconnect_attempts_every_delete_after_one_item_fails(fake_security):
    store = ProfileKeychainStore("rally-connector-github", "p-123")
    store.save_client(OAuthClientCredentials("client", "client-secret"))
    store.save_tokens(OAuthTokenMaterial("access-secret"))
    fake_security.fail_account = "oauth-client"

    with pytest.raises(ConnectorCredentialError, match="could not delete"):
        delete_profile_credentials(store)

    assert (store.service, "oauth-client") in fake_security.items
    assert (store.service, "oauth-token") not in fake_security.items
    attempted = [
        call[0][call[0].index("-a") + 1]
        for call in fake_security.calls
        if call[0][1] == "delete-generic-password"
    ]
    assert attempted == ["oauth-client", "oauth-token", "client", "tokens"]


def test_github_headers_are_fixed_read_only_and_normalized():
    assert github_read_only_headers(("context", "repos")) == {
        "X-MCP-Toolsets": "context,repos",
        "X-MCP-Readonly": "true",
        "X-MCP-Lockdown": "true",
    }


@pytest.mark.parametrize(
    "headers,error",
    [
        ({"Authorization": "Bearer attacker"}, "Authorization header overrides"),
        ({"X-Anything": "value"}, "arbitrary external credential headers"),
        ({"X-MCP-Readonly": "false"}, "cannot weaken Rally's safety posture"),
        ({"X-MCP-Lockdown": "0"}, "cannot weaken Rally's safety posture"),
        ({"X-MCP-Toolsets": "repos,../../admin"}, "invalid GitHub MCP toolsets"),
        ({"X-MCP-Toolsets": "repos,repos"}, "duplicate GitHub MCP toolset"),
        ({"X-MCP-Toolsets": "repos\r\nAuthorization: x"}, "header value"),
        ({"X-MCP-Readonly\nX-Evil": "true"}, "header name"),
    ],
)
def test_header_validation_rejects_unsafe_or_arbitrary_values(headers, error):
    with pytest.raises(ConnectorCredentialError, match=error):
        validate_safe_headers(headers)


def test_header_validation_rejects_case_insensitive_duplicates():
    with pytest.raises(ConnectorCredentialError, match="duplicate external credential header"):
        validate_safe_headers({"X-MCP-Readonly": "true", "x-mcp-readonly": "true"})


def test_github_header_builder_rejects_empty_duplicate_and_unsafe_toolsets():
    with pytest.raises(ConnectorCredentialError, match="cannot be empty"):
        github_read_only_headers(())
    with pytest.raises(ConnectorCredentialError, match="duplicate"):
        github_read_only_headers(("repos", "repos"))
    with pytest.raises(ConnectorCredentialError, match="invalid"):
        github_read_only_headers(("repos,issues",))


def test_external_bearer_auth_reads_keychain_and_injects_github_safety_headers(fake_security):
    store = ProfileKeychainStore("rally-connector-github", "p-123")
    store.save_tokens(OAuthTokenMaterial("token-one"))
    auth = ExternalBearerAuth(store, safe_headers=github_read_only_headers(("repos", "issues")))
    request = httpx.Request("POST", "https://api.githubcopilot.com/mcp")

    authenticated = next(auth.auth_flow(request))
    assert authenticated.headers["Authorization"] == "Bearer token-one"
    assert authenticated.headers["X-MCP-Toolsets"] == "repos,issues"
    assert authenticated.headers["X-MCP-Readonly"] == "true"
    assert authenticated.headers["X-MCP-Lockdown"] == "true"
    assert "token-one" not in repr(auth)

    store.save_tokens(OAuthTokenMaterial("token-two"))
    second = next(auth.auth_flow(httpx.Request("POST", "https://api.githubcopilot.com/mcp")))
    assert second.headers["Authorization"] == "Bearer token-two"


def test_github_auth_constructor_cannot_omit_fixed_safety_headers(fake_security):
    store = ProfileKeychainStore("rally-connector-github", "p-123")
    store.save_tokens(OAuthTokenMaterial("stored-token"))
    auth = ExternalBearerAuth.for_github(store, toolsets=("repos",))

    request = next(auth.auth_flow(httpx.Request("POST", "https://api.githubcopilot.com/mcp")))
    assert request.headers["X-MCP-Toolsets"] == "repos"
    assert request.headers["X-MCP-Readonly"] == "true"
    assert request.headers["X-MCP-Lockdown"] == "true"


def test_external_bearer_auth_rejects_request_authorization_override(fake_security):
    store = ProfileKeychainStore("rally-connector-github", "p-123")
    store.save_tokens(OAuthTokenMaterial("stored-token"))
    auth = ExternalBearerAuth(store)
    request = httpx.Request(
        "POST",
        "https://api.githubcopilot.com/mcp",
        headers={"authorization": "Bearer attacker"},
    )

    with pytest.raises(ConnectorCredentialError, match="Authorization header overrides"):
        next(auth.auth_flow(request))


def test_external_bearer_auth_rejects_request_safety_header_override(fake_security):
    store = ProfileKeychainStore("rally-connector-github", "p-123")
    store.save_tokens(OAuthTokenMaterial("stored-token"))
    auth = ExternalBearerAuth(store, safe_headers=github_read_only_headers(("repos",)))
    request = httpx.Request(
        "POST",
        "https://api.githubcopilot.com/mcp",
        headers={"x-mcp-readonly": "false"},
    )

    with pytest.raises(ConnectorCredentialError, match="safety header overrides"):
        next(auth.auth_flow(request))


def test_external_bearer_auth_fails_closed_when_token_is_missing(fake_security):
    store = ProfileKeychainStore("rally-connector-github", "p-123")
    auth = ExternalBearerAuth(store)

    with pytest.raises(ConnectorCredentialError, match="token is not available"):
        next(auth.auth_flow(httpx.Request("GET", "https://example.invalid/mcp")))


def test_test_fixture_serialization_matches_the_store_contract(fake_security):
    store = ProfileKeychainStore("rally-connector-github", "p-123")
    store.save_tokens(OAuthTokenMaterial("token"))
    saved = json.loads(fake_security.items[(store.service, "oauth-token")])
    assert saved == {"access_token": "token", "token_type": "Bearer"}
