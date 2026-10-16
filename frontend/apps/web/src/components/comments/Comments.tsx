import {
  type ClipOut,
  type CommentOut,
  formatTimeAgo,
  useAddComment,
  useComments,
  useDeleteComment,
  useMe,
} from '@tricklens/api';
import { type FormEvent, type RefObject, useEffect, useId, useRef, useState } from 'react';
import { Handle } from '../clip/People.tsx';
import { Icon } from '../icons/Icon.tsx';
import { Avatar } from '../ui/Avatar.tsx';
import { Button } from '../ui/Button.tsx';
import { Chip, ErrorState, Loading } from '../ui/controls.tsx';
import styles from './comments.module.css';

const MAX_LENGTH = 1000; // CommentCreate.body in the API
const REPLIES_SHOWN = 2;

interface ReplyTarget {
  /** Always the top-level comment: replies are one level deep. */
  parentId: string;
  username: string;
}

interface ItemProps {
  comment: CommentOut;
  clip: ClipOut;
  meId?: string;
  onReply: (target: ReplyTarget) => void;
  parentId?: string;
  /** Threads showing every reply; the rest fold after REPLIES_SHOWN. */
  expanded: Set<string>;
  onExpand: (commentId: string) => void;
}

function CommentItem({ comment, clip, meId, onReply, parentId, expanded, onExpand }: ItemProps) {
  const del = useDeleteComment(clip.id);
  const [confirming, setConfirming] = useState(false);
  const showAll = expanded.has(comment.id);
  const isOwner = comment.author.id === clip.author.id;
  const isMine = comment.author.id === meId;
  // The comment's author, or the clip's owner (moderation), same as the API.
  const canDelete = isMine || clip.author.id === meId;
  const replies = showAll ? comment.replies : comment.replies.slice(0, REPLIES_SHOWN);
  const hidden = comment.replies.length - replies.length;
  const name = comment.author.display_name ?? comment.author.username;

  return (
    <li className={styles.item}>
      <Avatar
        name={name}
        src={comment.author.avatar_url}
        size={parentId ? 1.75 : 2.125}
        highlight={isOwner}
      />
      <div className={styles.body}>
        <div className={styles.meta}>
          <Handle user={comment.author} />
          {isOwner && <Chip tone="yellow">Clip owner</Chip>}
          {isMine && !isOwner && <Chip>You</Chip>}
          <time className={styles.time} dateTime={comment.created_at}>
            {formatTimeAgo(comment.created_at)}
          </time>
        </div>
        <p className={styles.text}>{comment.body}</p>
        <div className={styles.actions}>
          {confirming ? (
            <>
              <span className={styles.confirm}>
                {comment.replies.length > 0
                  ? `Delete this and its ${comment.replies.length} ${comment.replies.length === 1 ? 'reply' : 'replies'}?`
                  : 'Delete this comment?'}
              </span>
              <button
                type="button"
                className={`${styles.action} ${styles.danger}`}
                onClick={() => del.mutate(comment)}
              >
                Delete
              </button>
              <button type="button" className={styles.action} onClick={() => setConfirming(false)}>
                Cancel
              </button>
            </>
          ) : (
            <>
              <button
                type="button"
                className={styles.action}
                onClick={() =>
                  onReply({ parentId: parentId ?? comment.id, username: comment.author.username })
                }
              >
                Reply
              </button>
              {canDelete && (
                <button type="button" className={styles.action} onClick={() => setConfirming(true)}>
                  Delete
                </button>
              )}
            </>
          )}
        </div>
        {comment.replies.length > 0 && (
          <ul className={styles.replies}>
            {replies.map((r) => (
              <CommentItem
                key={r.id}
                comment={r}
                clip={clip}
                meId={meId}
                onReply={onReply}
                parentId={comment.id}
                expanded={expanded}
                onExpand={onExpand}
              />
            ))}
            {hidden > 0 && (
              <li>
                <button type="button" className={styles.more} onClick={() => onExpand(comment.id)}>
                  Show {hidden} more {hidden === 1 ? 'reply' : 'replies'}
                </button>
              </li>
            )}
          </ul>
        )}
      </div>
    </li>
  );
}

function Composer({
  clip,
  replyTo,
  onCancelReply,
  onPosted,
  inputRef,
}: {
  clip: ClipOut;
  replyTo: ReplyTarget | null;
  onCancelReply: () => void;
  /** After a reply posts: unfold its thread so the reply is visible. */
  onPosted: (parentId: string | undefined) => void;
  inputRef: RefObject<HTMLInputElement | null>;
}) {
  const { data: me } = useMe();
  const add = useAddComment(clip.id);
  const [text, setText] = useState('');
  const id = useId();

  // Replying to someone starts the text with their handle, as people expect.
  useEffect(() => {
    if (replyTo) {
      setText((t) => (t.trim() ? t : `@${replyTo.username} `));
      inputRef.current?.focus();
    }
  }, [replyTo, inputRef]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const body = text.trim();
    if (!body) return;
    add.mutate(
      { body, parentId: replyTo?.parentId },
      {
        onSuccess: () => {
          setText('');
          onPosted(replyTo?.parentId);
          onCancelReply();
        },
      },
    );
  };

  return (
    <form className={styles.composer} onSubmit={submit}>
      {replyTo && (
        <div className={styles.replying}>
          <span>
            Replying to <b>@{replyTo.username}</b>
          </span>
          <button
            type="button"
            className={styles.iconButton}
            onClick={onCancelReply}
            aria-label="Cancel reply"
          >
            <Icon name="close" size={14} />
          </button>
        </div>
      )}
      <div className={styles.composerRow}>
        {me && <Avatar name={me.display_name ?? me.username} src={me.avatar_url} size={2} />}
        <label htmlFor={id} className="visually-hidden">
          {replyTo ? `Reply to @${replyTo.username}` : 'Add a comment'}
        </label>
        <input
          ref={inputRef}
          id={id}
          className={styles.input}
          placeholder={replyTo ? `Reply to @${replyTo.username}…` : 'Add a comment…'}
          value={text}
          maxLength={MAX_LENGTH}
          onChange={(e) => setText(e.target.value)}
        />
        <Button type="submit" variant="ghost" size="sm" disabled={!text.trim() || add.isPending}>
          Post
        </Button>
      </div>
      {add.isError && (
        <p className={styles.error} role="alert">
          Couldn't post that: {add.error.message}
        </p>
      )}
    </form>
  );
}

/** The comment list and composer for one clip. */
export function CommentThread({ clip }: { clip: ClipOut }) {
  const { data: me } = useMe();
  const comments = useComments(clip.id);
  const [replyTo, setReplyTo] = useState<ReplyTarget | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const expand = (id: string) => setExpanded((s) => new Set(s).add(id));
  const inputRef = useRef<HTMLInputElement>(null);
  const items = comments.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <div className={styles.thread}>
      <div className={styles.list}>
        {comments.isPending ? (
          <Loading label="Loading comments" />
        ) : comments.isError ? (
          <ErrorState error={comments.error} onRetry={() => void comments.refetch()} />
        ) : items.length === 0 ? (
          <p className={styles.empty}>No comments yet. Say something about the trick.</p>
        ) : (
          <ul className={styles.items}>
            {items.map((c) => (
              <CommentItem
                key={c.id}
                comment={c}
                clip={clip}
                meId={me?.id}
                onReply={setReplyTo}
                expanded={expanded}
                onExpand={expand}
              />
            ))}
          </ul>
        )}
        {comments.hasNextPage && (
          <button type="button" className={styles.more} onClick={() => void comments.fetchNextPage()}>
            Load older comments
          </button>
        )}
      </div>
      <Composer
        clip={clip}
        replyTo={replyTo}
        onCancelReply={() => setReplyTo(null)}
        onPosted={(parentId) => parentId && expand(parentId)}
        inputRef={inputRef}
      />
    </div>
  );
}

interface PanelProps {
  clip: ClipOut;
  onClose: () => void;
  /** "side": a panel beside the content (desktop). "sheet": a modal bottom sheet (phones). */
  mode: 'side' | 'sheet';
}

/** Comments for a clip, as a side panel on desktop or a bottom sheet on phones. */
export function CommentsPanel({ clip, onClose, mode }: PanelProps) {
  const titleId = useId();
  const sheetRef = useRef<HTMLDivElement>(null);

  // A sheet is modal: Escape closes it, focus moves in and returns on close.
  useEffect(() => {
    if (mode !== 'sheet') return;
    const previous = document.activeElement as HTMLElement | null;
    sheetRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = overflow;
      previous?.focus();
    };
  }, [mode, onClose]);

  const header = (
    <div className={styles.header}>
      <div>
        <h2 id={titleId} className={styles.title}>
          Comments <span className={styles.count}>{clip.comment_count}</span>
        </h2>
        <p className={styles.subtitle}>
          on @{clip.author.username}'s {clip.tricks[0]?.canonical_name.toLowerCase() ?? 'clip'}
        </p>
      </div>
      <button type="button" className={styles.iconButton} onClick={onClose} aria-label="Close comments">
        <Icon name="close" size={20} />
      </button>
    </div>
  );

  if (mode === 'side') {
    return (
      <aside className={styles.side} aria-labelledby={titleId}>
        {header}
        <CommentThread clip={clip} />
      </aside>
    );
  }

  return (
    <div className={styles.overlay}>
      <button
        type="button"
        className={styles.scrim}
        onClick={onClose}
        aria-label="Close comments"
        tabIndex={-1}
      />
      <div
        ref={sheetRef}
        className={styles.sheet}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        <div className={styles.grabber} aria-hidden="true" />
        {header}
        <CommentThread clip={clip} />
      </div>
    </div>
  );
}
