import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { expectOk, unwrap } from '../client.ts';
import { useApi } from '../context.tsx';
import type { CommentOut } from '../types.ts';
import { patchClip } from './cache.ts';
import { keys } from './keys.ts';

/** A clip's comments (GET /clips/{id}/comments): newest first, replies inline, one level deep. */
export function useComments(clipId: string, enabled = true) {
  const api = useApi();
  return useInfiniteQuery({
    queryKey: keys.comments(clipId),
    enabled,
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET('/clips/{clip_id}/comments', {
          params: { path: { clip_id: clipId }, query: { limit: 20, cursor: pageParam } },
        }),
      ),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
}

/** Posts a comment, or a reply when `parentId` is a top-level comment's id. */
export function useAddComment(clipId: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ body, parentId }: { body: string; parentId?: string | null }) =>
      unwrap(
        await api.POST('/clips/{clip_id}/comments', {
          params: { path: { clip_id: clipId } },
          body: { body, parent_id: parentId ?? null },
        }),
      ),
    onSuccess: () => {
      patchClip(qc, clipId, (c) => ({ ...c, comment_count: c.comment_count + 1 }));
      void qc.invalidateQueries({ queryKey: keys.comments(clipId) });
    },
  });
}

/** Deletes a comment (its author or the clip's owner). Its replies go with it. */
export function useDeleteComment(clipId: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (comment: CommentOut) =>
      expectOk(
        await api.DELETE('/clips/{clip_id}/comments/{comment_id}', {
          params: { path: { clip_id: clipId, comment_id: comment.id } },
        }),
      ),
    onSuccess: (_d, comment) => {
      const removed = 1 + comment.replies.length;
      patchClip(qc, clipId, (c) => ({ ...c, comment_count: Math.max(0, c.comment_count - removed) }));
      void qc.invalidateQueries({ queryKey: keys.comments(clipId) });
    },
  });
}
