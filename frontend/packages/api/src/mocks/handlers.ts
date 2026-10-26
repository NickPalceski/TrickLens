// Mock API handlers (MSW). They intercept the real client's requests, so
// the app runs its real data-fetching code against fake responses. Paths
// match the FastAPI routes on any origin ("*/..."), so the same handlers
// serve the browser (any VITE_API_URL) and the Node tests. Behaviour
// mirrors the backend's rules (docs/components/api.md); routes the API
// doesn't have yet are marked PROPOSED (docs/components/frontend.md,
// Endpoints the API doesn't have yet).
import { delay, HttpResponse, http } from 'msw';
import type { ClipOut, CommentOut, FeedPage, TeamCreate, TeamUpdate, UserMe } from '../types.ts';
import { ME_USERNAME, teamRankings } from './data.ts';
import {
  clipView,
  discoverClips,
  draftClips,
  feedClips,
  findClip,
  findComment,
  findTeam,
  getState,
  meNow,
  myRole,
  newId,
  publicUser,
  published,
  teamView,
  userBrief,
  visibleTeam,
} from './db.ts';
import { type MockTeam, TEAM_MAX_MEMBERS, TEAM_MIN_FOUNDING_INVITES } from './teams.ts';

/** Realistic latency in the browser so loading states show; none in tests. */
const isTest = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env
  ?.VITEST;
const wait = () => (isTest ? Promise.resolve() : delay(250));

/** Where the mock's presigned upload URLs point. */
export const MOCK_UPLOAD_ORIGIN = 'https://uploads.mock.tricklens.test';

const err = (status: number, detail: string) => HttpResponse.json({ detail }, { status });
const notFound = (what: string) => err(404, `${what} not found`);
const noContent = () => new HttpResponse(null, { status: 204 });

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
/** A clip you own, at any status (404 otherwise, like the API). */
const ownClip = (id: unknown) => {
  const c = findClip(String(id));
  return c && c.author.username === ME_USERNAME ? c : undefined;
};

const S3_CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'PUT',
  'Access-Control-Allow-Headers': 'Content-Type',
};
const CONTENT_TYPES = new Set(['video/mp4', 'video/quicktime', 'video/webm']);
const SLUG_RE = /^[a-z0-9_]{3,30}$/;

const memberOut = (t: MockTeam, username: string) => {
  const m = t.members.find((x) => x.username === username);
  return m ? { user: userBrief(m.username), role: m.role, joined_at: m.joined_at } : undefined;
};
const isAdmin = (t: MockTeam) => myRole(t) === 'owner' || myRole(t) === 'admin';

export const handlers = [
  // ---- users ----------------------------------------------------------
  http.get('*/users/me', async () => {
    await wait();
    return HttpResponse.json(meNow());
  }),

  // Registration after Cognito sign-up. The prototype has one sample
  // account, so this always answers with it rather than renaming it (every
  // sample clip and comment points at @juliavance).
  http.post('*/users', async () => {
    await wait();
    return HttpResponse.json(meNow(), { status: 201 });
  }),

  http.patch('*/users/me', async ({ request }) => {
    await wait();
    const body = (await request.json()) as Partial<Pick<UserMe, 'bio' | 'display_name'>>;
    Object.assign(me() ?? {}, body);
    return HttpResponse.json(meNow());
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

  // PROPOSED: your unpublished clips, newest first.
  http.get('*/users/me/drafts', async ({ request }) => {
    await wait();
    return HttpResponse.json(page(draftClips(), new URL(request.url)) satisfies FeedPage);
  }),

  // PROPOSED: teams you're a member of (forming ones you own included).
  http.get('*/users/me/teams', async () => {
    await wait();
    return HttpResponse.json(
      getState()
        .teams.filter((t) => myRole(t) !== null)
        .map(teamView),
    );
  }),

  // PROPOSED: a user's published clips, shaped like GET /feed.
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
    if (p.username === ME_USERNAME) return err(422, "can't follow yourself");
    if (p.followed) return err(409, 'already following');
    p.followed = true;
    p.follower_count += 1;
    return noContent();
  }),

  http.delete('*/users/:username/follow', async ({ params }) => {
    await wait();
    const p = getState().people[String(params.username)];
    if (!p) return notFound('user');
    if (p.followed) {
      p.followed = false;
      p.follower_count -= 1;
    }
    return noContent();
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

  // ---- upload and the clip lifecycle -------------------------------------
  http.post('*/clips', async ({ request }) => {
    await wait();
    const body = (await request.json()) as {
      content_type: string;
      duration_ms: number;
      source_fps: number;
      analyze?: boolean;
    };
    if (!CONTENT_TYPES.has(body.content_type)) return err(422, 'unsupported content type');
    if (!(body.duration_ms > 0 && body.duration_ms <= 30_000))
      return err(422, 'clips are capped at 30 seconds');
    const id = newId('a2000000');
    const now = new Date().toISOString();
    const clip: ClipOut = {
      id,
      status: 'draft',
      author: userBrief(ME_USERNAME),
      video_url: `mock://video/${id}`,
      thumb_url: null,
      duration_ms: body.duration_ms,
      source_fps: body.source_fps,
      steeze_score: null,
      published_at: null,
      tricks: [],
      analysis: null,
      like_count: 0,
      comment_count: 0,
      view_count: 0,
      liked_by_me: false,
      team: null,
      score_included: true,
      created_at: now,
    };
    const s = getState();
    s.clips.push(clip);
    s.uploads.set(id, { uploaded: false, analyze: body.analyze ?? true, outcome: s.nextOutcome });
    return HttpResponse.json({ clip, upload_url: `${MOCK_UPLOAD_ORIGIN}/raw/${id}` }, { status: 201 });
  }),

  // The presigned PUT straight to "S3", which (like the real bucket's CORS
  // rule) answers the browser's preflight and allows the PUT cross-origin.
  http.options(
    `${MOCK_UPLOAD_ORIGIN}/raw/:clipId`,
    () => new HttpResponse(null, { status: 204, headers: S3_CORS }),
  ),
  http.put(`${MOCK_UPLOAD_ORIGIN}/raw/:clipId`, async ({ params }) => {
    await wait();
    const up = getState().uploads.get(String(params.clipId));
    if (!up) return new HttpResponse(null, { status: 403, headers: S3_CORS });
    up.uploaded = true;
    return new HttpResponse(null, { status: 200, headers: S3_CORS });
  }),

  http.post('*/clips/:clipId/complete', async ({ params }) => {
    await wait();
    const clip = ownClip(params.clipId);
    if (!clip) return notFound('clip');
    if (clip.status !== 'draft') return err(409, `clip is already ${clip.status}`);
    const up = getState().uploads.get(clip.id);
    if (!up?.uploaded) return err(422, 'upload not found — PUT to the presigned URL first');
    if (!up.analyze) {
      // PROPOSED: with analysis off, the clip is ready to tag and publish
      // straight away, with no score.
      clip.status = 'analyzed';
      return HttpResponse.json(clipView(clip));
    }
    clip.status = 'queued';
    up.completedAt = Date.now();
    return HttpResponse.json(clipView(clip));
  }),

  http.post('*/clips/:clipId/tricks', async ({ params, request }) => {
    await wait();
    const clip = ownClip(params.clipId);
    if (!clip) return notFound('clip');
    clipView(clip);
    if (clip.status !== 'analyzed') return err(409, 'clip must be analyzed before tagging');
    const { tricks } = (await request.json()) as { tricks: string[] };
    const names = tricks.map((t) => t.trim());
    if (names.length < 1 || names.length > 5 || names.some((n) => n.length < 1 || n.length > 60)) {
      return err(422, 'tag 1 to 5 tricks, each 1-60 characters');
    }
    // Lowercased and in order, like the API (clip_tricks.position).
    clip.tricks = names.map((n, i) => ({
      id: `${clip.id.slice(0, -2)}g${i}`,
      canonical_name: n.toLowerCase(),
    }));
    return HttpResponse.json(clipView(clip));
  }),

  http.patch('*/clips/:clipId/team', async ({ params, request }) => {
    await wait();
    const clip = ownClip(params.clipId);
    if (!clip) return notFound('clip');
    if (clip.status !== 'analyzed')
      return err(409, 'clip must be analyzed, and not yet published, to tag a team');
    const { team_id } = (await request.json()) as { team_id: string | null };
    if (team_id === null) clip.team = null;
    else {
      const t = getState().teams.find((x) => x.id === team_id);
      if (!t || myRole(t) === null) return err(403, 'you must be a member of the team to tag a clip to it');
      clip.team = { id: t.id, name: t.name, slug: t.slug };
    }
    return HttpResponse.json(clipView(clip));
  }),

  http.post('*/clips/:clipId/publish', async ({ params }) => {
    await wait();
    const clip = ownClip(params.clipId);
    if (!clip) return notFound('clip');
    if (clip.status !== 'analyzed') return err(409, 'clip must be analyzed before publishing');
    if (clip.tricks.length === 0) return err(422, 'tag at least one trick before publishing');
    clip.status = 'published';
    clip.published_at = new Date().toISOString();
    return HttpResponse.json(clipView(clip));
  }),

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
    if (clip.status !== 'published') return err(409, 'clip must be published to like');
    if (clip.liked_by_me) return err(409, 'already liked');
    clip.liked_by_me = true;
    clip.like_count += 1;
    return HttpResponse.json(clipView(clip), { status: 201 });
  }),

  http.delete('*/clips/:clipId/like', async ({ params }) => {
    await wait();
    const clip = findClip(String(params.clipId));
    if (!clip) return notFound('clip');
    if (clip.liked_by_me) {
      clip.liked_by_me = false;
      clip.like_count -= 1;
    }
    return noContent();
  }),

  http.post('*/clips/:clipId/view', async ({ params }) => {
    const clip = findClip(String(params.clipId));
    if (!clip) return notFound('clip');
    if (clip.status !== 'published') return err(409, 'clip must be published to record a view');
    // The owner's own views aren't counted, same as the API.
    if (clip.author.username !== ME_USERNAME) clip.view_count += 1;
    return noContent();
  }),

  http.patch('*/clips/:clipId/score-inclusion', async ({ params, request }) => {
    await wait();
    const clip = ownClip(params.clipId);
    if (!clip) return notFound('clip');
    if (clip.status !== 'analyzed' && clip.status !== 'published') {
      return err(409, 'clip must be analyzed before its score can be toggled');
    }
    clip.score_included = ((await request.json()) as { included: boolean }).included;
    return HttpResponse.json(clipView(clip));
  }),

  // ---- reports (PROPOSED) -------------------------------------------------
  http.post('*/clips/:clipId/analysis-reports', async ({ params, request }) => {
    await wait();
    const clip = ownClip(params.clipId);
    if (!clip) return notFound('clip');
    clipView(clip);
    if (clip.status !== 'analyzed' && clip.status !== 'unanalyzable') {
      return err(409, 'only an analyzed clip, or one that could not be scored, can be reported');
    }
    if (!clip.analysis) return err(409, 'this clip was not analyzed');
    const body = (await request.json()) as { problems: string[]; note: string | null };
    if (body.problems.length === 0 && !body.note?.trim()) return err(422, 'say what went wrong');
    const report = {
      kind: 'analysis' as const,
      id: newId('d5000000'),
      clip_id: clip.id,
      body,
      created_at: new Date().toISOString(),
    };
    getState().reports.push(report);
    return HttpResponse.json({ id: report.id, created_at: report.created_at }, { status: 201 });
  }),

  http.post('*/bug-reports', async ({ request }) => {
    await wait();
    const body = (await request.json()) as { description: string };
    if (body.description.trim().length < 10) return err(422, 'describe the problem in a few words');
    const report = {
      kind: 'bug' as const,
      id: newId('d6000000'),
      body,
      created_at: new Date().toISOString(),
    };
    getState().reports.push(report);
    return HttpResponse.json({ id: report.id, created_at: report.created_at }, { status: 201 });
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
    if (clip.status !== 'published') return err(409, 'clip must be published to comment');
    const body = (await request.json()) as { body: string; parent_id?: string | null };
    const created: CommentOut = {
      id: newId('c4000000'),
      clip_id: clip.id,
      author: userBrief(ME_USERNAME),
      body: body.body,
      parent_id: body.parent_id ?? null,
      replies: [],
      created_at: new Date().toISOString(),
    };
    if (body.parent_id) {
      const parent = findComment(body.parent_id);
      if (!parent) return notFound('comment');
      // One level only, same as the API: replying to a reply is a 422.
      if (parent.parent) return err(422, 'replies are one level deep');
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
      return err(403, 'not allowed');
    }
    const s = getState();
    if (found.parent) found.parent.replies = found.parent.replies.filter((r) => r.id !== found.comment.id);
    else s.comments = s.comments.filter((c) => c.id !== found.comment.id);
    return noContent();
  }),

  // ---- teams --------------------------------------------------------------
  http.get('*/teams/invites/mine', async () => {
    await wait();
    const invites = getState().teams.flatMap((t) =>
      t.requests
        .filter((r) => r.username === ME_USERNAME && r.kind === 'invite')
        .map((r) => ({ team: { id: t.id, name: t.name, slug: t.slug }, created_at: r.created_at })),
    );
    return HttpResponse.json(invites);
  }),

  http.post('*/teams', async ({ request }) => {
    await wait();
    const body = (await request.json()) as TeamCreate;
    const s = getState();
    if (!SLUG_RE.test(body.slug))
      return err(422, 'slug must be 3-30 lowercase letters, digits, or underscores');
    const invitees = body.invitee_usernames.map((u) => u.toLowerCase());
    if (invitees.length < TEAM_MIN_FOUNDING_INVITES) {
      return err(422, `invite at least ${TEAM_MIN_FOUNDING_INVITES} founding members`);
    }
    if (new Set(invitees).size !== invitees.length) return err(422, 'invitee usernames must be unique');
    if (invitees.includes(ME_USERNAME)) return err(422, "you can't invite yourself");
    if (invitees.some((u) => !s.people[u])) return notFound('user');
    if (findTeam(body.slug)) return err(409, 'slug already taken');
    const now = new Date().toISOString();
    const t: MockTeam = {
      id: newId('b3000000'),
      name: body.name,
      slug: body.slug,
      description: body.description ?? null,
      level: body.level,
      join_policy: body.join_policy ?? 'open',
      owner: ME_USERNAME,
      created_at: now,
      founded_at: null,
      members: [{ username: ME_USERNAME, role: 'owner', joined_at: now }],
      requests: invitees.map((username) => ({ username, kind: 'invite', founding: true, created_at: now })),
      followers: new Set(),
      follower_base: 0,
      average_score: null,
    };
    s.teams.push(t);
    return HttpResponse.json(teamView(t), { status: 201 });
  }),

  // PROPOSED: a team's published clips.
  http.get('*/teams/:slug/clips', async ({ params, request }) => {
    await wait();
    const t = visibleTeam(String(params.slug));
    if (!t) return notFound('team');
    const clips = published()
      .filter((c) => c.team?.id === t.id)
      .sort((a, b) => (b.published_at ?? '').localeCompare(a.published_at ?? ''))
      .map(clipView);
    return HttpResponse.json(page(clips, new URL(request.url)) satisfies FeedPage);
  }),

  // PROPOSED: whether you've asked to join.
  http.get('*/teams/:slug/join-requests/mine', async ({ params }) => {
    await wait();
    const t = visibleTeam(String(params.slug));
    if (!t) return notFound('team');
    const r = t.requests.find((x) => x.username === ME_USERNAME && x.kind === 'request');
    return HttpResponse.json(r ? { pending: true, created_at: r.created_at } : { pending: false });
  }),

  http.get('*/teams/:slug', async ({ params }) => {
    await wait();
    const t = visibleTeam(String(params.slug));
    return t ? HttpResponse.json(teamView(t)) : notFound('team');
  }),

  http.patch('*/teams/:slug', async ({ params, request }) => {
    await wait();
    const t = visibleTeam(String(params.slug));
    if (!t) return notFound('team');
    if (t.owner !== ME_USERNAME) return err(403, 'only the owner can update team settings');
    const body = (await request.json()) as TeamUpdate;
    if (body.name != null) t.name = body.name;
    if (body.description !== undefined) t.description = body.description;
    if (body.level != null) t.level = body.level;
    if (body.join_policy != null) t.join_policy = body.join_policy;
    return HttpResponse.json(teamView(t));
  }),

  http.delete('*/teams/:slug', async ({ params }) => {
    await wait();
    const t = visibleTeam(String(params.slug));
    if (!t) return notFound('team');
    if (t.owner !== ME_USERNAME) return err(403, 'only the owner can delete this team');
    const s = getState();
    s.teams = s.teams.filter((x) => x.id !== t.id);
    // SET NULL on clips.team_id, like the database.
    for (const c of s.clips) if (c.team?.id === t.id) c.team = null;
    return noContent();
  }),

  http.get('*/teams/:slug/members', async ({ params }) => {
    await wait();
    const t = visibleTeam(String(params.slug));
    if (!t) return notFound('team');
    const order = { owner: 0, admin: 1, member: 2 } as const;
    const members = [...t.members]
      .sort((a, b) => order[a.role] - order[b.role])
      .map((m) => memberOut(t, m.username));
    return HttpResponse.json(members);
  }),

  http.patch('*/teams/:slug/members/:username', async ({ params, request }) => {
    await wait();
    const t = visibleTeam(String(params.slug));
    if (!t) return notFound('team');
    if (t.owner !== ME_USERNAME) return err(403, 'only the owner can change member roles');
    const m = t.members.find((x) => x.username === String(params.username));
    if (!m || m.role === 'owner') return err(404, 'not a member of this team');
    const { role } = (await request.json()) as { role: 'admin' | 'member' };
    m.role = role;
    return HttpResponse.json(memberOut(t, m.username));
  }),

  http.delete('*/teams/:slug/members/:username', async ({ params }) => {
    await wait();
    const t = visibleTeam(String(params.slug));
    if (!t) return notFound('team');
    const target = t.members.find((x) => x.username === String(params.username));
    if (!target) return err(404, 'not a member of this team');
    if (target.role === 'owner') return err(409, "the owner can't be removed — delete the team instead");
    const mine = myRole(t);
    const allowed =
      target.username === ME_USERNAME || mine === 'owner' || (mine === 'admin' && target.role === 'member');
    if (!allowed) return err(403, 'not allowed to remove this member');
    t.members = t.members.filter((x) => x.username !== target.username);
    return noContent();
  }),

  http.post('*/teams/:slug/join', async ({ params }) => {
    await wait();
    const t = visibleTeam(String(params.slug));
    if (!t) return notFound('team');
    if (!t.founded_at) return err(409, "team hasn't finished forming yet");
    if (t.join_policy === 'invite_only') return err(403, 'this team is invite-only');
    if (myRole(t)) return err(409, 'already a member');
    const now = new Date().toISOString();
    if (t.join_policy === 'request') {
      if (t.requests.some((r) => r.username === ME_USERNAME)) return err(409, 'already pending');
      t.requests.push({ username: ME_USERNAME, kind: 'request', founding: false, created_at: now });
      return HttpResponse.json(teamView(t), { status: 201 });
    }
    if (t.members.length >= TEAM_MAX_MEMBERS)
      return err(409, `team is at its ${TEAM_MAX_MEMBERS}-member cap`);
    t.members.push({ username: ME_USERNAME, role: 'member', joined_at: now });
    return HttpResponse.json(teamView(t), { status: 201 });
  }),

  http.delete('*/teams/:slug/join', async ({ params }) => {
    await wait();
    const t = visibleTeam(String(params.slug));
    if (!t) return notFound('team');
    t.requests = t.requests.filter((r) => !(r.username === ME_USERNAME && r.kind === 'request'));
    return HttpResponse.json(teamView(t));
  }),

  http.get('*/teams/:slug/join-requests', async ({ params }) => {
    await wait();
    const t = visibleTeam(String(params.slug));
    if (!t) return notFound('team');
    if (!isAdmin(t)) return err(403, 'owner/admin only');
    return HttpResponse.json(
      t.requests
        .filter((r) => r.kind === 'request')
        .map((r) => ({ user: userBrief(r.username), created_at: r.created_at })),
    );
  }),

  http.post('*/teams/:slug/join-requests/:username/accept', async ({ params }) => {
    await wait();
    const t = visibleTeam(String(params.slug));
    if (!t) return notFound('team');
    if (!isAdmin(t)) return err(403, 'owner/admin only');
    const username = String(params.username);
    const req = t.requests.find((r) => r.username === username && r.kind === 'request');
    if (!req) return err(404, 'no pending request from this user');
    if (t.members.length >= TEAM_MAX_MEMBERS)
      return err(409, `team is at its ${TEAM_MAX_MEMBERS}-member cap`);
    t.requests = t.requests.filter((r) => r !== req);
    t.members.push({ username, role: 'member', joined_at: new Date().toISOString() });
    return HttpResponse.json(memberOut(t, username));
  }),

  http.post('*/teams/:slug/join-requests/:username/reject', async ({ params }) => {
    await wait();
    const t = visibleTeam(String(params.slug));
    if (!t) return notFound('team');
    if (!isAdmin(t)) return err(403, 'owner/admin only');
    const username = String(params.username);
    if (!t.requests.some((r) => r.username === username && r.kind === 'request')) {
      return err(404, 'no pending request from this user');
    }
    t.requests = t.requests.filter((r) => !(r.username === username && r.kind === 'request'));
    return noContent();
  }),

  http.post('*/teams/:slug/invites', async ({ params, request }) => {
    await wait();
    const t = visibleTeam(String(params.slug));
    if (!t) return notFound('team');
    if (!isAdmin(t)) return err(403, 'owner/admin only');
    if (!t.founded_at) return err(409, "team hasn't finished forming yet");
    const username = ((await request.json()) as { username: string }).username.toLowerCase();
    if (!getState().people[username]) return notFound('user');
    if (t.members.some((m) => m.username === username)) return err(409, 'already a member');
    if (t.requests.some((r) => r.username === username)) return err(409, 'already invited or requested');
    t.requests.push({ username, kind: 'invite', founding: false, created_at: new Date().toISOString() });
    return noContent();
  }),

  http.post('*/teams/:slug/invites/mine/accept', async ({ params }) => {
    await wait();
    const t = visibleTeam(String(params.slug));
    if (!t) return notFound('team');
    const inv = t.requests.find((r) => r.username === ME_USERNAME && r.kind === 'invite');
    if (!inv) return err(404, 'no pending invite for you on this team');
    if (t.founded_at && t.members.length >= TEAM_MAX_MEMBERS) {
      return err(409, `team is at its ${TEAM_MAX_MEMBERS}-member cap`);
    }
    t.requests = t.requests.filter((r) => r !== inv);
    t.members.push({ username: ME_USERNAME, role: 'member', joined_at: new Date().toISOString() });
    // The last founding acceptance founds the team.
    if (!t.founded_at && !t.requests.some((r) => r.founding)) t.founded_at = new Date().toISOString();
    return HttpResponse.json(teamView(t));
  }),

  http.post('*/teams/:slug/invites/mine/reject', async ({ params }) => {
    await wait();
    const t = visibleTeam(String(params.slug));
    if (!t) return notFound('team');
    const inv = t.requests.find((r) => r.username === ME_USERNAME && r.kind === 'invite');
    if (!inv) return err(404, 'no pending invite for you on this team');
    const s = getState();
    // Rejecting a founding invite cancels the whole team, like the API.
    if (!t.founded_at) s.teams = s.teams.filter((x) => x.id !== t.id);
    else t.requests = t.requests.filter((r) => r !== inv);
    return noContent();
  }),

  http.post('*/teams/:slug/follow', async ({ params }) => {
    await wait();
    const t = visibleTeam(String(params.slug));
    if (!t) return notFound('team');
    if (!t.founded_at) return err(409, "team hasn't finished forming yet");
    if (t.followers.has(ME_USERNAME)) return err(409, 'already following');
    t.followers.add(ME_USERNAME);
    return HttpResponse.json(teamView(t), { status: 201 });
  }),

  http.delete('*/teams/:slug/follow', async ({ params }) => {
    await wait();
    const t = visibleTeam(String(params.slug));
    if (!t) return notFound('team');
    t.followers.delete(ME_USERNAME);
    return HttpResponse.json(teamView(t));
  }),
];
