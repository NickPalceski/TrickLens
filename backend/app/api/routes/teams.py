"""Team endpoints: founding, settings, roster, join requests/invites, and
following.

Founding is the one unusual state machine here (see app/models/team.py):
`POST /teams` doesn't make a team live — it stays invisible to everyone but
the owner and its founding invitees (`_get_visible` below) until all of them
accept. Accepting the last one stamps `Team.founded_at`; rejecting any one of
them (or the owner cancelling, which is just `DELETE /teams/{slug}` while
still pending) deletes the whole attempt via `ON DELETE CASCADE`, so it can
be redone from scratch with the same slug/name.

`team_join_requests` backs both self-service join requests and owner/admin
invites (`JoinRequestKind`) — the "who resolves this row" split is
REQUEST -> the team's owner/admin, INVITE -> the invited user themselves.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, DbSession, OptionalUser
from app.api.serializers import team_brief, team_member_out, team_out, user_brief
from app.models.enums import JoinPolicy, JoinRequestKind, TeamRole
from app.models.social import Follow
from app.models.team import TEAM_MAX_MEMBERS, Team, TeamJoinRequest, TeamMember
from app.models.user import User
from app.schemas.team import (
    TeamCreate,
    TeamInviteCreate,
    TeamInviteOut,
    TeamJoinRequestOut,
    TeamMemberOut,
    TeamOut,
    TeamRoleUpdate,
    TeamUpdate,
)

router = APIRouter(prefix="/teams", tags=["teams"])


async def _by_username(username: str, db: DbSession) -> User:
    user = await db.scalar(select(User).where(func.lower(User.username) == username.lower()))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    return user


async def _get_team(slug: str, db: DbSession) -> Team:
    team = await db.scalar(select(Team).where(func.lower(Team.slug) == slug.lower()))
    if team is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "team not found")
    return team


async def _get_visible(slug: str, viewer: User | None, db: DbSession) -> Team:
    """A team the caller may see: founded, or one they're the owner of or a
    founding invitee of while it's still forming — same 404-not-403 privacy
    rule clip drafts already use."""
    team = await _get_team(slug, db)
    if team.founded_at is not None:
        return team
    if viewer is not None:
        if team.owner_id == viewer.id:
            return team
        invited = await db.scalar(
            select(TeamJoinRequest.team_id).where(
                TeamJoinRequest.team_id == team.id, TeamJoinRequest.user_id == viewer.id
            )
        )
        if invited is not None:
            return team
    raise HTTPException(status.HTTP_404_NOT_FOUND, "team not found")


async def _get_membership(
    team_id: uuid.UUID, user_id: uuid.UUID, db: DbSession
) -> TeamMember | None:
    return await db.scalar(
        select(TeamMember).where(TeamMember.team_id == team_id, TeamMember.user_id == user_id)
    )


async def _require_admin(team: Team, me: User, db: DbSession) -> None:
    membership = await _get_membership(team.id, me.id, db)
    if membership is None or membership.role not in (TeamRole.OWNER, TeamRole.ADMIN):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "owner/admin only")


async def _add_member_respecting_cap(
    team: Team, user_id: uuid.UUID, role: TeamRole, db: DbSession
) -> None:
    count = await db.scalar(
        select(func.count()).select_from(TeamMember).where(TeamMember.team_id == team.id)
    )
    if (count or 0) >= TEAM_MAX_MEMBERS:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"team is at its {TEAM_MAX_MEMBERS}-member cap"
        )
    db.add(TeamMember(team_id=team.id, user_id=user_id, role=role))
    try:
        await db.flush()
    except IntegrityError as exc:  # lost a race against a concurrent add
        raise HTTPException(status.HTTP_409_CONFLICT, "already a member") from exc


@router.get("/invites/mine")
async def list_my_invites(me: CurrentUser, db: DbSession) -> list[TeamInviteOut]:
    """Every pending invite — founding or not — sent to the caller, across
    all teams. Needed because, unlike everything else in this module, the
    caller doesn't already know a slug to scope the lookup to."""
    requests = await db.scalars(
        select(TeamJoinRequest).where(
            TeamJoinRequest.user_id == me.id, TeamJoinRequest.kind == JoinRequestKind.INVITE
        )
    )
    return [TeamInviteOut(team=team_brief(r.team), created_at=r.created_at) for r in requests]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_team(body: TeamCreate, me: CurrentUser, db: DbSession) -> TeamOut:
    """Doesn't make the team live — see module docstring. Only the owner
    membership exists until every founding invitee accepts."""
    invitees = []
    for username in body.invitee_usernames:
        user = await _by_username(username, db)
        if user.id == me.id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "you can't invite yourself")
        invitees.append(user)

    team = Team(
        name=body.name,
        slug=body.slug,
        description=body.description,
        level=body.level,
        join_policy=body.join_policy,
        owner_id=me.id,
    )
    db.add(team)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "slug already taken") from exc

    db.add(TeamMember(team_id=team.id, user_id=me.id, role=TeamRole.OWNER))
    for user in invitees:
        db.add(TeamJoinRequest(team_id=team.id, user_id=user.id, kind=JoinRequestKind.INVITE))
    await db.flush()

    team = await db.scalar(select(Team).where(Team.id == team.id))
    return await team_out(team, db, viewer=me)


@router.get("/{slug}")
async def read_team(slug: str, db: DbSession, viewer: OptionalUser) -> TeamOut:
    team = await _get_visible(slug, viewer, db)
    return await team_out(team, db, viewer=viewer)


@router.patch("/{slug}")
async def update_team(slug: str, body: TeamUpdate, me: CurrentUser, db: DbSession) -> TeamOut:
    team = await _get_visible(slug, me, db)
    if team.owner_id != me.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "only the owner can update team settings")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(team, field, value)
    await db.flush()
    return await team_out(team, db, viewer=me)


@router.delete("/{slug}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(slug: str, me: CurrentUser, db: DbSession) -> None:
    """Owner-only. Doubles as "cancel" while the team is still forming — the
    exact same operation either way. `ON DELETE CASCADE` on team_members and
    team_join_requests, `SET NULL` on clips.team_id, handle cleanup at the
    DB level; a bulk `delete()` is used (not `db.delete(team)`) so nothing
    needs an ORM relationship loaded first — same reasoning as
    routes/clips.py's delete_comment."""
    team = await _get_visible(slug, me, db)
    if team.owner_id != me.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "only the owner can delete this team")
    await db.execute(delete(Team).where(Team.id == team.id))
    await db.flush()


@router.get("/{slug}/members")
async def list_members(slug: str, db: DbSession, viewer: OptionalUser) -> list[TeamMemberOut]:
    team = await _get_visible(slug, viewer, db)
    members = await db.scalars(
        select(TeamMember).where(TeamMember.team_id == team.id).order_by(TeamMember.joined_at.asc())
    )
    return [team_member_out(m) for m in members]


@router.patch("/{slug}/members/{username}")
async def update_member_role(
    slug: str, username: str, body: TeamRoleUpdate, me: CurrentUser, db: DbSession
) -> TeamMemberOut:
    team = await _get_visible(slug, me, db)
    if team.owner_id != me.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "only the owner can change member roles")
    target = await _by_username(username, db)
    membership = await _get_membership(team.id, target.id, db)
    if membership is None or membership.role == TeamRole.OWNER:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not a member of this team")
    membership.role = body.role
    await db.flush()
    return team_member_out(membership)


@router.delete("/{slug}/members/{username}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(slug: str, username: str, me: CurrentUser, db: DbSession) -> None:
    """Serves both "leave" (self) and "kick" — an owner can remove anyone
    but themselves, an admin only a plain MEMBER, same shape as comment
    delete's author-or-clip-owner rule."""
    team = await _get_visible(slug, me, db)
    target = await _by_username(username, db)
    membership = await _get_membership(team.id, target.id, db)
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not a member of this team")
    if membership.role == TeamRole.OWNER:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "the owner can't be removed — delete the team instead"
        )

    is_self = target.id == me.id
    my_membership = await _get_membership(team.id, me.id, db)
    my_role = my_membership.role if my_membership is not None else None
    allowed = (
        is_self
        or my_role == TeamRole.OWNER
        or (my_role == TeamRole.ADMIN and membership.role == TeamRole.MEMBER)
    )
    if not allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not allowed to remove this member")

    await db.execute(
        delete(TeamMember).where(TeamMember.team_id == team.id, TeamMember.user_id == target.id)
    )
    await db.flush()


@router.post("/{slug}/join", status_code=status.HTTP_201_CREATED)
async def join_team(slug: str, me: CurrentUser, db: DbSession) -> TeamOut:
    team = await _get_visible(slug, me, db)
    if team.founded_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "team hasn't finished forming yet")
    if team.join_policy == JoinPolicy.INVITE_ONLY:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "this team is invite-only")
    if await _get_membership(team.id, me.id, db) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "already a member")

    if team.join_policy == JoinPolicy.REQUEST:
        existing = await db.scalar(
            select(TeamJoinRequest).where(
                TeamJoinRequest.team_id == team.id, TeamJoinRequest.user_id == me.id
            )
        )
        if existing is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "already pending")
        db.add(TeamJoinRequest(team_id=team.id, user_id=me.id, kind=JoinRequestKind.REQUEST))
        try:
            await db.flush()
        except IntegrityError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, "already pending") from exc
        return await team_out(team, db, viewer=me)

    await _add_member_respecting_cap(team, me.id, TeamRole.MEMBER, db)
    return await team_out(team, db, viewer=me)


@router.delete("/{slug}/join")
async def withdraw_join_request(slug: str, me: CurrentUser, db: DbSession) -> TeamOut:
    """Idempotent: withdrawing a request you never made is a no-op 200,
    same as unfollow/unlike."""
    team = await _get_visible(slug, me, db)
    await db.execute(
        delete(TeamJoinRequest).where(
            TeamJoinRequest.team_id == team.id,
            TeamJoinRequest.user_id == me.id,
            TeamJoinRequest.kind == JoinRequestKind.REQUEST,
        )
    )
    await db.flush()
    return await team_out(team, db, viewer=me)


@router.get("/{slug}/join-requests")
async def list_join_requests(slug: str, me: CurrentUser, db: DbSession) -> list[TeamJoinRequestOut]:
    team = await _get_visible(slug, me, db)
    await _require_admin(team, me, db)
    requests = await db.scalars(
        select(TeamJoinRequest)
        .where(TeamJoinRequest.team_id == team.id, TeamJoinRequest.kind == JoinRequestKind.REQUEST)
        .order_by(TeamJoinRequest.created_at.asc())
    )
    return [TeamJoinRequestOut(user=user_brief(r.user), created_at=r.created_at) for r in requests]


@router.post("/{slug}/join-requests/{username}/accept")
async def accept_join_request(
    slug: str, username: str, me: CurrentUser, db: DbSession
) -> TeamMemberOut:
    team = await _get_visible(slug, me, db)
    await _require_admin(team, me, db)
    target = await _by_username(username, db)
    req = await db.scalar(
        select(TeamJoinRequest).where(
            TeamJoinRequest.team_id == team.id,
            TeamJoinRequest.user_id == target.id,
            TeamJoinRequest.kind == JoinRequestKind.REQUEST,
        )
    )
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no pending request from this user")

    await _add_member_respecting_cap(team, target.id, TeamRole.MEMBER, db)
    await db.execute(
        delete(TeamJoinRequest).where(
            TeamJoinRequest.team_id == team.id, TeamJoinRequest.user_id == target.id
        )
    )
    await db.flush()
    member = await _get_membership(team.id, target.id, db)
    return team_member_out(member)


@router.post("/{slug}/join-requests/{username}/reject", status_code=status.HTTP_204_NO_CONTENT)
async def reject_join_request(slug: str, username: str, me: CurrentUser, db: DbSession) -> None:
    team = await _get_visible(slug, me, db)
    await _require_admin(team, me, db)
    target = await _by_username(username, db)
    await db.execute(
        delete(TeamJoinRequest).where(
            TeamJoinRequest.team_id == team.id,
            TeamJoinRequest.user_id == target.id,
            TeamJoinRequest.kind == JoinRequestKind.REQUEST,
        )
    )
    await db.flush()


@router.post("/{slug}/invites", status_code=status.HTTP_204_NO_CONTENT)
async def invite_member(slug: str, body: TeamInviteCreate, me: CurrentUser, db: DbSession) -> None:
    """Post-founding invite from an owner/admin. Founding invites are only
    ever created by create_team — there's no path back into "still
    forming" once founded_at is set."""
    team = await _get_visible(slug, me, db)
    if team.founded_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "team hasn't finished forming yet")
    await _require_admin(team, me, db)

    target = await _by_username(body.username, db)
    if await _get_membership(team.id, target.id, db) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "already a member")

    db.add(TeamJoinRequest(team_id=team.id, user_id=target.id, kind=JoinRequestKind.INVITE))
    try:
        await db.flush()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "already invited or requested") from exc


@router.post("/{slug}/invites/mine/accept")
async def accept_invite(slug: str, me: CurrentUser, db: DbSession) -> TeamOut:
    team = await _get_visible(slug, me, db)
    req = await db.scalar(
        select(TeamJoinRequest).where(
            TeamJoinRequest.team_id == team.id,
            TeamJoinRequest.user_id == me.id,
            TeamJoinRequest.kind == JoinRequestKind.INVITE,
        )
    )
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no pending invite for you on this team")

    await _add_member_respecting_cap(team, me.id, TeamRole.MEMBER, db)
    await db.execute(
        delete(TeamJoinRequest).where(
            TeamJoinRequest.team_id == team.id, TeamJoinRequest.user_id == me.id
        )
    )

    if team.founded_at is None:
        remaining = await db.scalar(
            select(func.count())
            .select_from(TeamJoinRequest)
            .where(
                TeamJoinRequest.team_id == team.id,
                TeamJoinRequest.kind == JoinRequestKind.INVITE,
            )
        )
        if not remaining:
            team.founded_at = datetime.now(UTC)

    await db.flush()
    return await team_out(team, db, viewer=me)


@router.post("/{slug}/invites/mine/reject", status_code=status.HTTP_204_NO_CONTENT)
async def reject_invite(slug: str, me: CurrentUser, db: DbSession) -> None:
    """Rejecting a *founding* invite (team.founded_at is still null) kills
    the whole team-creation attempt, not just this one invite — see the
    module docstring. Rejecting a post-founding invite just removes it."""
    team = await _get_visible(slug, me, db)
    req = await db.scalar(
        select(TeamJoinRequest).where(
            TeamJoinRequest.team_id == team.id,
            TeamJoinRequest.user_id == me.id,
            TeamJoinRequest.kind == JoinRequestKind.INVITE,
        )
    )
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no pending invite for you on this team")

    if team.founded_at is None:
        await db.execute(delete(Team).where(Team.id == team.id))
    else:
        await db.execute(
            delete(TeamJoinRequest).where(
                TeamJoinRequest.team_id == team.id, TeamJoinRequest.user_id == me.id
            )
        )
    await db.flush()


@router.post("/{slug}/follow", status_code=status.HTTP_201_CREATED)
async def follow_team(slug: str, me: CurrentUser, db: DbSession) -> TeamOut:
    team = await _get_visible(slug, me, db)
    if team.founded_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "team hasn't finished forming yet")

    already = await db.scalar(
        select(Follow.id).where(Follow.follower_id == me.id, Follow.followee_team_id == team.id)
    )
    if already is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "already following")

    db.add(Follow(follower_id=me.id, followee_team_id=team.id))
    try:
        await db.flush()
    except IntegrityError as exc:  # lost a race against a concurrent follow
        raise HTTPException(status.HTTP_409_CONFLICT, "already following") from exc
    return await team_out(team, db, viewer=me)


@router.delete("/{slug}/follow")
async def unfollow_team(slug: str, me: CurrentUser, db: DbSession) -> TeamOut:
    team = await _get_visible(slug, me, db)
    await db.execute(
        delete(Follow).where(Follow.follower_id == me.id, Follow.followee_team_id == team.id)
    )
    await db.flush()
    return await team_out(team, db, viewer=me)
