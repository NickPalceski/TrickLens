// Mock API handlers (MSW). They intercept the real client's requests, so
// the app runs its real data-fetching code against fake responses. Paths
// match the FastAPI routes on any origin ("*/..."), so the same handlers
// serve the browser (any VITE_API_URL) and the Node tests. Behaviour
// mirrors the backend's rules (docs/components/api.md); where the API has a
// gap the frontend designs around, the handler is marked PROPOSED.
import { delay, HttpResponse, http } from 'msw';
import type { CommentOut, FeedPage, UserMe } from '../types.ts';
import { ME_USERNAME, meFrom, teamRankings } from './data.ts';
import {
  clipView,
  discoverClips,
  feedClips,
  findClip,
  findComment,
  getState,
  newCommentId,
  publicUser,
  published,
} from './db.ts';

/** Realistic latency in the browser so loading states show; none in tests. */
const isTest = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env
  ?.VITEST;
const wait = () => (isTest ? Promise.resolve() : delay(250));

const notFound = (what: string) => HttpResponse.json({ detail: `${what} not found` }, { status: 404 });
const conflict = (detail: string) => HttpResponse.json({ detail }, { status: 409 });

function page<T>(items: T[], url: URL): { items: T[]; next_cursor: string | null } {
  const limit = Number(url.searchParams.get('limit') ?? 20);
  const start = Number(url.searchParams.get('cursor') ?? 0);
  const next = start + limit < items.length ? String(start + limit) : null;
  return { items: items.slice(start, start + limit), next_cursor: next };
}

function offsetPage<T>(items: T[], url: URL): { items: T[]; next_offset: number | null } {
  const limit = Number(url.searchParams.get('limit') ?? 20);
  const offset = Number(url.searchParams.get('offset') ?? 0);
  return {
    items: items.slice(offset, offset + limit),
    next_offset: offset + limit < items.length ? offset + limit : null,
  };
}

const me = () => getState().people[ME_USERNAME];

export const handlers = [
  // ---- users ----------------------------------------------------------
  http.get('*/users/me', async () => {
    await wait();
    return HttpResponse.json(meFrom(getState()));
  }),

  // Registration after Cognito sign-up. The prototype has one sample
  // account, so this always answers with it rather than renaming it (every
  // sample clip and comment points at @juliavance).
  http.post('*/users', async () => {
    await wait();
    return HttpResponse.json(meFrom(getState()), { status: 201 });
  }),

  http.patch('*/users/me', async ({ request }) => {
    await wait();
    const body = (await request.json()) as Partial<Pick<UserMe, 'bio' | 'display_name'>>;
    Object.assign(me() ?? {}, body);
    return HttpResponse.json(meFrom(getState()));
  }),

  http.patch('*/users/me/profile', async ({ request }) => {
    await wait();
    const body = (await request.json()) as Record<string, unknown>;
    const p = me();
    if (!p) return notFound('user');
    p.profile = {
      ...(p.profile ?? {}),
      ...body,
      board_size: body.board_size == null ? null : String(body.board_size),
    };
    // Like the API, this route answers with the profile alone.
    return HttpResponse.json(p.profile);
  }),

  // PROPOSED: the API has no endpoint that lists a user's clips yet
  // (docs/components/frontend.md, Known gaps). Shaped like GET /feed.
  http.get('*/users/:username/clips', async ({ params, request }) => {
    await wait();
    const username = String(params.username);
    if (!publicUser(username)) return notFound('user');
    const clips = published()
      .filter((c) => c.author.username === username)
      .sort((a, b) => (b.published_at ?? '').localeCompare(a.published_at ?? ''))
      .map(clipView);
    return HttpResponse.json(page(clips, new URL(request.url)) satisfies FeedPage);
  }),

  http.get('*/users/:username', async ({ params }) => {
    await wait();
    const user = publicUser(String(params.username));
    return user ? HttpResponse.json(user) : notFound('user');
  }),

  http.post('*/users/:username/follow', async ({ params }) => {
    await wait();
    const p = getState().people[String(params.username)];
    if (!p) return notFound('user');
    if (p.username === ME_USERNAME)
      return HttpResponse.json({ detail: "can't follow yourself" }, { status: 422 });
    if (p.followed) return conflict('already following');
    p.followed = true;
    p.follower_count += 1;
    return new HttpResponse(null, { status: 204 });
  }),

  http.delete('*/users/:username/follow', async ({ params }) => {
    await wait();
    const p = getState().people[String(params.username)];
    if (!p) return notFound('user');
    if (p.followed) {
      p.followed = false;
      p.follower_count -= 1;
    }
    return new HttpResponse(null, { status: 204 });
  }),

  // ---- feed and discover ----------------------------------------------
  http.get('*/feed', async ({ request }) => {
    await wait();
    return HttpResponse.json(page(feedClips().map(clipView), new URL(request.url)) satisfies FeedPage);
  }),

  http.get('*/discover/clips', async ({ request }) => {
    await wait();
    const url = new URL(request.url);
    const sort = url.searchParams.get('sort') === 'engagement' ? 'engagement' : 'score';
    return HttpResponse.json(offsetPage(discoverClips(sort).map(clipView), url));
  }),

  http.get('*/discover/teams', async ({ request }) => {
    await wait();
    return HttpResponse.json(offsetPage(teamRankings, new URL(request.url)));
  }),

  // ---- clips ------------------------------------------------------------
  http.get('*/clips/:clipId', async ({ params }) => {
    await wait();
    const clip = findClip(String(params.clipId));
    // Same visibility rule as the API: published, or your own.
    if (!clip || (clip.status !== 'published' && clip.author.username !== ME_USERNAME))
      return notFound('clip');
    return HttpResponse.json(clipView(clip));
  }),

  http.post('*/clips/:clipId/like', async ({ params }) => {
    await wait();
    const clip = findClip(String(params.clipId));
    if (!clip) return notFound('clip');
    if (clip.status !== 'published') return conflict('clip must be published to like');
    if (clip.liked_by_me) return conflict('already liked');
    clip.liked_by_me = true;
    clip.like_count += 1;
    return new HttpResponse(null, { status: 204 });
  }),

  http.delete('*/clips/:clipId/like', async ({ params }) => {
    await wait();
    const clip = findClip(String(params.clipId));
    if (!clip) return notFound('clip');
    if (clip.liked_by_me) {
      clip.liked_by_me = false;
      clip.like_count -= 1;
    }
    return new HttpResponse(null, { status: 204 });
  }),

  http.post('*/clips/:clipId/view', async ({ params }) => {
    const clip = findClip(String(params.clipId));
    if (!clip) return notFound('clip');
    // The owner's own views aren't counted, same as the API.
    if (clip.author.username !== ME_USERNAME) clip.view_count += 1;
    return new HttpResponse(null, { status: 204 });
  }),

  http.patch('*/clips/:clipId/score-inclusion', async ({ params, request }) => {
    await wait();
    const clip = findClip(String(params.clipId));
    if (!clip || clip.author.username !== ME_USERNAME) return notFound('clip');
    clip.score_included = ((await request.json()) as { included: boolean }).included;
    return HttpResponse.json(clipView(clip));
  }),

  // ---- comments -----------------------------------------------------------
  http.get('*/clips/:clipId/comments', async ({ params, request }) => {
    await wait();
    const clipId = String(params.clipId);
    if (!findClip(clipId)) return notFound('clip');
    const top = getState()
      .comments.filter((c) => c.clip_id === clipId)
      .sort((a, b) => b.created_at.localeCompare(a.created_at));
    return HttpResponse.json(page(top, new URL(request.url)));
  }),

  http.post('*/clips/:clipId/comments', async ({ params, request }) => {
    await wait();
    const clip = findClip(String(params.clipId));
    if (!clip) return notFound('clip');
    if (clip.status !== 'published') return conflict('clip must be published to comment');
    const body = (await request.json()) as { body: string; parent_id?: string | null };
    const author = publicUser(ME_USERNAME);
    if (!author) return notFound('user');
    const created: CommentOut = {
      id: newCommentId(),
      clip_id: clip.id,
      author: {
        id: author.id,
        username: author.username,
        display_name: author.display_name,
        avatar_url: author.avatar_url,
      },
      body: body.body,
      parent_id: body.parent_id ?? null,
      replies: [],
      created_at: new Date().toISOString(),
    };
    if (body.parent_id) {
      const parent = findComment(body.parent_id);
      if (!parent) return notFound('comment');
      // One level only, same as the API: replying to a reply is a 422.
      if (parent.parent) return HttpResponse.json({ detail: 'replies are one level deep' }, { status: 422 });
      parent.comment.replies.push(created);
    } else {
      getState().comments.push(created);
    }
    return HttpResponse.json(created, { status: 201 });
  }),

  http.delete('*/clips/:clipId/comments/:commentId', async ({ params }) => {
    await wait();
    const clip = findClip(String(params.clipId));
    const found = findComment(String(params.commentId));
    if (!clip || !found) return notFound('comment');
    // The author or the clip's owner (moderation), same as the API.
    if (found.comment.author.username !== ME_USERNAME && clip.author.username !== ME_USERNAME) {
      return HttpResponse.json({ detail: 'not allowed' }, { status: 403 });
    }
    const s = getState();
    if (found.parent) found.parent.replies = found.parent.replies.filter((r) => r.id !== found.comment.id);
    else s.comments = s.comments.filter((c) => c.id !== found.comment.id);
    return new HttpResponse(null, { status: 204 });
  }),
];
