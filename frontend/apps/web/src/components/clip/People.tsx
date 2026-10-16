import type { TeamBrief, UserBrief } from '@tricklens/api';
import { Link } from 'react-router';
import styles from './clip.module.css';

/** A team's yellow initials mark. */
export function TeamMark({ name, size = 1.125 }: { name: string; size?: number }) {
  const initials = name
    .split(/\s+/)
    .map((w) => w[0] ?? '')
    .join('')
    .slice(0, 2)
    .toUpperCase();
  return (
    <span
      className={styles.teamMark}
      style={{ width: `${size}rem`, height: `${size}rem`, fontSize: `${(size * 0.42).toFixed(3)}rem` }}
      aria-hidden="true"
    >
      {initials}
    </span>
  );
}

/** "DS Downtown Skaters", linking to the team. */
export function TeamLine({ team, suffix }: { team: TeamBrief; suffix?: string }) {
  return (
    <Link to={`/t/${team.slug}`} className={styles.team}>
      <TeamMark name={team.name} />
      {team.name}
      {suffix && <span className="muted"> · {suffix}</span>}
    </Link>
  );
}

/** "@handle", linking to the profile. */
export function Handle({ user }: { user: UserBrief }) {
  return (
    <Link to={`/u/${user.username}`} className={styles.handle}>
      @{user.username}
    </Link>
  );
}
