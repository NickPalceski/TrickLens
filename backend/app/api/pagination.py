"""Keyset-pagination cursor codec, shared by every `(timestamp, id)`-ordered
listing — the home feed (routes/feed.py) and comment listings
(routes/clips.py) both page this way. See docs/ARCHITECTURE.md §7 for why
keyset rather than OFFSET.
"""

import uuid
from datetime import datetime


def encode_cursor(ts: datetime, item_id: uuid.UUID) -> str:
    return f"{ts.isoformat()}|{item_id}"


def decode_cursor(cursor: str | None) -> tuple[datetime, uuid.UUID] | None:
    """Raises ValueError on a malformed cursor — callers turn that into a
    422, same as before this was factored out of feed.py."""
    if not cursor:
        return None
    ts, _, item_id = cursor.rpartition("|")
    return datetime.fromisoformat(ts), uuid.UUID(item_id)
