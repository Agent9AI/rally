from types import SimpleNamespace

import pytest

from credential_vault import (
    ConnectorSecret,
    CredentialVaultError,
    KmsEnvelopeCipher,
    MemoryConnectorVault,
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
