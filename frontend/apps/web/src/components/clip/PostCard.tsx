import { type ClipOut, formatTimeAgo, useRecordView } from '@tricklens/api';
import { Link } from 'react-router';
import { Avatar } from '../ui/Avatar.tsx';
import { ClipActions } from './ClipActions.tsx';
import { ClipMedia, trickNames } from './ClipMedia.tsx';
import styles from './clip.module.css';
import { Handle, TeamLine } from './People.tsx';
import { SubscoreStrip } from './Score.tsx';

/** One clip in the feed: who, the video with its score, the breakdown, and engagement. */
export function PostCard({
  clip,
  onComments,
  meId,
}: {
  clip: ClipOut;
  onComments: () => void;
  meId?: string;
}) {
  const view = useRecordView();
  const when = clip.published_at ?? clip.created_at;
  const name = clip.author.display_name ?? clip.author.username;

  return (
    <article className={styles.post} aria-label={`${trickNames(clip)} by @${clip.author.username}`}>
      <div className={styles.postPad}>
        <div className={styles.who}>
          <Link to={`/u/${clip.author.username}`} tabIndex={-1} aria-hidden="true">
            <Avatar name={name} src={clip.author.avatar_url} size={2.25} />
          </Link>
          <div className={styles.whoText}>
            <span>
              <Handle user={clip.author} />
              <Link to={`/clips/${clip.id}`} className={styles.when}>
                <time dateTime={when}>{formatTimeAgo(when)}</time>
                <span className="visually-hidden">, open clip</span>
              </Link>
            </span>
            {clip.team && <TeamLine team={clip.team} />}
          </div>
        </div>
      </div>
      <div className={styles.postMedia}>
        <ClipMedia clip={clip} onPlay={() => view.mutate({ clip, own: clip.author.id === meId })} />
      </div>
      <div className={styles.postPad}>
        <SubscoreStrip breakdown={clip.analysis?.steeze_breakdown} />
        <ClipActions clip={clip} onComments={onComments} />
        {clip.comment_count > 0 && (
          <button type="button" className={styles.commentsLink} onClick={onComments}>
            View all {clip.comment_count} comments
          </button>
        )}
      </div>
    </article>
  );
}
