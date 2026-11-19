"""Windows Credential Manager integration for local Nika API secrets."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from typing import Protocol

CREDENTIAL_TYPE_GENERIC = 1
CREDENTIAL_PERSIST_LOCAL_MACHINE = 2
PRIMARY_TARGET = "NikaCompanion/OpenAI/Primary"
SECONDARY_TARGET = "NikaCompanion/OpenAI/Secondary"
MAX_API_KEY_CHARS = 4096


class CredentialStoreError(RuntimeError):
    """A local operating-system credential operation failed."""


class CredentialStore(Protocol):
    """Minimal secret-store contract used by the provider manager."""

    def get_secret(self, slot: str) -> str | None: ...
    def set_secret(self, slot: str, secret: str) -> None: ...
    def delete_secret(self, slot: str) -> None: ...


def validate_openai_secret(secret: str) -> str:
    """Validate key shape without including any secret bytes in errors."""
    if not isinstance(secret, str):
        raise CredentialStoreError("API key must be text.")
    value = secret.strip()
    if (
        not value.startswith("sk-")
        or not 20 <= len(value) <= MAX_API_KEY_CHARS
        or any(character.isspace() for character in value)
        or "\x00" in value
    ):
        raise CredentialStoreError("The OpenAI API key has an invalid format.")
    return value


def _target_for_slot(slot: str) -> str:
    targets = {
        "primary": PRIMARY_TARGET,
        "secondary": SECONDARY_TARGET,
    }
    try:
        return targets[slot]
    except KeyError:
        raise CredentialStoreError("Unknown OpenAI credential slot.") from None


class WindowsCredentialStore:
    """Store secrets in the current Windows user's Credential Manager."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise CredentialStoreError(
                "Windows Credential Manager is available only on Windows."
            )
        self._advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        self._advapi32.CredWriteW.argtypes = [
            ctypes.POINTER(_CREDENTIALW),
            wintypes.DWORD,
        ]
        self._advapi32.CredWriteW.restype = wintypes.BOOL
        self._advapi32.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(_CREDENTIALW)),
        ]
        self._advapi32.CredReadW.restype = wintypes.BOOL
        self._advapi32.CredDeleteW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        self._advapi32.CredDeleteW.restype = wintypes.BOOL
        self._advapi32.CredFree.argtypes = [ctypes.c_void_p]
        self._advapi32.CredFree.restype = None

    def get_secret(self, slot: str) -> str | None:
        target = _target_for_slot(slot)
        pointer = ctypes.POINTER(_CREDENTIALW)()
        if not self._advapi32.CredReadW(
            target, CREDENTIAL_TYPE_GENERIC, 0, ctypes.byref(pointer)
        ):
            error = ctypes.get_last_error()
            if error == 1168:  # ERROR_NOT_FOUND
                return None
            raise CredentialStoreError(
                f"Windows Credential Manager could not read slot {slot} (error {error})."
            )
        try:
            credential = pointer.contents
            size = int(credential.CredentialBlobSize)
            if size <= 0 or size > MAX_API_KEY_CHARS * 4:
                raise CredentialStoreError("Stored credential has an invalid size.")
            raw = ctypes.string_at(credential.CredentialBlob, size)
            try:
                secret = raw.decode("utf-8")
            except UnicodeDecodeError:
                raise CredentialStoreError(
                    "Stored credential is not valid UTF-8."
                ) from None
            return validate_openai_secret(secret)
        finally:
            self._advapi32.CredFree(pointer)

    def set_secret(self, slot: str, secret: str) -> None:
        target = _target_for_slot(slot)
        value = validate_openai_secret(secret)
        raw = bytearray(value.encode("utf-8"))
        buffer = ctypes.create_string_buffer(bytes(raw), len(raw))
        credential = _CREDENTIALW()
        credential.Type = CREDENTIAL_TYPE_GENERIC
        credential.TargetName = target
        credential.Comment = "Nika Companion OpenAI API credential"
        credential.CredentialBlobSize = len(raw)
        credential.CredentialBlob = ctypes.cast(
            buffer, ctypes.POINTER(wintypes.BYTE)
        )
        credential.Persist = CREDENTIAL_PERSIST_LOCAL_MACHINE
        credential.UserName = "Nika Companion"
        try:
            if not self._advapi32.CredWriteW(ctypes.byref(credential), 0):
                error = ctypes.get_last_error()
                raise CredentialStoreError(
                    f"Windows Credential Manager could not save slot {slot} (error {error})."
                )
        finally:
            ctypes.memset(buffer, 0, len(raw))
            for index in range(len(raw)):
                raw[index] = 0

    def delete_secret(self, slot: str) -> None:
        target = _target_for_slot(slot)
        if not self._advapi32.CredDeleteW(target, CREDENTIAL_TYPE_GENERIC, 0):
            error = ctypes.get_last_error()
            if error != 1168:  # ERROR_NOT_FOUND
                raise CredentialStoreError(
                    f"Windows Credential Manager could not remove slot {slot} (error {error})."
                )


class MemoryCredentialStore:
    """Non-persistent fake store for tests; never used by the production runtime."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def get_secret(self, slot: str) -> str | None:
        _target_for_slot(slot)
        return self._values.get(slot)

    def set_secret(self, slot: str, secret: str) -> None:
        _target_for_slot(slot)
        self._values[slot] = validate_openai_secret(secret)

    def delete_secret(self, slot: str) -> None:
        _target_for_slot(slot)
        self._values.pop(slot, None)


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(wintypes.BYTE)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def create_credential_store() -> CredentialStore:
    """Return the production secret store for the current operating system."""
    return WindowsCredentialStore()
