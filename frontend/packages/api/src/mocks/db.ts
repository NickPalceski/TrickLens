// In-memory state behind the mock API, so likes, follows, comments,
// uploads, teams and profile edits stick for the session (and reset
// between tests). Also simulates the worker: a completed upload moves
// queued → analyzing → analyzed / unanalyzable on a timer (with analysis
// off, the same stages with no analysis at the end).
import type { ClipOut, CommentOut, UserBrief, UserMe, UserPublic } from '../types.ts';
import {
  brief,
  ids,
  ME_EMAIL,
  ME_USERNAME,
  type MockOutcome,
  type MockPerson,
  scoreOf,
  seedClips,
  seedComments,
  seedPeople,
  simulatedAnalysis,
} from './data.ts';
import { type MockTeam, seedTeams, teamOut } from './teams.ts';

const isTest = Boolean(
  (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env?.VITEST,
);

/** How long the simulated worker takes per stage: visible in the browser, instant in tests. */
const STAGE_MS = isTest ? { queued: 0, analyzing: 0 } : { queued: 1500, analyzing: 4500 };

interface Upload {
  /** The PUT to the presigned URL arrived. */
  uploaded: boolean;
  completedAt?: number;
  outcome: MockOutcome;
}

export interface MockState {
  people: Record<string, MockPerson>;
  clips: ClipOut[];
  comments: CommentOut[];
  teams: MockTeam[];
  uploads: Map<string, Upload>;
  /** What the next completed upload's analysis turns out to be. */
  nextOutcome: MockOutcome;
  /** Reports received, newest last. Tests read these. */
  reports: { kind: 'analysis' | 'bug'; id: string; clip_id?: string; body: unknown; created_at: string }[];
}

function seed(): MockState {
  return {
    people: seedPeople(),
    clips: seedClips(),
    comments: seedComments(),
    teams: seedTeams(),
    uploads: new Map(),
    nextOutcome: 'single',
    reports: [],
  };
}

let state: MockState = seed();

/** Back to the sample data. Tests call this between cases. */
export function resetMockDb() {
  state = seed();
}

export function getState(): MockState {
  return state;
}

/**
 * Picks what the simulated analyzer decides for the next upload: one
 * landed trick, a three-trick line with a bail, or a clip that can't be
 * scored. The upload page offers this in mock mode only.
 */
export function setNextMockOutcome(outcome: MockOutcome) {
  state.nextOutcome = outcome;
}

export const userBrief = (username: string): UserBrief => {
  const p = state.people[username];
  return p
    ? { id: p.id, username: p.username, display_name: p.display_name, avatar_url: p.avatar_url }
    : brief(username);
};

/** The signed-in user as GET /users/me returns it. */
export function meNow(): UserMe {
  const { followed: _, ...p } = state.people[ME_USERNAME] as MockPerson;
  return { ...p, email: ME_EMAIL, followed_by_me: false };
}

export function countComments(clipId: string): number {
  return state.comments.filter((c) => c.clip_id === clipId).reduce((n, c) => n + 1 + c.replies.length, 0);
}

/** Moves a clip along the simulated worker's timeline, writing its analysis once done. */
function advance(c: ClipOut): void {
  const up = state.uploads.get(c.id);
  if (!up?.completedAt || (c.status !== 'queued' && c.status !== 'analyzing')) return;
  const elapsed = Date.now() - up.completedAt;
  if (elapsed < STAGE_MS.queued) return;
  if (elapsed < STAGE_MS.queued + STAGE_MS.analyzing) {
    c.status = 'analyzing';
    return;
  }
  if (!c.analyze) {
    // Posted without analysis: the worker only prepares the video.
    c.status = 'analyzed';
    return;
  }
  const analysis = simulatedAnalysis(up.outcome);
  c.analysis = analysis;
  c.steeze_score = scoreOf(analysis);
  c.status = analysis.failure_reason ? 'unanalyzable' : 'analyzed';
  c.thumb_url = null;
}

/** A clip as the API would return it to the signed-in user right now. */
export function clipView(c: ClipOut): ClipOut {
  advance(c);
  return { ...c, comment_count: countComments(c.id) };
}

export function findClip(id: string): ClipOut | undefined {
  return state.clips.find((c) => c.id === id);
}

export function publicUser(username: string): UserPublic | undefined {
  const p = state.people[username];
  if (!p) return undefined;
  const { followed, ...rest } = p;
  return { ...rest, followed_by_me: username !== ME_USERNAME && followed };
}

export const published = () => state.clips.filter((c) => c.status === 'published');
const newestFirst = (a: ClipOut, b: ClipOut) =>
  (b.published_at ?? b.created_at).localeCompare(a.published_at ?? a.created_at);

/** Newest first, from followed skaters and followed teams (GET /feed). */
export function feedClips(): ClipOut[] {
  const followedTeams = new Set(state.teams.filter((t) => t.followers.has(ME_USERNAME)).map((t) => t.id));
  return published()
    .filter(
      (c) => (state.people[c.author.username]?.followed ?? false) || (c.team && followedTeams.has(c.team.id)),
    )
    .filter((c) => c.author.username !== ME_USERNAME)
    .sort(newestFirst);
}

/** Your clips that aren't published yet (GET /users/me/drafts). */
export function draftClips(): ClipOut[] {
  return state.clips
    .filter((c) => c.author.username === ME_USERNAME && c.status !== 'published')
    .map(clipView)
    .sort(newestFirst);
}

const ENGAGEMENT = (c: ClipOut) => c.view_count + c.like_count * 5 + countComments(c.id) * 10;

/** This week's ranking (GET /discover/clips), same rules as app/rankings.py. */
export function discoverClips(sort: 'score' | 'engagement'): ClipOut[] {
  const week = Date.now() - 7 * 24 * 3_600_000;
  const recent = published().filter((c) => Date.parse(c.published_at ?? '') >= week);
  if (sort === 'engagement') return recent.sort((a, b) => ENGAGEMENT(b) - ENGAGEMENT(a));
  return recent
    .filter((c) => c.score_included && c.steeze_score)
    .sort((a, b) => Number(b.steeze_score) - Number(a.steeze_score));
}

let nextId = 1;
/** A fresh id for a record the mock creates (comments, clips, teams). */
export function newId(prefix: string): string {
  nextId += 1;
  return `${prefix}-0000-4000-8000-${String(nextId).padStart(12, '0')}`;
}

export function findComment(id: string): { comment: CommentOut; parent?: CommentOut } | undefined {
  for (const c of state.comments) {
    if (c.id === id) return { comment: c };
    const r = c.replies.find((x) => x.id === id);
    if (r) return { comment: r, parent: c };
  }
  return undefined;
}

// ---- teams --------------------------------------------------------------

export function findTeam(slug: string): MockTeam | undefined {
  return state.teams.find((t) => t.slug.toLowerCase() === slug.toLowerCase());
}

/** Founded, or forming and you're its owner or a founding invitee (404 otherwise, like the API). */
export function visibleTeam(slug: string): MockTeam | undefined {
  const t = findTeam(slug);
  if (!t) return undefined;
  if (t.founded_at) return t;
  if (t.owner === ME_USERNAME || t.requests.some((r) => r.username === ME_USERNAME)) return t;
  return undefined;
}

export const teamView = (t: MockTeam) => teamOut(t, ME_USERNAME, userBrief);
export const myRole = (t: MockTeam) => t.members.find((m) => m.username === ME_USERNAME)?.role ?? null;

export { ids };
