import {
  type ClipOut,
  type DiscoverSort,
  formatAverage,
  formatCount,
  toNumber,
  useDiscoverClips,
  useDiscoverTeams,
} from '@tricklens/api';
import { Link, useSearchParams } from 'react-router';
import { useIsDesktop } from '../../app/useMediaQuery.ts';
import { ClipMedia, trickNames } from '../../components/clip/ClipMedia.tsx';
import clipStyles from '../../components/clip/clip.module.css';
import { TeamMark } from '../../components/clip/People.tsx';
import { Button } from '../../components/ui/Button.tsx';
import { EmptyState, ErrorState, Loading, Pills, Segmented } from '../../components/ui/controls.tsx';
import page from '../page.module.css';
import styles from './DiscoverPage.module.css';

const SORTS = [
  { value: 'score', label: 'Top scores' },
  { value: 'engagement', label: 'Most active' },
] as const;

const TABS = [
  { value: 'clips', label: 'Clips' },
  { value: 'teams', label: 'Teams' },
] as const;

function RankedClip({ clip, rank }: { clip: ClipOut; rank: number }) {
  const score = toNumber(clip.steeze_score);
  const label = `#${rank} ${trickNames(clip)} by @${clip.author.username}${score !== null ? `, score ${Math.round(score)}` : ''}`;
  return (
    <li>
      <Link to={`/clips/${clip.id}`} className={styles.clipCard} aria-label={label}>
        <ClipMedia clip={clip} playable={false} showScore={false} showTrick={false}>
          <span className={`${styles.rank} ${rank === 1 ? styles.first : ''}`}>#{rank}</span>
          {score !== null && <span className={clipStyles.smallScore}>{Math.round(score)}</span>}
        </ClipMedia>
        <span className={styles.clipName}>{trickNames(clip)}</span>
        <span className={styles.clipMeta}>
          <span className={styles.clipHandle}>@{clip.author.username}</span>
          <span className="mono">
            ♥ {formatCount(clip.like_count)} · ▶ {formatCount(clip.view_count)}
          </span>
        </span>
      </Link>
    </li>
  );
}

function ClipsSection({ sort, onSort }: { sort: DiscoverSort; onSort: (s: DiscoverSort) => void }) {
  const clips = useDiscoverClips(sort);
  const items = clips.data?.pages.flatMap((p) => p.items) ?? [];
  return (
    <section className={styles.clips} aria-label="Top clips this week">
      <div className={styles.sortRow}>
        <Pills label="Rank clips by" options={SORTS} value={sort} onChange={onSort} />
      </div>
      {clips.isPending ? (
        <Loading label="Loading clips" />
      ) : clips.isError ? (
        <ErrorState error={clips.error} onRetry={() => void clips.refetch()} />
      ) : items.length === 0 ? (
        <EmptyState title="Nothing ranked yet">
          <p>Clips published this week show up here after the next refresh.</p>
        </EmptyState>
      ) : (
        <ol className={styles.grid}>
          {items.map((c, i) => (
            <RankedClip key={c.id} clip={c} rank={i + 1} />
          ))}
        </ol>
      )}
      {clips.hasNextPage && (
        <div className={page.loadMore}>
          <Button
            variant="ghost"
            onClick={() => void clips.fetchNextPage()}
            disabled={clips.isFetchingNextPage}
          >
            Show more
          </Button>
        </div>
      )}
      <p className={page.note}>
        Top scores ranks clips whose score counts toward the skater's average. Most active ranks every clip by
        views, likes and comments.
      </p>
    </section>
  );
}

function TeamsSection() {
  const teams = useDiscoverTeams();
  const items = teams.data?.items ?? [];
  return (
    <section className={`${page.card} ${styles.teams}`} aria-labelledby="rising-title">
      <h2 id="rising-title" className={styles.teamsTitle}>
        Rising teams
      </h2>
      <p className={page.note}>Biggest jump in team average over the last 7 days.</p>
      {teams.isPending ? (
        <Loading label="Loading teams" />
      ) : teams.isError ? (
        <ErrorState error={teams.error} onRetry={() => void teams.refetch()} />
      ) : items.length === 0 ? (
        <p className={page.note}>No team has a week of history yet.</p>
      ) : (
        <ol className={styles.teamList}>
          {items.map((t, i) => {
            const delta = toNumber(t.score_delta) ?? 0;
            return (
              <li key={t.team.id} className={styles.teamRow}>
                <span className={`${styles.teamRank} ${i === 0 ? styles.first : ''}`}>{i + 1}</span>
                <TeamMark name={t.team.name} size={2.375} />
                <span className={styles.teamText}>
                  <Link to={`/t/${t.team.slug}`} className={styles.teamName}>
                    {t.team.name}
                  </Link>
                  <span className="mono muted">avg {formatAverage(t.score)}</span>
                </span>
                <span className={styles.delta}>
                  <span className={styles.deltaNum}>
                    {delta >= 0 ? '+' : '−'}
                    {Math.abs(delta).toFixed(1)}
                  </span>
                  <span className={styles.deltaLabel}>7 days</span>
                </span>
              </li>
            );
          })}
        </ol>
      )}
      <p className={page.note}>Teams younger than a week aren't ranked yet.</p>
    </section>
  );
}

export function DiscoverPage() {
  const [params, setParams] = useSearchParams();
  const isDesktop = useIsDesktop();
  const sort: DiscoverSort = params.get('sort') === 'engagement' ? 'engagement' : 'score';
  const tab = params.get('tab') === 'teams' ? 'teams' : 'clips';
  const update = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    next.set(key, value);
    setParams(next, { replace: true });
  };

  return (
    <div className={page.page}>
      <div className={page.head}>
        <div>
          <h1 className={page.title}>Discover</h1>
          <p className={page.lead}>
            The best of this week, from everyone. Rankings refresh every 30 minutes.
          </p>
        </div>
      </div>
      {isDesktop ? (
        <div className={styles.columns}>
          <ClipsSection sort={sort} onSort={(s) => update('sort', s)} />
          <TeamsSection />
        </div>
      ) : (
        <div className={styles.stack}>
          <Segmented label="Show" options={TABS} value={tab} onChange={(t) => update('tab', t)} block />
          {tab === 'clips' ? (
            <ClipsSection sort={sort} onSort={(s) => update('sort', s)} />
          ) : (
            <TeamsSection />
          )}
        </div>
      )}
    </div>
  );
}
