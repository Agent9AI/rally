from types import SimpleNamespace

import pytest

from credential_vault import (
    ConnectorSecret,
    CredentialVaultBusy,
    CredentialVaultConflict,
    CredentialVaultError,
    KmsEnvelopeCipher,
    MemoryConnectorVault,
    certified_manifest_sha256,
)


class FakeKms:
    def encrypt(self, request):
        return SimpleNamespace(ciphertext=b"kms:" + request["plaintext"][::-1])

    def decrypt(self, request):
        ciphertext = request["ciphertext"]
        if not ciphertext.startswith(b"kms:"):
            raise ValueError("bad wrapped key")
        return SimpleNamespace(plaintext=ciphertext[4:][::-1])


def test_kms_envelope_round_trip_and_ciphertext_redaction():
    cipher = KmsEnvelopeCipher(
        "projects/rally/locations/us-east1/keyRings/connector-vault/cryptoKeys/credentials",
        client=FakeKms(),
    )
    plaintext = b'{"kind":"bearer_token","value":"extremely-secret"}'
    associated_data = b"rally.connector-secret/v1\0user-one\0github"

    envelope = cipher.seal(plaintext, associated_data)

    assert cipher.open(envelope, associated_data) == plaintext
    assert "extremely-secret" not in repr(envelope)
    assert envelope["schema"] == "rally.connector-secret/v1"


def test_envelope_is_bound_to_one_user_and_connector():
    cipher = KmsEnvelopeCipher(
        "projects/rally/locations/us-east1/keyRings/connector-vault/cryptoKeys/credentials",
        client=FakeKms(),
    )
    envelope = cipher.seal(b"secret", b"user-one\0github")

    with pytest.raises(CredentialVaultError, match="could not open"):
        cipher.open(envelope, b"user-two\0github")


@pytest.mark.asyncio
async def test_memory_vault_is_tenant_isolated_and_returns_no_secret_metadata():
    vault = MemoryConnectorVault()
    first = ConnectorSecret("token-one", "bearer_token")
    second = ConnectorSecret("token-two", "bearer_token")

    metadata = await vault.put("user-one", "github", first)
    await vault.put("user-two", "github", second)

    assert metadata.status == "stored_unverified"
    assert "token-one" not in repr(metadata)
    assert await vault.get_secret("user-one", "github") == first
    assert await vault.get_secret("user-two", "github") == second
    assert len(await vault.list("user-one")) == 1
    assert await vault.delete("user-one", "github") is True
    assert await vault.get_secret("user-one", "github") is None
    assert await vault.get_secret("user-two", "github") == second


@pytest.mark.asyncio
async def test_secret_values_and_connector_ids_are_bounded():
    with pytest.raises(CredentialVaultError, match="invalid connector credential"):
        ConnectorSecret("bad\nsecret", "api_key")
    with pytest.raises(CredentialVaultError, match="unsupported"):
        ConnectorSecret("secret", "password")

    vault = MemoryConnectorVault()
    with pytest.raises(CredentialVaultError, match="connector identifier"):
        await vault.delete("user", "../github")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "certification",
    [
        {},
        {"tool_count": 1},
        {"tool_count": 1, "canary_tool": "get_me"},
        {
            "tool_count": 1,
            "canary_tool": "get_me",
            "tool_schema_sha256": "a" * 64,
        },
        {
            "tool_count": 1,
            "canary_tool": "get_me",
            "tool_schema_sha256": "not-a-sha256",
            "proof_version": "rally.connection-certification/v1",
        },
    ],
)
async def test_vault_cannot_mark_ready_without_complete_live_certification(certification):
    vault = MemoryConnectorVault()
    await vault.put("user", "github", ConnectorSecret("secret", "bearer_token"))

    with pytest.raises(
        CredentialVaultError,
        match="ready connection requires live certification",
    ):
        await vault.mark("user", "github", status="ready", **certification)

    record = (await vault.list("user"))[0]
    assert record.status == "stored_unverified"
    assert record.verified_at is None


def live_certification(tool="get_me"):
    manifest = ((tool, "a" * 64),)
    return {
        "status": "ready",
        "tool_count": 1,
        "canary_tool": tool,
        "tool_schema_sha256": "a" * 64,
        "proof_version": "rally.connection-certification/v1",
        "certified_tools": manifest,
        "certified_manifest_sha256": certified_manifest_sha256(manifest),
    }


@pytest.mark.asyncio
async def test_create_is_atomic_and_never_overwrites_an_existing_secret():
    vault = MemoryConnectorVault()
    original = ConnectorSecret("original-secret", "bearer_token")
    await vault.put("user", "github", original)

    with pytest.raises(CredentialVaultConflict):
        await vault.put("user", "github", ConnectorSecret("replacement", "bearer_token"))

    assert await vault.get_secret("user", "github") == original


@pytest.mark.asyncio
async def test_verification_cannot_recertify_after_disconnect_begins():
    vault = MemoryConnectorVault()
    created = await vault.put(
        "user",
        "github",
        ConnectorSecret("original-secret", "bearer_token"),
    )
    begun = await vault.begin_verification(
        "user",
        "github",
        expected_generation=created.credential_generation,
    )
    assert begun is not None
    assert (
        await vault.begin_verification(
            "user",
            "github",
            expected_generation=created.credential_generation,
        )
        is None
    )
    assert await vault.release_execution(
        "user",
        "github",
        expected_lease=begun.execution_lease or "",
    )
    disconnecting = await vault.begin_disconnect("user", "github")
    assert disconnecting is not None

    stale_finish = await vault.finish_verification(
        "user",
        "github",
        expected_generation=created.credential_generation,
        expected_lease=begun.execution_lease or "",
        **live_certification(),
    )

    assert stale_finish is None
    [retained] = await vault.list("user")
    assert retained.status == "needs_attention"
    assert retained.error_code == "disconnect_pending"
    assert retained.certified_tools == ()


@pytest.mark.asyncio
async def test_disconnect_cannot_cross_an_active_execution_lease():
    vault = MemoryConnectorVault()
    await vault.put("user", "github", ConnectorSecret("secret", "bearer_token"))
    await vault.mark("user", "github", **live_certification())
    claimed = await vault.claim_execution("user", "github")
    assert claimed is not None

    with pytest.raises(CredentialVaultBusy):
        await vault.begin_disconnect("user", "github")

    assert await vault.release_execution(
        "user",
        "github",
        expected_lease=claimed.record.execution_lease or "",
    )
    assert await vault.begin_disconnect("user", "github") is not None
