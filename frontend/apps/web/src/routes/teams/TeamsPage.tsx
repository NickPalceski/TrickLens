import { formatAverage, useMyInvites, useMyTeams } from '@tricklens/api';
import { Link } from 'react-router';
import { TeamMark } from '../../components/clip/People.tsx';
import { Chip, EmptyState, ErrorState, Loading, SectionHeading } from '../../components/ui/controls.tsx';
import page from '../page.module.css';
import styles from './teams.module.css';

/** /teams: invites waiting for you, and the teams you're on. */
export function TeamsPage() {
  const teams = useMyTeams();
  const invites = useMyInvites();
  const pending = invites.data ?? [];

  return (
    <div className={`${page.page} ${styles.page}`}>
      <div className={page.head}>
        <div>
          <h1 className={page.title}>Teams</h1>
          <p className={page.lead}>Crews that skate together. A team's score is its top 10 clips.</p>
        </div>
        <Link to="/teams/new" className={styles.linkButton}>
          Create a team
        </Link>
      </div>

      {pending.length > 0 && (
        <section className={styles.section} aria-labelledby="invites-title">
          <SectionHeading id="invites-title">Invites · {pending.length}</SectionHeading>
          <ul className={styles.list}>
            {pending.map((inv) => (
              <li key={inv.team.id}>
                <Link to={`/t/${inv.team.slug}`} className={styles.teamCard}>
                  <TeamMark name={inv.team.name} size={2.75} />
                  <span className={styles.teamText}>
                    <span className={styles.teamName}>{inv.team.name}</span>
                    <span className="muted">You're invited. Open it to accept or decline.</span>
                  </span>
                  <Chip tone="yellow">Invite</Chip>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className={styles.section} aria-labelledby="mine-title">
        <SectionHeading id="mine-title">Your teams</SectionHeading>
        {teams.isPending ? (
          <Loading label="Loading your teams" />
        ) : teams.isError ? (
          <ErrorState error={teams.error} onRetry={() => void teams.refetch()} />
        ) : teams.data.length === 0 ? (
          <EmptyState title="You're not on a team yet">
            <p>Start one with at least two friends, or find one to join.</p>
            <Link className="link" to="/discover?tab=teams">
              Rising teams on Discover
            </Link>
          </EmptyState>
        ) : (
          <ul className={styles.list}>
            {teams.data.map((t) => (
              <li key={t.id}>
                <Link to={`/t/${t.slug}`} className={styles.teamCard}>
                  <TeamMark name={t.name} size={2.75} />
                  <span className={styles.teamText}>
                    <span className={styles.teamName}>{t.name}</span>
                    <span className="muted">
                      {t.founded
                        ? `${t.member_count} members · avg ${formatAverage(t.average_score)}`
                        : 'Forming: waiting on founders'}
                    </span>
                  </span>
                  {t.founded ? (
                    <Chip tone={t.my_role === 'owner' ? 'yellow' : t.my_role === 'admin' ? 'azure' : 'plain'}>
                      {t.my_role ?? 'member'}
                    </Chip>
                  ) : (
                    <Chip tone="danger">Forming</Chip>
                  )}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
