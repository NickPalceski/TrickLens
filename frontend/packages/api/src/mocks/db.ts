// In-memory state behind the mock API, so likes, follows, comments and
// profile edits stick for the session (and reset between tests).
import type { ClipOut, CommentOut, UserPublic } from '../types.ts';
import { ids, ME_USERNAME, type MockState, seed } from './data.ts';

let state: MockState = seed();

/** Back to the sample data. Tests call this between cases. */
export function resetMockDb() {
  state = seed();
}

export function getState(): MockState {
  return state;
}

export function countComments(clipId: string): number {
  return state.comments.filter((c) => c.clip_id === clipId).reduce((n, c) => n + 1 + c.replies.length, 0);
}

/** A clip as the API would return it to the signed-in user right now. */
export function clipView(c: ClipOut): ClipOut {
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

/** Newest first, from followed skaters and followed teams (GET /feed). */
export function feedClips(): ClipOut[] {
  return published()
    .filter((c) => {
      const author = state.people[c.author.username];
      return (
        (author?.followed ?? false) ||
        (c.team !== null && c.team !== undefined && state.followedTeams.has(c.team.id))
      );
    })
    .filter((c) => c.author.username !== ME_USERNAME)
    .sort((a, b) => (b.published_at ?? '').localeCompare(a.published_at ?? ''));
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
export function newCommentId(): string {
  nextId += 1;
  return `c4000000-0000-4000-8000-${String(nextId).padStart(12, '0')}`;
}

export function findComment(id: string): { comment: CommentOut; parent?: CommentOut } | undefined {
  for (const c of state.comments) {
    if (c.id === id) return { comment: c };
    const r = c.replies.find((x) => x.id === id);
    if (r) return { comment: r, parent: c };
  }
  return undefined;
}

export { ids };
