import { useMutation } from '@tanstack/react-query';
import { unwrap } from '../client.ts';
import { useApi } from '../context.tsx';
import type { AnalysisReportCreate, BugReportCreate } from '../types.ts';

/**
 * POST /clips/{clip_id}/analysis-reports: tell TrickLens the analysis got
 * something wrong. Your own clip, analyzed or couldn't be scored, before
 * publishing. The server snapshots the analysis itself (model version,
 * per-trick results, measurements), so the body carries only what the
 * skater says. It never changes the score or blocks publishing
 * (docs/components/frontend.md, Reports).
 */
export function useReportAnalysis(clipId: string) {
  const api = useApi();
  return useMutation({
    mutationFn: async (body: AnalysisReportCreate) =>
      unwrap(
        await api.POST('/clips/{clip_id}/analysis-reports', { params: { path: { clip_id: clipId } }, body }),
      ),
  });
}

/** POST /bug-reports: a problem with the app itself, not the analyzer. Works signed out. */
export function useReportBug() {
  const api = useApi();
  return useMutation({
    mutationFn: async (body: BugReportCreate) => unwrap(await api.POST('/bug-reports', { body })),
  });
}
