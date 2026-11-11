import uuid

import uuid6


def uuid7() -> uuid.UUID:
    """Time-ordered UUIDv7, used as the default for every primary key."""
    return uuid.UUID(int=uuid6.uuid7().int)
