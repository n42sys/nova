"""Symmetric encryption for stored secrets (payment provider keys).

Keys come from NOVA_FERNET_KEYS, newest first. MultiFernet encrypts with the newest key and
decrypts with any of them, so a key is rotated by prepending a new one, running
`manage.py rotate_payment_secrets`, then dropping the old key.

Errors never include plaintext or ciphertext.
"""

from functools import cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class DecryptionError(Exception):
    """Ciphertext could not be decrypted with any configured key."""


_DECRYPT_FAILED = "Stored secret could not be decrypted with the configured keys"


@cache
def _fernet(keys: tuple[str, ...]) -> MultiFernet:
    if not keys:
        raise ImproperlyConfigured("NOVA_FERNET_KEYS is empty")
    try:
        return MultiFernet([Fernet(key.encode()) for key in keys])
    except (ValueError, TypeError) as exc:
        raise ImproperlyConfigured("NOVA_FERNET_KEYS contains an invalid key") from exc


def _current() -> MultiFernet:
    # Keyed on the setting's value so tests (and rotations) that change it take effect.
    return _fernet(tuple(settings.NOVA_FERNET_KEYS))


def encrypt(plaintext: str) -> bytes:
    return _current().encrypt(plaintext.encode())


def decrypt(ciphertext: bytes) -> str:
    try:
        return _current().decrypt(bytes(ciphertext)).decode()
    except InvalidToken:
        raise DecryptionError(_DECRYPT_FAILED) from None


def rotate(ciphertext: bytes) -> bytes:
    """Re-encrypt with the newest key (decrypting with whichever key still works)."""
    try:
        return _current().rotate(bytes(ciphertext))
    except InvalidToken:
        raise DecryptionError(_DECRYPT_FAILED) from None
