"""Secret tokens: generation and hashing. Only SHA-256 hashes are ever stored."""

import hashlib
import re
import secrets
import string
from dataclasses import dataclass

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


# API tokens: nova_dlv_{prefix}_{secret} (delivery) / nova_prv_{prefix}_{secret} (preview).
# The prefix (8 lowercase alphanumerics) is stored in clear for lookup; the secret (43
# alphanumerics, ~256 bits) is stored only as SHA-256. Neither part contains "_".
API_TOKEN_KIND_TAGS = {"delivery": "dlv", "preview": "prv"}
_PREFIX_ALPHABET = string.ascii_lowercase + string.digits
_SECRET_ALPHABET = string.ascii_letters + string.digits
_API_TOKEN_RE = re.compile(r"nova_(dlv|prv)_([a-z0-9]{8})_([A-Za-z0-9]{43})")


@dataclass(frozen=True, slots=True)
class ParsedApiToken:
    kind: str  # "delivery" | "preview"
    prefix: str
    secret: str


def new_api_token(kind: str) -> tuple[str, str, str]:
    """Return (raw token, prefix, secret hash) for an ApiToken of `kind`."""
    prefix = "".join(secrets.choice(_PREFIX_ALPHABET) for _ in range(8))
    secret = "".join(secrets.choice(_SECRET_ALPHABET) for _ in range(43))
    return f"nova_{API_TOKEN_KIND_TAGS[kind]}_{prefix}_{secret}", prefix, hash_token(secret)


def parse_api_token(raw: str) -> ParsedApiToken | None:
    match = _API_TOKEN_RE.fullmatch(raw)
    if match is None:
        return None
    tag, prefix, secret = match.groups()
    kind = next(kind for kind, kind_tag in API_TOKEN_KIND_TAGS.items() if kind_tag == tag)
    return ParsedApiToken(kind=kind, prefix=prefix, secret=secret)
