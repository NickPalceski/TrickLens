"""Discover API schemas (4d).

Clip rankings reuse ClipOut directly rather than a lighter wrapper — same
shape the feed already returns, and Discover shows the same kind of card.
"""

from decimal import Decimal

from pydantic import BaseModel

from app.schemas.clip import ClipOut
from app.schemas.team import TeamBrief


class DiscoverClipPage(BaseModel):
    """One page of ranked clips. Offset, not keyset, pagination — unlike the
    home feed this reads from a snapshot (`clip_rankings`) that's frozen
    between rebuilds, so the usual keyset justification (rows shifting under
    a paginating client) doesn't apply, and jumping to an arbitrary page is
    a reasonable thing to want on a ranked list."""

    items: list[ClipOut]
    next_offset: int | None = None


class TeamRankingOut(BaseModel):
    team: TeamBrief
    score: Decimal
    score_delta: Decimal


class DiscoverTeamPage(BaseModel):
    items: list[TeamRankingOut]
    next_offset: int | None = None
