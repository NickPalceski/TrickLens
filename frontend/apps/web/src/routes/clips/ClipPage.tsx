import {
  type ClipOut,
  formatTimeAgo,
  formatTrickName,
  useClip,
  useMe,
  useRecordView,
  useSetScoreIncluded,
} from '@tricklens/api';
import { useRef } from 'react';
import { Link, useParams } from 'react-router';
import { ClipActions } from '../../components/clip/ClipActions.tsx';
import { ClipMedia } from '../../components/clip/ClipMedia.tsx';
import { FailureCard } from '../../components/clip/FailureCard.tsx';
import { Handle, TeamLine } from '../../components/clip/People.tsx';
import { confidenceLabel, ScoreBlock, SubscoreBars } from '../../components/clip/Score.tsx';
import { TrickBreakdown, TrickTimeline } from '../../components/clip/TrickBreakdown.tsx';
import { CommentThread } from '../../components/comments/Comments.tsx';
import { Avatar } from '../../components/ui/Avatar.tsx';
import { Chip, ErrorState, Loading, SectionHeading, Switch } from '../../components/ui/controls.tsx';
import page from '../page.module.css';
import styles from './ClipPage.module.css';

function NotScored({ clip }: { clip: ClipOut }) {
  if (clip.status === 'unanalyzable') return <FailureCard clip={clip} />;
  return (
    <section className={`${page.card} ${styles.failed}`}>
      <Chip>Not published</Chip>
      <p>
        This clip is still {clip.status === 'analyzed' ? 'waiting to be published' : clip.status}.{' '}
        <Link className="link" to={`/upload/${clip.id}`}>
          Continue in the upload flow
        </Link>
      </p>
    </section>
  );
}

function Breakdown({ clip, own }: { clip: ClipOut; own: boolean }) {
  const setIncluded = useSetScoreIncluded();
  const analysis = clip.analysis;
  const tricks = analysis?.tricks ?? [];
  const landed = tricks.filter((t) => t.outcome === 'landed').length;
  const multi = tricks.length > 1;

  return (
    <section className={styles.breakdown} aria-labelledby="score-title">
      <div className={styles.scoreHead}>
        <h2 id="score-title" className="label">
          {multi ? 'Clip score' : 'Steeze breakdown'}
        </h2>
      </div>
      <ScoreBlock
        score={clip.steeze_score}
        chip={multi ? `${landed} of ${tricks.length} landed` : confidenceLabel(analysis?.confidence)}
      />
      {multi && (
        <p className={styles.explain}>
          Averaged over the {landed} landed {landed === 1 ? 'trick' : 'tricks'}. Bails don't count against
          you.
        </p>
      )}
      {own && (
        <div className={styles.include}>
          <Switch
            label="Counts toward your average"
            description="Change it any time, even after publishing. The clip stays up either way."
            checked={clip.score_included}
            disabled={setIncluded.isPending}
            onChange={(included) => setIncluded.mutate({ clipId: clip.id, included })}
          />
        </div>
      )}
      {multi ? (
        <TrickBreakdown
          tricks={tricks}
          names={
            clip.tricks.length === tricks.length
              ? clip.tricks.map((t) => formatTrickName(t.canonical_name))
              : undefined
          }
        />
      ) : (
        <SubscoreBars breakdown={analysis?.steeze_breakdown} />
      )}
      <p className={`${page.note} ${styles.footnote}`}>
        Scored automatically from the clip. Tricks tagged by @{clip.author.username}.
      </p>
    </section>
  );
}

export function ClipPage() {
  const { clipId = '' } = useParams();
  const clip = useClip(clipId);
  const { data: me } = useMe();
  const view = useRecordView();
  const commentsRef = useRef<HTMLElement>(null);

  if (clip.isPending) return <Loading label="Loading clip" />;
  if (clip.isError) {
    return (
      <div className={page.page}>
        <ErrorState error={clip.error} onRetry={() => void clip.refetch()} />
      </div>
    );
  }

  const c = clip.data;
  const own = c.author.id === me?.id;
  const tricks = c.analysis?.tricks ?? [];
  const when = c.published_at ?? c.created_at;
  const scored = c.status === 'published' || c.status === 'analyzed';

  return (
    <div className={`${page.page} ${styles.layout} ${scored ? '' : styles.statusFirst}`}>
      <div className={styles.left}>
        <ClipMedia clip={c} showScore={false} onPlay={() => view.mutate({ clip: c, own })} />
        {tricks.length > 1 && <TrickTimeline tricks={tricks} durationMs={c.duration_ms ?? 1} />}
        <div className={styles.who}>
          <Avatar name={c.author.display_name ?? c.author.username} src={c.author.avatar_url} size={2} />
          <Handle user={c.author} />
          <time className={styles.when} dateTime={when}>
            {formatTimeAgo(when)}
          </time>
        </div>
        {c.team && <TeamLine team={c.team} />}
        <div className={styles.tags}>
          {c.tricks.map((t) => (
            <span key={t.id} className={styles.tag}>
              {formatTrickName(t.canonical_name)}
            </span>
          ))}
        </div>
        {c.status === 'published' && (
          <ClipActions
            clip={c}
            onComments={() => {
              commentsRef.current?.scrollIntoView({ behavior: 'smooth' });
              commentsRef.current?.querySelector('input')?.focus();
            }}
          />
        )}
      </div>

      <div className={styles.right}>
        {scored ? <Breakdown clip={c} own={own} /> : <NotScored clip={c} />}
        {c.status === 'published' && (
          <section
            ref={commentsRef}
            className={`${page.card} ${styles.comments}`}
            aria-labelledby="comments-title"
          >
            <SectionHeading id="comments-title">Comments · {c.comment_count}</SectionHeading>
            <CommentThread clip={c} />
          </section>
        )}
        <p>
          <Link className="link" to={`/u/${c.author.username}`}>
            More from @{c.author.username}
          </Link>
        </p>
      </div>
    </div>
  );
}
