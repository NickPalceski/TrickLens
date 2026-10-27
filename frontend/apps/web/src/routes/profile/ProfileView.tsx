import {
  type ClipOut,
  formatAverage,
  formatCount,
  type Profile,
  toNumber,
  type UserPublic,
  useToggleFollow,
  useUserClips,
} from '@tricklens/api';
import { Link } from 'react-router';
import { ClipMedia, trickNames } from '../../components/clip/ClipMedia.tsx';
import clipStyles from '../../components/clip/clip.module.css';
import { Icon } from '../../components/icons/Icon.tsx';
import { Avatar } from '../../components/ui/Avatar.tsx';
import { Button } from '../../components/ui/Button.tsx';
import { Chip, EmptyState, ErrorState, Loading, SectionHeading } from '../../components/ui/controls.tsx';
import page from '../page.module.css';
import styles from './ProfileView.module.css';

const STANCE = { regular: 'Regular', goofy: 'Goofy' } as const;
const STYLE = { street: 'Street', vert: 'Vert', mix: 'Mix' } as const;

/** The setup sheet, skipping anything the skater left blank. */
function setupRows(p: Profile | null | undefined): [string, string][] {
  if (!p) return [];
  const rows: [string, string | null | undefined][] = [
    ['Stance', p.stance ? STANCE[p.stance] : null],
    ['Style', p.style ? STYLE[p.style] : null],
    ['Board', [p.board, p.board_size && `${p.board_size}″`].filter(Boolean).join(' ')],
    ['Wheels', [p.wheels, p.wheel_size && `${p.wheel_size}mm`].filter(Boolean).join(' ')],
    ['Trucks', p.trucks],
    ['Bearings', p.bearings],
  ];
  return rows.filter((r): r is [string, string] => Boolean(r[1]));
}

function ClipTile({ clip }: { clip: ClipOut }) {
  const score = toNumber(clip.steeze_score);
  return (
    <li>
      <Link to={`/clips/${clip.id}`} className={styles.tile}>
        <ClipMedia clip={clip} aspect="4 / 3" playable={false} showScore={false} showTrick={false}>
          {!clip.score_included && (
            <span className={styles.notCounted}>
              <Chip>Not counted</Chip>
            </span>
          )}
          {score !== null && (
            <span className={`${clipStyles.smallScore} ${clip.score_included ? '' : clipStyles.muted}`}>
              {Math.round(score)}
            </span>
          )}
        </ClipMedia>
        <span className={styles.tileName}>{trickNames(clip)}</span>
      </Link>
    </li>
  );
}

function Clips({ username, own }: { username: string; own: boolean }) {
  const clips = useUserClips(username);
  const items = clips.data?.pages.flatMap((p) => p.items) ?? [];
  if (clips.isPending) return <Loading label="Loading clips" />;
  if (clips.isError) return <ErrorState error={clips.error} onRetry={() => void clips.refetch()} />;
  if (items.length === 0) {
    return (
      <EmptyState title="No clips yet">
        {own && (
          <Link className="link" to="/upload">
            Upload your first clip
          </Link>
        )}
      </EmptyState>
    );
  }
  return (
    <>
      <ul className={styles.grid}>
        {items.map((c) => (
          <ClipTile key={c.id} clip={c} />
        ))}
      </ul>
      {clips.hasNextPage && (
        <div className={page.loadMore}>
          <Button variant="ghost" onClick={() => void clips.fetchNextPage()}>
            Show more
          </Button>
        </div>
      )}
    </>
  );
}

/** A skater's profile: who they are, their numbers, their setup and clips. Own or someone else's. */
export function ProfileView({ user, own }: { user: UserPublic; own: boolean }) {
  const follow = useToggleFollow();
  const name = user.display_name ?? user.username;
  const setup = setupRows(user.profile);

  return (
    <div className={page.page}>
      <header className={styles.head}>
        <div className={styles.identity}>
          <Avatar name={name} src={user.avatar_url} size={5} />
          <div className={styles.names}>
            <h1 className={styles.name}>{name}</h1>
            <p className={`mono ${styles.handle}`}>@{user.username}</p>
            {user.bio && <p className={styles.bio}>{user.bio}</p>}
          </div>
        </div>
        <div className={styles.side}>
          <dl className={styles.stats}>
            <div className={styles.stat}>
              <dt>Followers</dt>
              <dd>{formatCount(user.follower_count)}</dd>
            </div>
            <div className={styles.stat}>
              <dt>Following</dt>
              <dd>{formatCount(user.following_count)}</dd>
            </div>
            <div className={styles.stat}>
              <dt>Avg steeze</dt>
              <dd>
                <span className={styles.avg}>{formatAverage(user.average_score)}</span>
              </dd>
            </div>
          </dl>
          <div className={styles.buttons}>
            {own ? (
              <>
                <Link to="/profile/edit" className={styles.linkButton}>
                  Edit profile
                </Link>
                <Link
                  to="/settings"
                  className={`${styles.linkButton} ${styles.iconOnly}`}
                  aria-label="Settings"
                >
                  <Icon name="gear" size={18} />
                </Link>
              </>
            ) : (
              <Button
                variant={user.followed_by_me ? 'azure' : 'primary'}
                aria-pressed={user.followed_by_me}
                onClick={() => follow.mutate(user)}
                disabled={follow.isPending}
                className={styles.follow}
              >
                {user.followed_by_me ? '✓ Following' : 'Follow'}
              </Button>
            )}
          </div>
        </div>
      </header>

      <section className={styles.section} aria-labelledby="setup-title">
        <SectionHeading id="setup-title">Setup</SectionHeading>
        {setup.length ? (
          <dl className={styles.setup}>
            {setup.map(([k, v]) => (
              <div key={k} className={styles.setupItem}>
                <dt>{k}</dt>
                <dd className="mono">{v}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className={page.note}>
            {own ? (
              <>
                No setup yet.{' '}
                <Link className="link" to="/profile/edit">
                  Add your stance and gear
                </Link>
                .
              </>
            ) : (
              'No setup shared yet.'
            )}
          </p>
        )}
      </section>

      <section className={styles.section} aria-labelledby="clips-title">
        <SectionHeading id="clips-title">Clips</SectionHeading>
        <Clips username={user.username} own={own} />
        <p className={page.note}>
          Avg steeze counts every published clip whose score is included. "Not counted" clips still play; they
          just sit out of the average.
        </p>
      </section>
    </div>
  );
}
