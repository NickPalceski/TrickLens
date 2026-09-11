"""Comment API schemas.

Likes have no schema of their own — they only ever surface as `like_count`/
`liked_by_me` on `ClipOut` (schemas/clip.py), the same way follows surface as
counts on `UserPublic` with no separate "list of followers" endpoint.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.user import UserBrief


class CommentCreate(BaseModel):
    """Body for POST /clips/{clip_id}/comments. Omitting `parent_id` makes a
    top-level comment; setting it makes a reply — but only to a top-level
    comment, never to another reply (see app/models/social.py)."""

    body: str = Field(min_length=1, max_length=1000)
    parent_id: uuid.UUID | None = None


class CommentOut(BaseModel):
    id: uuid.UUID
    clip_id: uuid.UUID
    author: UserBrief
    body: str
    parent_id: uuid.UUID | None = None
    # Only ever populated on top-level comments — a reply can't have
    # replies, so this is always [] there.
    replies: list["CommentOut"] = []
    created_at: datetime


class CommentPage(BaseModel):
    """One page of top-level comments, keyset-paginated same as FeedPage.
    Replies ride along inline on each item, not paginated separately."""

    items: list[CommentOut]
    next_cursor: str | None = None
