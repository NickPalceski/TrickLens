import { useFeed, useMe } from '@tricklens/api';
import { useState } from 'react';
import { Link } from 'react-router';
import { useIsDesktop } from '../../app/useMediaQuery.ts';
import { PostCard } from '../../components/clip/PostCard.tsx';
import { CommentsPanel } from '../../components/comments/Comments.tsx';
import { Button } from '../../components/ui/Button.tsx';
import { EmptyState, ErrorState, Loading } from '../../components/ui/controls.tsx';
import page from '../page.module.css';
import styles from './FeedPage.module.css';

/** New clips from skaters and teams you follow, with comments beside (desktop) or in a sheet (phone). */
export function FeedPage() {
  const feed = useFeed();
  const { data: me } = useMe();
  const isDesktop = useIsDesktop();
  const [commentsFor, setCommentsFor] = useState<string | null>(null);
  const clips = feed.data?.pages.flatMap((p) => p.items) ?? [];
  const open = clips.find((c) => c.id === commentsFor);

  return (
    <div
      className={`${page.page} ${page.flush} ${styles.layout} ${open && isDesktop ? styles.withPanel : ''}`}
    >
      <section className={styles.feed} aria-labelledby="feed-title">
        <div className={`${page.head} ${page.headPad}`}>
          <div>
            <h1 id="feed-title" className={page.title}>
              Feed
            </h1>
            <p className={page.lead}>New clips from skaters and teams you follow.</p>
          </div>
        </div>

        {feed.isPending ? (
          <Loading label="Loading your feed" />
        ) : feed.isError ? (
          <ErrorState error={feed.error} onRetry={() => void feed.refetch()} />
        ) : clips.length === 0 ? (
          <EmptyState title="Your feed is empty">
            <p>Follow skaters and teams to see their clips here.</p>
            <Link className="link" to="/discover">
              Find people on Discover
            </Link>
          </EmptyState>
        ) : (
          <>
            {clips.map((clip) => (
              <PostCard key={clip.id} clip={clip} meId={me?.id} onComments={() => setCommentsFor(clip.id)} />
            ))}
            {feed.hasNextPage && (
              <div className={page.loadMore}>
                <Button
                  variant="ghost"
                  onClick={() => void feed.fetchNextPage()}
                  disabled={feed.isFetchingNextPage}
                >
                  {feed.isFetchingNextPage ? 'Loading…' : 'Show older clips'}
                </Button>
              </div>
            )}
          </>
        )}
      </section>

      {open && (
        <div className={styles.panel}>
          <CommentsPanel
            clip={open}
            mode={isDesktop ? 'side' : 'sheet'}
            onClose={() => setCommentsFor(null)}
          />
        </div>
      )}
    </div>
  );
}
