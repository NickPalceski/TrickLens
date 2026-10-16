import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { expectOk, unwrap } from '../client.ts';
import { useApi } from '../context.tsx';
import type { ClipOut } from '../types.ts';
import { patchClip } from './cache.ts';
import { keys } from './keys.ts';

const PAGE = 10;

/** The home feed (GET /feed), keyset-paginated. */
export function useFeed() {
  const api = useApi();
  return useInfiniteQuery({
    queryKey: keys.feed,
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam }) =>
      unwrap(await api.GET('/feed', { params: { query: { limit: PAGE, cursor: pageParam } } })),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
}

/** One clip (GET /clips/{id}): published, or your own at any status. */
export function useClip(clipId: string) {
  const api = useApi();
  return useQuery({
    queryKey: keys.clip(clipId),
    queryFn: async () => unwrap(await api.GET('/clips/{clip_id}', { params: { path: { clip_id: clipId } } })),
  });
}

/** Like or unlike, shown immediately everywhere the clip appears. */
export function useToggleLike() {
  const api = useApi();
  const qc = useQueryClient();
  const flip = (liked: boolean) => (c: ClipOut) => ({
    ...c,
    liked_by_me: !liked,
    like_count: c.like_count + (liked ? -1 : 1),
  });
  return useMutation({
    mutationFn: async (clip: ClipOut) => {
      const params = { params: { path: { clip_id: clip.id } } };
      expectOk(
        clip.liked_by_me
          ? await api.DELETE('/clips/{clip_id}/like', params)
          : await api.POST('/clips/{clip_id}/like', params),
      );
    },
    onMutate: (clip) => patchClip(qc, clip.id, flip(clip.liked_by_me)),
    // Undo: flip back from the optimistic state.
    onError: (_e, clip) => patchClip(qc, clip.id, flip(!clip.liked_by_me)),
  });
}

/** Counts a play (POST /clips/{id}/view). The API ignores the owner's own views. */
export function useRecordView() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ clip }: { clip: ClipOut; own: boolean }) =>
      expectOk(await api.POST('/clips/{clip_id}/view', { params: { path: { clip_id: clip.id } } })),
    onSuccess: (_d, { clip, own }) => {
      if (!own) patchClip(qc, clip.id, (c) => ({ ...c, view_count: c.view_count + 1 }));
    },
  });
}

/** Whether a clip's score counts toward its owner's (and team's) average. */
export function useSetScoreIncluded() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ clipId, included }: { clipId: string; included: boolean }) =>
      unwrap(
        await api.PATCH('/clips/{clip_id}/score-inclusion', {
          params: { path: { clip_id: clipId } },
          body: { included },
        }),
      ),
    onMutate: ({ clipId, included }) => patchClip(qc, clipId, (c) => ({ ...c, score_included: included })),
    onError: (_e, { clipId, included }) =>
      patchClip(qc, clipId, (c) => ({ ...c, score_included: !included })),
    onSettled: (_d, _e, { clipId }) => {
      void qc.invalidateQueries({ queryKey: keys.me });
      void qc.invalidateQueries({ queryKey: keys.clip(clipId), exact: true });
    },
  });
}
