import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError, unwrap } from '../client.ts';
import { useApi } from '../context.tsx';
import type { ClipOut } from '../types.ts';
import { patchClip } from './cache.ts';
import { keys } from './keys.ts';

/** Clip statuses the worker hasn't finished with yet. */
export const IN_PROGRESS: ReadonlySet<ClipOut['status']> = new Set(['draft', 'queued', 'analyzing']);

/**
 * PUTs the file straight to S3 with the presigned URL from POST /clips
 * (never through the API). XHR rather than fetch, because only XHR reports
 * upload progress. The Content-Type must match what POST /clips was told.
 */
export function uploadToStorage(
  url: string,
  file: Blob,
  contentType: string,
  onProgress?: (fraction: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('PUT', url);
    xhr.setRequestHeader('Content-Type', contentType);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress?.(e.loaded / e.total);
    };
    xhr.onload = () =>
      xhr.status >= 200 && xhr.status < 300
        ? resolve()
        : reject(new ApiError(xhr.status, 'The upload failed. Check your connection and try again.'));
    xhr.onerror = () => reject(new ApiError(0, 'The upload failed. Check your connection and try again.'));
    xhr.send(file);
  });
}

/** One of your clips, polled every 2s while it's queued or being analyzed. */
export function useClipProgress(clipId: string) {
  const api = useApi();
  return useQuery({
    queryKey: keys.clip(clipId),
    queryFn: async () => unwrap(await api.GET('/clips/{clip_id}', { params: { path: { clip_id: clipId } } })),
    refetchInterval: (q) => (q.state.data && IN_PROGRESS.has(q.state.data.status) ? 2000 : false),
  });
}

/** POST /clips/{id}/complete: the upload landed, queue it for analysis. */
export function useCompleteClip() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (clipId: string) =>
      unwrap(await api.POST('/clips/{clip_id}/complete', { params: { path: { clip_id: clipId } } })),
    onSuccess: (clip) => {
      qc.setQueryData(keys.clip(clip.id), clip);
      void qc.invalidateQueries({ queryKey: keys.drafts });
    },
  });
}

/** POST /clips/{id}/tricks: the trick names, in clip order (position = order). */
export function useTagTricks() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ clipId, tricks }: { clipId: string; tricks: string[] }) =>
      unwrap(
        await api.POST('/clips/{clip_id}/tricks', {
          params: { path: { clip_id: clipId } },
          body: { tricks },
        }),
      ),
    onSuccess: (clip) => qc.setQueryData(keys.clip(clip.id), clip),
  });
}

export interface PublishChoices {
  /** One name per analyzed trick, in clip order; or the tags typed at upload. */
  tricks: string[];
  teamId: string | null;
  scoreIncluded: boolean;
}

/**
 * Everything "Publish" does, in the order the API requires while the clip
 * is `analyzed`: tag the tricks, tag the team (or clear it), set score
 * inclusion, then publish.
 */
export function usePublishClip(clipId: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ tricks, teamId, scoreIncluded }: PublishChoices) => {
      const path = { params: { path: { clip_id: clipId } } };
      unwrap(await api.POST('/clips/{clip_id}/tricks', { ...path, body: { tricks } }));
      unwrap(await api.PATCH('/clips/{clip_id}/team', { ...path, body: { team_id: teamId } }));
      unwrap(
        await api.PATCH('/clips/{clip_id}/score-inclusion', { ...path, body: { included: scoreIncluded } }),
      );
      return unwrap(await api.POST('/clips/{clip_id}/publish', path));
    },
    onSuccess: (clip) => {
      qc.setQueryData(keys.clip(clip.id), clip);
      patchClip(qc, clip.id, () => clip);
      void qc.invalidateQueries({ queryKey: keys.drafts });
      void qc.invalidateQueries({ queryKey: keys.userClips(clip.author.username) });
      void qc.invalidateQueries({ queryKey: keys.me });
    },
  });
}
