// Hooks for endpoints the frontend needs but the API doesn't have yet
// (docs/components/frontend.md, Endpoints the API doesn't have yet). Only
// the mock API answers them. Each is shaped like the existing routes, so
// when the backend adds one, `make web-types` brings it into schema.ts, the
// call moves to the typed client, and this file shrinks.
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { Client } from 'openapi-fetch';
import { unwrap } from '../client.ts';
import { useApi } from '../context.tsx';
import type { ClipCreate, ClipCreateOut, FeedPage, TeamOut } from '../types.ts';
import { keys } from './keys.ts';

// ---- the proposed routes, in the shape openapi-typescript generates ------

type Method = 'get' | 'put' | 'post' | 'delete' | 'options' | 'head' | 'patch' | 'trace';
type Json<T> = { headers: { [name: string]: unknown }; content: { 'application/json': T } };

// `[X] extends [never]` (not `X extends never`) so the check doesn't
// distribute over never; openapi-fetch wants absent parts as `?: never`.
type Op<Path, Query, Body, Res, Code extends number = 200> = {
  parameters: ([Query] extends [never] ? { query?: never } : { query?: Query }) & {
    header?: never;
    cookie?: never;
  } & ([Path] extends [never] ? { path?: never } : { path: Path });
  responses: { [K in Code]: Json<Res> };
} & ([Body] extends [never]
  ? { requestBody?: never }
  : { requestBody: { content: { 'application/json': Body } } });

type PathItem<M extends Partial<Record<Method, unknown>>> = {
  parameters: { query?: never; header?: never; path?: never; cookie?: never };
} & { [K in keyof M]: M[K] } & { [K in Exclude<Method, keyof M>]?: never };

/** POST /clips with the proposed `analyze` flag (defaults to true). */
export type ProposedClipCreate = ClipCreate & {
  /** false: skip the analyzer. The clip is ready to tag and publish as soon as the upload completes, with no score. */
  analyze?: boolean;
};

/** What a skater can say is wrong with an analysis (the report form's checklist). */
export type AnalysisProblem =
  | 'missed_trick'
  | 'extra_trick'
  | 'wrong_landed'
  | 'timing_off'
  | 'score_off'
  | 'should_have_scored'
  | 'wrong_reason';

/** PROPOSED body for POST /clips/{clip_id}/analysis-reports. */
export interface AnalysisReportCreate {
  problems: AnalysisProblem[];
  /** Which analyzed trick (index into analysis.tricks), or null for the clip as a whole. */
  trick_index: number | null;
  /** With score_off: which subscores feel wrong, and which way. */
  subscores: string[];
  score_direction: 'too_high' | 'too_low' | null;
  note: string | null;
  /** The skater lets TrickLens keep and watch this clip to improve the analyzer. */
  share_video: boolean;
  app_version: string;
}

/** PROPOSED body for POST /bug-reports. Works signed out too (a login bug). */
export interface BugReportCreate {
  description: string;
  /** The page the bug happened on, e.g. "/upload/…". */
  page: string | null;
  /** Sent automatically and shown to the user before sending. */
  context: {
    app_version: string;
    user_agent: string;
    viewport: string;
    theme: string;
    api_mode: string;
  };
}

export interface ReportCreated {
  id: string;
  created_at: string;
}

interface ProposedPaths {
  '/clips': PathItem<{ post: Op<never, never, ProposedClipCreate, ClipCreateOut, 201> }>;
  '/users/{username}/clips': PathItem<{
    get: Op<{ username: string }, { limit?: number; cursor?: string | null }, never, FeedPage>;
  }>;
  '/users/me/drafts': PathItem<{
    get: Op<never, { limit?: number; cursor?: string | null }, never, FeedPage>;
  }>;
  '/users/me/teams': PathItem<{ get: Op<never, never, never, TeamOut[]> }>;
  '/teams/{slug}/clips': PathItem<{
    get: Op<{ slug: string }, { limit?: number; cursor?: string | null }, never, FeedPage>;
  }>;
  '/clips/{clip_id}/analysis-reports': PathItem<{
    post: Op<{ clip_id: string }, never, AnalysisReportCreate, ReportCreated, 201>;
  }>;
  '/bug-reports': PathItem<{ post: Op<never, never, BugReportCreate, ReportCreated, 201> }>;
  '/teams/{slug}/join-requests/mine': PathItem<{
    get: Op<{ slug: string }, never, never, MyJoinRequest>;
  }>;
}

/** Whether you've asked to join a team (and when). */
export type MyJoinRequest = { pending: false } | { pending: true; created_at: string };

const useProposedApi = () => useApi() as unknown as Client<ProposedPaths>;

// ---- hooks -----------------------------------------------------------------

/**
 * PROPOSED `GET /users/{username}/clips`: a user's published clips, newest
 * first, keyset-paginated like the feed. Profiles need it for their clip grid.
 */
export function useUserClips(username: string) {
  const api = useProposedApi();
  return useInfiniteQuery({
    queryKey: keys.userClips(username),
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET('/users/{username}/clips', {
          params: { path: { username }, query: { limit: 12, cursor: pageParam } },
        }),
      ),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
}

/**
 * PROPOSED `GET /users/me/drafts`: your clips that aren't published yet
 * (uploading, being analyzed, ready to publish, couldn't be scored), newest
 * first. The upload page lists them so a clip you left mid-analysis isn't lost.
 */
export function useMyDrafts() {
  const api = useProposedApi();
  return useQuery({
    queryKey: keys.drafts,
    queryFn: async () => unwrap(await api.GET('/users/me/drafts', { params: { query: { limit: 20 } } })),
  });
}

/**
 * PROPOSED `GET /users/me/teams`: teams you're a member of, with your role
 * (`my_role`). Needed by the Teams tab and by "Tag to a team" before
 * publishing, which may only offer your own teams.
 */
export function useMyTeams() {
  const api = useProposedApi();
  return useQuery({
    queryKey: keys.myTeams,
    queryFn: async () => unwrap(await api.GET('/users/me/teams')),
  });
}

/** PROPOSED `GET /teams/{slug}/clips`: a team's published clips, newest first. */
export function useTeamClips(slug: string, enabled = true) {
  const api = useProposedApi();
  return useInfiniteQuery({
    queryKey: keys.teamClips(slug),
    enabled,
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET('/teams/{slug}/clips', {
          params: { path: { slug }, query: { limit: 12, cursor: pageParam } },
        }),
      ),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
}

/**
 * PROPOSED `GET /teams/{slug}/join-requests/mine`: whether you've asked to
 * join (`{ pending: false }` if not). `TeamOut` doesn't say, so without it a
 * team page can't show "Request sent" after a reload.
 */
export function useMyJoinRequest(slug: string, enabled = true) {
  const api = useProposedApi();
  return useQuery({
    queryKey: keys.myJoinRequest(slug),
    enabled,
    queryFn: async () =>
      unwrap(await api.GET('/teams/{slug}/join-requests/mine', { params: { path: { slug } } })),
  });
}

/**
 * Starts an upload: POST /clips with the PROPOSED `analyze` flag. The API
 * ignores the unknown field today, so `analyze: false` only takes effect
 * once the backend supports it.
 */
export function useCreateClip() {
  const api = useProposedApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: ProposedClipCreate) => {
      const res = await api.POST('/clips', { body });
      return unwrap(res);
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: keys.drafts }),
  });
}

/**
 * PROPOSED `POST /clips/{clip_id}/analysis-reports`: tell TrickLens the
 * analysis got something wrong. Your own clip, analyzed or couldn't be
 * scored, before publishing. The server snapshots the analysis itself
 * (model version, per-trick results, measurements), so the body carries
 * only what the skater says. It never changes the score or blocks
 * publishing (docs/components/frontend.md, Reports).
 */
export function useReportAnalysis(clipId: string) {
  const api = useProposedApi();
  return useMutation({
    mutationFn: async (body: AnalysisReportCreate) =>
      unwrap(
        await api.POST('/clips/{clip_id}/analysis-reports', { params: { path: { clip_id: clipId } }, body }),
      ),
  });
}

/** PROPOSED `POST /bug-reports`: a problem with the app itself, not the analyzer. */
export function useReportBug() {
  const api = useProposedApi();
  return useMutation({
    mutationFn: async (body: BugReportCreate) => unwrap(await api.POST('/bug-reports', { body })),
  });
}
