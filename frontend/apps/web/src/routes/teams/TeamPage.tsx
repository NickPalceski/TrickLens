import {
  type ClipOut,
  formatAverage,
  formatCount,
  formatScore,
  type TeamMember,
  type TeamOut,
  useAnswerInvite,
  useAnswerJoinRequest,
  useDeleteTeam,
  useInviteMember,
  useJoinRequests,
  useJoinTeam,
  useMe,
  useMyInvites,
  useMyJoinRequest,
  useRemoveMember,
  useSetMemberRole,
  useTeam,
  useTeamClips,
  useTeamMembers,
  useToggleTeamFollow,
  useWithdrawJoin,
} from '@tricklens/api';
import { type FormEvent, type ReactNode, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { ClipMedia, trickNames } from '../../components/clip/ClipMedia.tsx';
import clipStyles from '../../components/clip/clip.module.css';
import { Handle, TeamMark } from '../../components/clip/People.tsx';
import { Icon } from '../../components/icons/Icon.tsx';
import { Avatar } from '../../components/ui/Avatar.tsx';
import { Button } from '../../components/ui/Button.tsx';
import {
  Chip,
  EmptyState,
  ErrorState,
  Field,
  Loading,
  SectionHeading,
} from '../../components/ui/controls.tsx';
import page from '../page.module.css';
import { levelLabel, policyLabel } from './TeamFields.tsx';
import styles from './teams.module.css';

const MAX_MEMBERS = 20; // TEAM_MAX_MEMBERS in the API
const roleTone = (r: string) => (r === 'owner' ? 'yellow' : r === 'admin' ? 'azure' : 'plain');
const errText = (e: unknown) => (e instanceof Error ? e.message : 'Something went wrong.');

function TeamHeader({ team }: { team: TeamOut }) {
  return (
    <div className={styles.identity}>
      <TeamMark name={team.name} size={4.5} />
      <div style={{ minWidth: 0 }}>
        <h1 className={styles.teamTitle}>{team.name}</h1>
        <div className={styles.chips} style={{ margin: '0.5rem 0' }}>
          <Chip tone="azure">{levelLabel(team.level)}</Chip>
          <Chip>{policyLabel(team.join_policy)}</Chip>
        </div>
        {team.description && <p className={styles.description}>{team.description}</p>}
      </div>
    </div>
  );
}

// ---- forming --------------------------------------------------------------

/** A founding invitee's view: accept, or decline (which cancels the whole team). */
function InviteResponse({ team }: { team: TeamOut }) {
  const answer = useAnswerInvite(team.slug);
  const navigate = useNavigate();
  const [confirming, setConfirming] = useState(false);
  return (
    <div className={`${page.page} ${styles.narrow}`}>
      <p className="muted" style={{ marginBottom: '1rem' }}>
        <Handle user={team.owner} /> invited you to help found
      </p>
      <div className={styles.summary}>
        <TeamHeader team={team} />
      </div>
      <div className={styles.warning} style={{ margin: '1.25rem 0' }}>
        <strong>This is bigger than a join request</strong>
        You're one of the people this team is built around. If you decline, the team is cancelled for @
        {team.owner.username} and everyone else invited.
      </div>
      {answer.isError && (
        <p className={styles.error} role="alert">
          {errText(answer.error)}
        </p>
      )}
      <div className={styles.actions} style={{ justifyContent: 'flex-end' }}>
        {confirming ? (
          <>
            <span className="muted">Cancel {team.name} for everyone?</span>
            <Button
              variant="danger"
              onClick={() => answer.mutate(false, { onSuccess: () => navigate('/teams') })}
            >
              Decline and cancel it
            </Button>
            <Button variant="ghost" onClick={() => setConfirming(false)}>
              Keep the invite
            </Button>
          </>
        ) : (
          <>
            <Button variant="ghost-danger" onClick={() => setConfirming(true)}>
              Decline
            </Button>
            <Button onClick={() => answer.mutate(true)} disabled={answer.isPending}>
              Accept and help found it
            </Button>
          </>
        )}
      </div>
    </div>
  );
}

/** The owner's (or an accepted founder's) view while founders are still answering. */
function Forming({ team, isOwner }: { team: TeamOut; isOwner: boolean }) {
  const members = useTeamMembers(team.slug);
  const cancel = useDeleteTeam(team.slug);
  const navigate = useNavigate();
  const [confirming, setConfirming] = useState(false);
  const accepted = members.data ?? [];
  const total = accepted.length + team.pending_founders.length;

  return (
    <div className={`${page.page} ${styles.narrow}`}>
      <Chip tone="danger">Not live yet</Chip>
      <h1 className={page.title} style={{ margin: '0.75rem 0' }}>
        {team.name} is forming
      </h1>
      <p className="muted">
        Nobody else can see the team yet. It goes live once every founder accepts; if anyone declines, it's
        cancelled.
      </p>
      <div className={styles.addRow} style={{ margin: '1.25rem 0 0.5rem', alignItems: 'center' }}>
        <div
          className={clipStyles.bar}
          style={{ height: 8 }}
          role="progressbar"
          aria-label="Founders accepted"
          aria-valuemin={0}
          aria-valuemax={total}
          aria-valuenow={accepted.length}
        >
          <div
            className={clipStyles.barFill}
            style={{ width: `${(accepted.length / Math.max(total, 1)) * 100}%` }}
          />
        </div>
        <span className="mono">
          {accepted.length} of {total} in
        </span>
      </div>
      <ul className={styles.people}>
        {accepted.map((m) => (
          <li key={m.user.id} className={styles.person}>
            <Avatar name={m.user.display_name ?? m.user.username} src={m.user.avatar_url} />
            <span className={styles.personText}>
              <span className={styles.personName}>{m.user.display_name ?? m.user.username}</span>
              <span className="mono muted">@{m.user.username}</span>
            </span>
            <Chip tone={m.role === 'owner' ? 'yellow' : 'azure'}>
              {m.role === 'owner' ? 'Owner' : 'Accepted'}
            </Chip>
          </li>
        ))}
        {team.pending_founders.map((u) => (
          <li key={u.id} className={styles.person}>
            <Avatar name={u.display_name ?? u.username} src={u.avatar_url} />
            <span className={styles.personText}>
              <span className={styles.personName}>{u.display_name ?? u.username}</span>
              <span className="mono muted">@{u.username}</span>
            </span>
            <Chip>Pending</Chip>
          </li>
        ))}
      </ul>
      {isOwner && (
        <div className={styles.actions} style={{ marginTop: '1.5rem' }}>
          {confirming ? (
            <>
              <Button
                variant="danger"
                onClick={() => cancel.mutate(undefined, { onSuccess: () => navigate('/teams') })}
              >
                Cancel it for everyone
              </Button>
              <Button variant="ghost" onClick={() => setConfirming(false)}>
                Keep forming
              </Button>
            </>
          ) : (
            <Button variant="ghost-danger" onClick={() => setConfirming(true)}>
              Cancel team creation
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

// ---- founded --------------------------------------------------------------

/** Follow, join (by policy), leave, settings. */
function TeamActions({ team, meUsername }: { team: TeamOut; meUsername?: string }) {
  const follow = useToggleTeamFollow();
  const join = useJoinTeam(team.slug);
  const withdraw = useWithdrawJoin(team.slug);
  const leave = useRemoveMember(team.slug);
  const invites = useMyInvites();
  const answer = useAnswerInvite(team.slug);
  const member = team.my_role !== null && team.my_role !== undefined;
  const myRequest = useMyJoinRequest(team.slug, !member && team.join_policy === 'request');
  const invited = (invites.data ?? []).some((i) => i.team.id === team.id);
  const [confirmLeave, setConfirmLeave] = useState(false);
  const error = join.error ?? withdraw.error ?? leave.error ?? answer.error;

  let joinArea: ReactNode = null;
  if (!member) {
    if (invited) {
      joinArea = (
        <>
          <Button onClick={() => answer.mutate(true)}>Accept invite</Button>
          <Button variant="ghost" onClick={() => answer.mutate(false)}>
            Decline
          </Button>
        </>
      );
    } else if (team.join_policy === 'open') {
      joinArea = (
        <Button onClick={() => join.mutate()} disabled={join.isPending || team.member_count >= MAX_MEMBERS}>
          {team.member_count >= MAX_MEMBERS ? 'Team is full' : 'Join'}
        </Button>
      );
    } else if (team.join_policy === 'request') {
      joinArea = myRequest.data?.pending ? (
        <Button variant="ghost" onClick={() => withdraw.mutate()} disabled={withdraw.isPending}>
          Request sent · Withdraw
        </Button>
      ) : (
        <Button onClick={() => join.mutate()} disabled={join.isPending || myRequest.isPending}>
          Request to join
        </Button>
      );
    } else {
      joinArea = <span className="muted">Invite only. Ask an owner or admin to invite you.</span>;
    }
  }

  return (
    <>
      <div className={styles.actions}>
        <Button
          variant={team.followed_by_me ? 'azure' : 'ghost'}
          aria-pressed={team.followed_by_me}
          onClick={() => follow.mutate(team)}
        >
          {team.followed_by_me ? '✓ Following' : 'Follow'}
        </Button>
        {joinArea}
        {team.my_role === 'owner' && (
          <Link to={`/t/${team.slug}/settings`} className={styles.linkButton}>
            Team settings
          </Link>
        )}
        {member &&
          team.my_role !== 'owner' &&
          meUsername &&
          (confirmLeave ? (
            <>
              <Button variant="danger" onClick={() => leave.mutate(meUsername)}>
                Leave {team.name}
              </Button>
              <Button variant="ghost" onClick={() => setConfirmLeave(false)}>
                Stay
              </Button>
            </>
          ) : (
            <Button variant="ghost-danger" onClick={() => setConfirmLeave(true)}>
              Leave team
            </Button>
          ))}
      </div>
      {error && (
        <p className={styles.error} role="alert">
          {errText(error)}
        </p>
      )}
    </>
  );
}

/** One member, with what you're allowed to do to them (owner: roles and removal; admin: remove members). */
function MemberRow({ team, m, meUsername }: { team: TeamOut; m: TeamMember; meUsername?: string }) {
  const setRole = useSetMemberRole(team.slug);
  const remove = useRemoveMember(team.slug);
  const [confirm, setConfirm] = useState(false);
  const isOwner = team.my_role === 'owner';
  const canRemove =
    m.role !== 'owner' &&
    m.user.username !== meUsername &&
    (isOwner || (team.my_role === 'admin' && m.role === 'member'));
  const canPromote = isOwner && m.role !== 'owner';
  const name = m.user.display_name ?? m.user.username;

  return (
    <li className={styles.member}>
      <Avatar name={name} src={m.user.avatar_url} />
      <span className={styles.personText}>
        <span className={styles.personName}>{name}</span>
        <Handle user={m.user} />
      </span>
      <Chip tone={roleTone(m.role)}>{m.role}</Chip>
      {confirm ? (
        <span className={styles.actions}>
          <Button variant="danger" size="sm" onClick={() => remove.mutate(m.user.username)}>
            Remove
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setConfirm(false)}>
            Cancel
          </Button>
        </span>
      ) : (
        (canRemove || canPromote) && (
          <details className={styles.menu}>
            <summary aria-label={`Manage @${m.user.username}`}>
              <Icon name="dots" size={18} />
            </summary>
            <div className={styles.menuItems}>
              {canPromote && (
                <button
                  type="button"
                  onClick={() =>
                    setRole.mutate({
                      username: m.user.username,
                      role: m.role === 'admin' ? 'member' : 'admin',
                    })
                  }
                >
                  {m.role === 'admin' ? 'Make a member' : 'Make an admin'}
                </button>
              )}
              {canRemove && (
                <button type="button" className={styles.danger} onClick={() => setConfirm(true)}>
                  Remove from team
                </button>
              )}
            </div>
          </details>
        )
      )}
    </li>
  );
}

function InviteForm({ team }: { team: TeamOut }) {
  const invite = useInviteMember(team.slug);
  const [username, setUsername] = useState('');
  const [sent, setSent] = useState<string | null>(null);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const u = username.trim().replace(/^@/, '').toLowerCase();
    if (!u) return;
    invite.mutate(u, {
      onSuccess: () => {
        setSent(u);
        setUsername('');
      },
    });
  };
  return (
    <form className={styles.addRow} onSubmit={submit}>
      <Field
        label="Invite a member"
        placeholder="@username"
        autoCapitalize="none"
        value={username}
        onChange={(e) => {
          setUsername(e.target.value);
          setSent(null);
        }}
        help={sent ? `Invite sent to @${sent}.` : undefined}
        error={invite.isError ? errText(invite.error) : null}
      />
      <Button type="submit" variant="ghost" disabled={invite.isPending || !username.trim()}>
        Invite
      </Button>
    </form>
  );
}

function JoinRequests({ team }: { team: TeamOut }) {
  const requests = useJoinRequests(team.slug);
  const answer = useAnswerJoinRequest(team.slug);
  const items = requests.data ?? [];
  return (
    <section className={styles.card} aria-labelledby="requests-title">
      <h2 id="requests-title" className={styles.cardTitle}>
        Join requests {items.length > 0 && <Chip tone="yellow">{items.length}</Chip>}
      </h2>
      <p className="muted">Only owners and admins see these.</p>
      {items.length === 0 ? (
        <p className="muted">No one's waiting.</p>
      ) : (
        <ul className={styles.members}>
          {items.map((r) => (
            <li key={r.user.id} className={styles.request}>
              <Avatar name={r.user.display_name ?? r.user.username} src={r.user.avatar_url} size={2} />
              <span className={styles.requestName}>@{r.user.username}</span>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => answer.mutate({ username: r.user.username, accept: false })}
              >
                Decline
              </Button>
              <Button
                variant="azure"
                size="sm"
                onClick={() => answer.mutate({ username: r.user.username, accept: true })}
              >
                Approve
              </Button>
            </li>
          ))}
        </ul>
      )}
      {answer.isError && (
        <p className={styles.error} role="alert">
          {errText(answer.error)}
        </p>
      )}
    </section>
  );
}

function TeamClips({ slug }: { slug: string }) {
  const clips = useTeamClips(slug);
  const items: ClipOut[] = clips.data?.pages.flatMap((p) => p.items) ?? [];
  if (clips.isPending) return <Loading label="Loading clips" />;
  if (items.length === 0)
    return <EmptyState title="No clips yet">Members tag clips to the team when they publish.</EmptyState>;
  return (
    <ul className={styles.clipGrid}>
      {items.map((c) => (
        <li key={c.id}>
          <Link
            to={`/clips/${c.id}`}
            className={styles.tile}
            aria-label={`${trickNames(c)} by @${c.author.username}`}
          >
            <ClipMedia clip={c} aspect="4 / 3" playable={false} showScore={false} showTrick={false}>
              {c.steeze_score && <span className={clipStyles.smallScore}>{formatScore(c.steeze_score)}</span>}
            </ClipMedia>
            {trickNames(c)}
            <span className="mono muted" style={{ fontWeight: 400, fontSize: '0.8125rem' }}>
              @{c.author.username}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

function FoundedTeam({ team }: { team: TeamOut }) {
  const { data: me } = useMe();
  const members = useTeamMembers(team.slug);
  const isAdmin = team.my_role === 'owner' || team.my_role === 'admin';

  return (
    <div className={`${page.page} ${styles.page}`}>
      <header className={styles.hero}>
        <TeamHeader team={team} />
        <div className={styles.side}>
          <dl className={styles.stats}>
            <div className={styles.stat}>
              <dt>Members</dt>
              <dd>
                {team.member_count}/{MAX_MEMBERS}
              </dd>
            </div>
            <div className={styles.stat}>
              <dt>Followers</dt>
              <dd>{formatCount(team.follower_count)}</dd>
            </div>
            <div className={styles.stat}>
              <dt>Team avg</dt>
              <dd>
                <span className={styles.avg}>{formatAverage(team.average_score)}</span>
              </dd>
            </div>
          </dl>
          <TeamActions team={team} meUsername={me?.username} />
        </div>
      </header>

      <div className={styles.columns}>
        <section className={styles.card} aria-labelledby="members-title">
          <h2 id="members-title" className={styles.cardTitle}>
            Members
          </h2>
          {members.isPending ? (
            <Loading label="Loading members" />
          ) : members.isError ? (
            <ErrorState error={members.error} onRetry={() => void members.refetch()} />
          ) : (
            <ul className={styles.members}>
              {members.data.map((m) => (
                <MemberRow key={m.user.id} team={team} m={m} meUsername={me?.username} />
              ))}
            </ul>
          )}
          {isAdmin && <InviteForm team={team} />}
        </section>
        {isAdmin && <JoinRequests team={team} />}
      </div>

      <section className={styles.section} style={{ marginTop: '2rem' }} aria-labelledby="team-clips-title">
        <SectionHeading id="team-clips-title">Clips</SectionHeading>
        <TeamClips slug={team.slug} />
      </section>
    </div>
  );
}

/** /t/:slug: a team, forming or live, from whoever's looking. */
export function TeamPage() {
  const { slug = '' } = useParams();
  const team = useTeam(slug);
  const { data: me } = useMe();
  if (team.isPending) return <Loading label="Loading team" />;
  if (team.isError) {
    return (
      <div className={page.page}>
        <ErrorState error={team.error} onRetry={() => void team.refetch()} />
      </div>
    );
  }
  const t = team.data;
  if (!t.founded) {
    const invited = t.pending_founders.some((u) => u.username === me?.username);
    return invited ? <InviteResponse team={t} /> : <Forming team={t} isOwner={t.my_role === 'owner'} />;
  }
  return <FoundedTeam team={t} />;
}
