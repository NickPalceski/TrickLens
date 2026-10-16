import type { QueryClient } from '@tanstack/react-query';
import type { ClipOut } from '../types.ts';

type ClipFn = (clip: ClipOut) => ClipOut;

function isClip(x: unknown, id: string): x is ClipOut {
  return typeof x === 'object' && x !== null && (x as ClipOut).id === id && 'like_count' in x;
}

/** Applies fn to the clip wherever it sits: a ClipOut, a page of items, or infinite pages. */
function mapClip(data: unknown, id: string, fn: ClipFn): unknown {
  if (typeof data !== 'object' || data === null) return data;
  if (isClip(data, id)) return fn(data);
  if ('pages' in data && Array.isArray(data.pages)) {
    return { ...data, pages: data.pages.map((p: unknown) => mapClip(p, id, fn)) };
  }
  if ('items' in data && Array.isArray(data.items)) {
    return { ...data, items: data.items.map((c: unknown) => (isClip(c, id) ? fn(c) : c)) };
  }
  return data;
}

/**
 * Updates one clip in every cached query that holds it (feed, Discover,
 * clip detail, profile grids), so a like or a new comment shows everywhere
 * at once without refetching.
 */
export function patchClip(queryClient: QueryClient, id: string, fn: ClipFn) {
  queryClient.setQueriesData(
    {
      predicate: (q) => {
        const [root, , leaf] = q.queryKey;
        return (
          root === 'feed' ||
          root === 'discover' ||
          (root === 'clips' && leaf === undefined) ||
          leaf === 'clips'
        );
      },
    },
    (old: unknown) => mapClip(old, id, fn),
  );
}
