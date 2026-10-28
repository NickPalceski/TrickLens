// Sample data for the mock API: the same people, teams and numbers as the
// design canvas. Typed against the generated schema, so it can't drift from
// what the real API returns. `seed()` builds a fresh copy; db.ts mutates it.
import type { AnalysisOut, ClipOut, CommentOut, TeamBrief, UserBrief, UserPublic } from '../types.ts';

const HOUR = 3_600_000;
const ago = (hours: number) => new Date(Date.now() - hours * HOUR).toISOString();
const created = '2026-08-02T17:20:00Z';

// Stable ids, so links and tests can name them.
export const ids = {
  julia: '0b6f3c1e-5d2a-4c8e-9a71-2f4e8d6b1a01',
  marco: '1c7a4d2f-6e3b-4d9f-8b82-3a5f9e7c2b02',
  leo: '2d8b5e3a-7f4c-4eaf-9c93-4b6a0f8d3c03',
  destiny: '3e9c6f4b-8a5d-4fb0-ad04-5c7b1a9e4d04',
  priya: '4fad7a5c-9b6e-40c1-be15-6d8c2bae5e05',
  sam: '50be8b6d-ac7f-41d2-8f26-7e9d3cbf6f06',
  casey: '61cf9c7e-bd80-42e3-9037-8fae4dc07a07',
  clips: {
    marcoKickflip: 'a1000000-0000-4000-8000-000000000001',
    leoBs180: 'a1000000-0000-4000-8000-000000000002',
    destinyHeelflip: 'a1000000-0000-4000-8000-000000000003',
    juliaLine: 'a1000000-0000-4000-8000-000000000004',
    juliaKickflip: 'a1000000-0000-4000-8000-000000000005',
    juliaBoardslide: 'a1000000-0000-4000-8000-000000000006',
    destinyKickflip: 'a1000000-0000-4000-8000-000000000007',
    destinyVarial: 'a1000000-0000-4000-8000-000000000008',
    destinyOllie: 'a1000000-0000-4000-8000-000000000009',
    caseyHardflip: 'a1000000-0000-4000-8000-00000000000a',
    priyaTreflip: 'a1000000-0000-4000-8000-00000000000b',
    samVarial: 'a1000000-0000-4000-8000-00000000000c',
    juliaHeelflipFailed: 'a1000000-0000-4000-8000-00000000000d',
  },
} as const;

type Breakdown = Record<string, number | null>;
const SUBS = ['pop', 'landing_stability', 'roll_away', 'stomp', 'compactness', 'catch'] as const;
const breakdown = (values: (number | null)[]): Breakdown =>
  Object.fromEntries(SUBS.map((k, i) => [k, values[i] ?? null]));

function average(values: (number | null)[]): string {
  const xs = values.filter((v): v is number => v !== null);
  return (xs.reduce((a, b) => a + b, 0) / xs.length).toFixed(2);
}

function singleTrick(values: (number | null)[], takeoff = 1250, confidence = '0.91'): AnalysisOut {
  return {
    model_version: 'steeze-v0-uncalibrated',
    confidence,
    steeze_breakdown: breakdown(values),
    failure_reason: null,
    tricks: [
      {
        outcome: 'landed',
        takeoff_ms: takeoff,
        touchdown_ms: takeoff + 400,
        confidence: 0.92,
        subscores: breakdown(values),
      },
    ],
    created_at: created,
  };
}

const people: Record<string, Omit<UserPublic, 'followed_by_me'> & { followed: boolean }> = {
  juliavance: {
    id: ids.julia,
    username: 'juliavance',
    display_name: 'Julia Vance',
    bio: 'Street skater, regular stance. Filming everything, judging nothing but the landing.',
    avatar_url: null,
    profile: {
      stance: 'regular',
      style: 'street',
      board: 'Baker B1',
      board_size: '8.0',
      wheels: 'Spitfire F4',
      wheel_size: 54,
      trucks: 'Independent Stage 11',
      bearings: 'Bones Reds',
    },
    follower_count: 186,
    following_count: 204,
    average_score: '79.30',
    created_at: created,
    followed: false,
  },
  marcosandoval: {
    id: ids.marco,
    username: 'marcosandoval',
    display_name: 'Marco Sandoval',
    bio: 'West lot regular. Kickflips until the lights go off.',
    avatar_url: null,
    profile: {
      stance: 'regular',
      style: 'street',
      board: 'Girl',
      board_size: '8.25',
      wheels: 'Spitfire',
      wheel_size: 53,
      trucks: 'Venture',
      bearings: 'Bones',
    },
    follower_count: 421,
    following_count: 188,
    average_score: '81.40',
    created_at: created,
    followed: true,
  },
  leotran: {
    id: ids.leo,
    username: 'leotran',
    display_name: 'Leo Tran',
    bio: 'Rolling 180s and bad decisions.',
    avatar_url: null,
    profile: { stance: 'goofy', style: 'mix' },
    follower_count: 97,
    following_count: 130,
    average_score: '71.20',
    created_at: created,
    followed: true,
  },
  destinyfoster: {
    id: ids.destiny,
    username: 'destinyfoster',
    display_name: 'Destiny Foster',
    bio: 'Goofy, mostly street. Flip tricks on flat until security shows up.',
    avatar_url: null,
    profile: {
      stance: 'goofy',
      style: 'street',
      board: 'Real',
      board_size: '8.25',
      wheels: 'OJ',
      wheel_size: 53,
      trucks: 'Thunder 147',
      bearings: 'Bones Swiss',
    },
    follower_count: 312,
    following_count: 140,
    average_score: '77.70',
    created_at: created,
    followed: false,
  },
  priyanair: {
    id: ids.priya,
    username: 'priyanair',
    display_name: 'Priya Nair',
    bio: 'Tre flips on flat ground only.',
    avatar_url: null,
    profile: { stance: 'regular', style: 'street' },
    follower_count: 150,
    following_count: 75,
    average_score: '81.00',
    created_at: created,
    followed: false,
  },
  samgreer: {
    id: ids.sam,
    username: 'samgreer',
    display_name: 'Sam Greer',
    bio: null,
    avatar_url: null,
    profile: null,
    follower_count: 44,
    following_count: 60,
    average_score: '80.00',
    created_at: created,
    followed: false,
  },
  caseyoshiro: {
    id: ids.casey,
    username: 'caseyoshiro',
    display_name: 'Casey Oshiro',
    bio: 'Hardflips are a personality.',
    avatar_url: null,
    profile: { stance: 'regular', style: 'street' },
    follower_count: 610,
    following_count: 210,
    average_score: '83.00',
    created_at: created,
    followed: false,
  },
};

export const teams = {
  downtown: {
    id: 'b2000000-0000-4000-8000-000000000001',
    name: 'Downtown Skaters',
    slug: 'downtown_skaters',
  },
  nightShift: { id: 'b2000000-0000-4000-8000-000000000002', name: 'Night Shift', slug: 'night_shift' },
  curbCult: { id: 'b2000000-0000-4000-8000-000000000003', name: 'Curb Cult', slug: 'curb_cult' },
  westside: {
    id: 'b2000000-0000-4000-8000-000000000004',
    name: 'Westside Ledge Club',
    slug: 'westside_ledge_club',
  },
  bowlRats: { id: 'b2000000-0000-4000-8000-000000000005', name: 'Bowl Rats', slug: 'bowl_rats' },
} satisfies Record<string, TeamBrief>;

const brief = (username: string): UserBrief => {
  const p = people[username];
  if (!p) throw new Error(`no sample user ${username}`);
  return { id: p.id, username: p.username, display_name: p.display_name, avatar_url: p.avatar_url };
};

interface ClipSeed {
  id: string;
  author: string;
  trick: string | string[];
  hoursAgo: number;
  values?: (number | null)[];
  analysis?: AnalysisOut;
  likes: number;
  views: number;
  liked?: boolean;
  team?: TeamBrief;
  scoreIncluded?: boolean;
  status?: ClipOut['status'];
  durationMs?: number;
}

function clip(s: ClipSeed): ClipOut {
  const analysis = s.analysis ?? (s.values ? singleTrick(s.values) : null);
  const scored = s.values ?? null;
  const tricks = (Array.isArray(s.trick) ? s.trick : [s.trick]).map((name, i) => ({
    id: `${s.id.slice(0, -2)}t${i}`,
    // The API stores trick names lowercased (canonical_name).
    canonical_name: name.toLowerCase(),
    // Seeded like tags from before F4, named by position.
    analysis_index: null,
  }));
  const status = s.status ?? 'published';
  return {
    id: s.id,
    status,
    author: brief(s.author),
    video_url: `mock://video/${s.id}`,
    thumb_url: null,
    duration_ms: s.durationMs ?? 3200,
    source_fps: 60,
    steeze_score: analysis?.steeze_breakdown
      ? average(Object.values(analysis.steeze_breakdown))
      : scored
        ? average(scored)
        : null,
    published_at: status === 'published' ? ago(s.hoursAgo) : null,
    tricks,
    analysis,
    like_count: s.likes,
    comment_count: 0,
    view_count: s.views,
    liked_by_me: s.liked ?? false,
    team: s.team ?? null,
    score_included: s.scoreIncluded ?? true,
    analyze: true,
    created_at: ago(s.hoursAgo + 0.1),
  };
}

// Julia's three-trick line: kickflip landed, heelflip bailed, ollie landed
// (catch n/a). The clip score averages the landed tricks only.
const LINE_KF = [84, 80, 86, 75, 78, 83];
const LINE_OL = [79, 72, 81, 70, 73, null];
const lineAnalysis: AnalysisOut = {
  model_version: 'steeze-v0-uncalibrated',
  confidence: '0.84',
  steeze_breakdown: breakdown(
    SUBS.map((_, i) => {
      const xs = [LINE_KF[i], LINE_OL[i]].filter((v): v is number => v !== null && v !== undefined);
      return xs.length ? Number((xs.reduce((a, b) => a + b, 0) / xs.length).toFixed(1)) : null;
    }),
  ),
  failure_reason: null,
  tricks: [
    {
      outcome: 'landed',
      takeoff_ms: 1200,
      touchdown_ms: 1600,
      confidence: 0.9,
      subscores: breakdown(LINE_KF),
    },
    { outcome: 'bailed', takeoff_ms: 3900, touchdown_ms: 4300, confidence: 0.82, subscores: null },
    {
      outcome: 'landed',
      takeoff_ms: 6300,
      touchdown_ms: 6650,
      confidence: 0.88,
      subscores: breakdown(LINE_OL),
    },
  ],
  created_at: created,
};

const failedAnalysis: AnalysisOut = {
  model_version: 'steeze-v0-uncalibrated',
  confidence: '0.41',
  steeze_breakdown: null,
  failure_reason: 'no landed trick detected',
  tricks: [{ outcome: 'bailed', takeoff_ms: 1100, touchdown_ms: 1330, confidence: 0.66, subscores: null }],
  created_at: created,
};

function seedClips(): ClipOut[] {
  return [
    clip({
      id: ids.clips.marcoKickflip,
      author: 'marcosandoval',
      trick: 'Kickflip',
      hoursAgo: 2,
      values: [86, 79, 88, 72, 81, 90],
      likes: 148,
      views: 1200,
      liked: true,
      team: teams.downtown,
    }),
    clip({
      id: ids.clips.leoBs180,
      author: 'leotran',
      trick: 'Backside 180',
      hoursAgo: 5,
      values: [75, 70, 66, 73, 72, null],
      likes: 63,
      views: 410,
    }),
    clip({
      id: ids.clips.destinyHeelflip,
      author: 'destinyfoster',
      trick: 'Heelflip',
      hoursAgo: 26,
      values: [80, 76, 82, 74, 77, 79],
      likes: 120,
      views: 1000,
      team: teams.downtown,
    }),
    clip({
      id: ids.clips.juliaLine,
      author: 'juliavance',
      trick: ['Kickflip', 'Heelflip', 'Ollie'],
      hoursAgo: 24,
      analysis: lineAnalysis,
      likes: 92,
      views: 540,
      durationMs: 8400,
    }),
    clip({
      id: ids.clips.juliaKickflip,
      author: 'juliavance',
      trick: 'Kickflip',
      hoursAgo: 50,
      values: [82, 74, 91, 68, 77, 82],
      likes: 214,
      views: 1900,
      team: teams.downtown,
    }),
    clip({
      id: ids.clips.juliaBoardslide,
      author: 'juliavance',
      trick: 'Boardslide',
      hoursAgo: 120,
      values: [70, 78, 80, 74, 76, null],
      likes: 40,
      views: 300,
      scoreIncluded: false,
    }),
    clip({
      id: ids.clips.destinyKickflip,
      author: 'destinyfoster',
      trick: 'Kickflip',
      hoursAgo: 72,
      values: [76, 70, 78, 72, 70, 78],
      likes: 60,
      views: 500,
    }),
    clip({
      id: ids.clips.destinyVarial,
      author: 'destinyfoster',
      trick: 'Varial heelflip',
      hoursAgo: 96,
      values: [83, 80, 84, 78, 79, 82],
      likes: 75,
      views: 640,
    }),
    clip({
      id: ids.clips.destinyOllie,
      author: 'destinyfoster',
      trick: 'Ollie',
      hoursAgo: 140,
      values: [72, 68, 70, 66, 69, null],
      likes: 18,
      views: 150,
      scoreIncluded: false,
    }),
    clip({
      id: ids.clips.caseyHardflip,
      author: 'caseyoshiro',
      trick: 'Hardflip',
      hoursAgo: 30,
      values: [94, 90, 93, 89, 91, 95],
      likes: 301,
      views: 2400,
    }),
    clip({
      id: ids.clips.priyaTreflip,
      author: 'priyanair',
      trick: 'Tre flip',
      hoursAgo: 40,
      values: [83, 79, 84, 78, 80, 82],
      likes: 96,
      views: 880,
    }),
    clip({
      id: ids.clips.samVarial,
      author: 'samgreer',
      trick: 'Varial flip',
      hoursAgo: 60,
      values: [82, 78, 83, 77, 79, 81],
      likes: 77,
      views: 640,
    }),
    clip({
      id: ids.clips.juliaHeelflipFailed,
      author: 'juliavance',
      trick: 'Heelflip',
      hoursAgo: 0.05,
      analysis: failedAnalysis,
      likes: 0,
      views: 0,
      status: 'unanalyzable',
    }),
  ];
}

function comment(
  id: string,
  clipId: string,
  author: string,
  minutesAgo: number,
  body: string,
  replies: CommentOut[] = [],
): CommentOut {
  return {
    id,
    clip_id: clipId,
    author: brief(author),
    body,
    parent_id: null,
    replies: replies.map((r) => ({ ...r, parent_id: id })),
    created_at: new Date(Date.now() - minutesAgo * 60_000).toISOString(),
  };
}

function seedComments(): CommentOut[] {
  const c = ids.clips.marcoKickflip;
  const n = (i: number) => `c3000000-0000-4000-8000-${String(i).padStart(12, '0')}`;
  return [
    comment(n(1), c, 'leotran', 120, 'That catch was so clean. Pop looks higher than 86 to me though.', [
      comment(n(2), c, 'marcosandoval', 60, "I'll take 86. Next one's getting more tail."),
      comment(
        n(3),
        c,
        'destinyfoster',
        58,
        '@leotran the west lot ledge is sketchy too, the run-up is half gravel.',
      ),
    ]),
    comment(n(4), c, 'juliavance', 55, 'Roll-away 88 is crazy. Teach me how you ride out that clean.'),
    comment(n(5), c, 'priyanair', 40, 'First try or are we not talking about it', [
      comment(n(6), c, 'samgreer', 35, 'not first try lol'),
      comment(n(7), c, 'caseyoshiro', 30, 'twentieth, he said so'),
      comment(n(8), c, 'marcosandoval', 28, 'we do not talk about the other nineteen'),
    ]),
    comment(n(9), c, 'samgreer', 12, 'This should be counting toward the team average, easy.'),
    comment(n(10), ids.clips.juliaKickflip, 'marcosandoval', 300, 'Third try is the charm every time.'),
  ];
}

export interface TeamRanking {
  team: TeamBrief;
  score: string;
  score_delta: string;
}

export const teamRankings: TeamRanking[] = [
  { team: teams.nightShift, score: '84.10', score_delta: '7.40' },
  { team: teams.downtown, score: '79.60', score_delta: '5.10' },
  { team: teams.curbCult, score: '68.30', score_delta: '4.00' },
  { team: teams.westside, score: '76.00', score_delta: '2.20' },
  { team: teams.bowlRats, score: '81.70', score_delta: '0.90' },
];

export const ME_USERNAME = 'juliavance';
export const ME_EMAIL = 'julia@westlot.co';

export type MockPerson = (typeof people)[string];

/** Fresh copies of the seed records; db.ts owns the live state. */
export const seedPeople = () => structuredClone(people);
export { brief, seedClips, seedComments };

/** What the simulated worker decides for an upload (the prototype's outcome picker). */
export type MockOutcome = 'single' | 'line' | 'stepoff' | 'failed';

/** The analysis the simulated worker writes for each outcome, like the real worker's shape. */
export function simulatedAnalysis(outcome: MockOutcome): AnalysisOut {
  if (outcome === 'line') return structuredClone(lineAnalysis);
  if (outcome === 'failed') return structuredClone(failedAnalysis);
  if (outcome === 'stepoff') {
    // A landed trick, then stepping off at the very end of the clip, which
    // the analyzer lists as a second "trick" it couldn't judge.
    const a = singleTrick([78, 74, 62, 70, 72, null], 1300, '0.86');
    a.tricks.push({
      outcome: 'clip ends too soon after the landing',
      takeoff_ms: 4200,
      touchdown_ms: 4500,
      confidence: 0.5,
      subscores: null,
    });
    return a;
  }
  return singleTrick([81, 77, 86, 70, 75, 84], 1300, '0.88');
}

/** The clip score the worker stores: the mean of the breakdown's subscores. */
export function scoreOf(analysis: AnalysisOut): string | null {
  return analysis.steeze_breakdown ? average(Object.values(analysis.steeze_breakdown)) : null;
}
