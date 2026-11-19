import pytest

from nika.credentials import (
    CredentialStoreError,
    MemoryCredentialStore,
    validate_openai_secret,
)


def test_memory_credential_store_keeps_primary_and_secondary_slots_separate() -> None:
    store = MemoryCredentialStore()
    primary = "sk-test-primary-012345678901234567"
    secondary = "sk-test-secondary-012345678901234567"

    store.set_secret("primary", primary)
    store.set_secret("secondary", secondary)

    assert store.get_secret("primary") == primary
    assert store.get_secret("secondary") == secondary
    store.delete_secret("primary")
    assert store.get_secret("primary") is None
    assert store.get_secret("secondary") == secondary


@pytest.mark.parametrize(
    "secret",
    ["", "not-a-key", "sk-short", "sk-key with spaces 0123456789012345"],
)
def test_openai_secret_validation_rejects_invalid_values(secret: str) -> None:
    with pytest.raises(CredentialStoreError):
        validate_openai_secret(secret)


def test_unknown_credential_slot_is_rejected() -> None:
    store = MemoryCredentialStore()
    with pytest.raises(CredentialStoreError):
        store.get_secret("tertiary")
