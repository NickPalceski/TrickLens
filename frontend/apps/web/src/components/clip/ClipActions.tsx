import { type ClipOut, formatCount, useToggleLike } from '@tricklens/api';
import { useState } from 'react';
import { Icon } from '../icons/Icon.tsx';
import styles from './clip.module.css';

/** Like, comments, views and share for one clip. */
export function ClipActions({ clip, onComments }: { clip: ClipOut; onComments?: () => void }) {
  const like = useToggleLike();
  const [copied, setCopied] = useState(false);

  const share = async () => {
    const url = `${window.location.origin}/clips/${clip.id}`;
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      window.prompt('Copy this link', url);
    }
  };

  return (
    <div className={styles.actions}>
      <button
        type="button"
        className={styles.action}
        aria-pressed={clip.liked_by_me}
        aria-label={`${clip.liked_by_me ? 'Unlike' : 'Like'}, ${clip.like_count} likes`}
        onClick={() => like.mutate(clip)}
        disabled={like.isPending}
      >
        <Icon name="heart" size={20} />
        <span aria-hidden="true">{formatCount(clip.like_count)}</span>
      </button>
      <button
        type="button"
        className={styles.action}
        aria-label={`Comments, ${clip.comment_count}`}
        onClick={onComments}
      >
        <Icon name="comment" size={20} />
        <span aria-hidden="true">{formatCount(clip.comment_count)}</span>
      </button>
      <span className={`${styles.action} ${styles.static}`} title="Views">
        <Icon name="eye" size={20} />
        <span>
          {formatCount(clip.view_count)}
          <span className="visually-hidden"> views</span>
        </span>
      </span>
      <button
        type="button"
        className={`${styles.action} ${styles.share}`}
        onClick={share}
        aria-label="Copy link to clip"
      >
        {copied ? <span role="status">Link copied</span> : <Icon name="share" size={20} />}
      </button>
    </div>
  );
}
