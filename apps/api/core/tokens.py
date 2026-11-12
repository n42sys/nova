"""Secret tokens: generation and hashing. Only SHA-256 hashes are ever stored."""

import hashlib
import re
import secrets

TOKEN_BYTES = 32
_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{43}")  # 32 bytes, URL-safe base64, no padding


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_invitation_token() -> tuple[str, str]:
    """Return (raw token, hash). The raw token goes only into the invitation email."""
    token = secrets.token_urlsafe(TOKEN_BYTES)
    return token, hash_token(token)


def is_well_formed_invitation_token(token: str) -> bool:
    return bool(_TOKEN_RE.fullmatch(token))
