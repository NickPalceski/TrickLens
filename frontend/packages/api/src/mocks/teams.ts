// Teams for the mock API: the design canvas's Downtown Skaters plus the
// teams Discover ranks, and one still forming that @juliavance has been
// invited to found. Rules follow backend app/api/routes/teams.py.
import type { JoinPolicy, TeamLevel, TeamOut, TeamRole, UserBrief } from '../types.ts';
import { teams as briefs } from './data.ts';

export const TEAM_MAX_MEMBERS = 20; // backend app/models/team.py
export const TEAM_MIN_FOUNDING_INVITES = 2;

export interface MockMember {
  username: string;
  role: TeamRole;
  joined_at: string;
}

export interface MockJoinRequest {
  username: string;
  /** "request": they asked to join. "invite": the team asked them (founding or not). */
  kind: 'request' | 'invite';
  founding: boolean;
  created_at: string;
}

export interface MockTeam {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  level: TeamLevel;
  join_policy: JoinPolicy;
  owner: string;
  created_at: string;
  founded_at: string | null;
  members: MockMember[];
  requests: MockJoinRequest[];
  /** Usernames following the team, on top of `follower_base` followers not in the sample data. */
  followers: Set<string>;
  follower_base: number;
  average_score: string | null;
}

const DAY = 86_400_000;
const daysAgo = (d: number) => new Date(Date.now() - d * DAY).toISOString();

function team(
  brief: { id: string; name: string; slug: string },
  rest: Omit<
    MockTeam,
    'id' | 'name' | 'slug' | 'created_at' | 'founded_at' | 'members' | 'requests' | 'followers'
  > & {
    members: [string, TeamRole][];
    requests?: [string, MockJoinRequest['kind'], boolean][];
    followers?: string[];
    forming?: boolean;
  },
): MockTeam {
  const { members, requests = [], followers = [], forming = false, ...fields } = rest;
  return {
    ...brief,
    ...fields,
    created_at: daysAgo(60),
    founded_at: forming ? null : daysAgo(58),
    members: members.map(([username, role], i) => ({ username, role, joined_at: daysAgo(58 - i) })),
    requests: requests.map(([username, kind, founding], i) => ({
      username,
      kind,
      founding,
      created_at: daysAgo(2 - i * 0.5),
    })),
    followers: new Set(followers),
  };
}

export function seedTeams(): MockTeam[] {
  return [
    team(briefs.downtown, {
      description:
        'Filming west-lot ledges and downtown gaps. All levels welcome to watch, intermediate and up to skate with us.',
      level: 'intermediate',
      join_policy: 'request',
      owner: 'juliavance',
      members: [
        ['juliavance', 'owner'],
        ['marcosandoval', 'admin'],
        ['leotran', 'member'],
        ['destinyfoster', 'member'],
      ],
      requests: [
        ['priyanair', 'request', false],
        ['samgreer', 'request', false],
      ],
      followers: ['juliavance'],
      follower_base: 211,
      average_score: '79.60',
    }),
    team(briefs.nightShift, {
      description: 'Late sessions under the parking-garage lights.',
      level: 'advanced',
      join_policy: 'open',
      owner: 'caseyoshiro',
      members: [
        ['caseyoshiro', 'owner'],
        ['priyanair', 'member'],
      ],
      follower_base: 340,
      average_score: '84.10',
    }),
    team(briefs.curbCult, {
      description: 'Curbs, manual pads, and nothing over knee height.',
      level: 'beginner',
      join_policy: 'invite_only',
      owner: 'samgreer',
      members: [
        ['samgreer', 'owner'],
        ['leotran', 'member'],
      ],
      follower_base: 58,
      average_score: '68.30',
    }),
    team(briefs.westside, {
      description: 'Ledge tech on the west side. Ask to join and show us a clip.',
      level: 'intermediate',
      join_policy: 'request',
      owner: 'priyanair',
      members: [
        ['priyanair', 'owner'],
        ['destinyfoster', 'member'],
        ['marcosandoval', 'member'],
      ],
      follower_base: 120,
      average_score: '76.00',
    }),
    team(briefs.bowlRats, {
      description: 'Transition only. Bring knee pads.',
      level: 'advanced',
      join_policy: 'open',
      owner: 'leotran',
      members: [
        ['leotran', 'owner'],
        ['caseyoshiro', 'member'],
      ],
      follower_base: 95,
      average_score: '81.70',
    }),
    // Forming: Marco invited Julia and Priya to found it; Priya accepted.
    team(
      { id: 'b2000000-0000-4000-8000-000000000006', name: 'Ledge Lords', slug: 'ledge_lords' },
      {
        description: 'A crew for long ledge lines. Founding now.',
        level: 'intermediate',
        join_policy: 'open',
        owner: 'marcosandoval',
        members: [
          ['marcosandoval', 'owner'],
          ['priyanair', 'member'],
        ],
        requests: [['juliavance', 'invite', true]],
        follower_base: 0,
        average_score: null,
        forming: true,
      },
    ),
  ];
}

/** TeamOut as the API would return it to `viewer`. */
export function teamOut(t: MockTeam, viewer: string, brief: (username: string) => UserBrief): TeamOut {
  const mine = t.members.find((m) => m.username === viewer);
  return {
    id: t.id,
    name: t.name,
    slug: t.slug,
    description: t.description,
    level: t.level,
    join_policy: t.join_policy,
    owner: brief(t.owner),
    member_count: t.members.length,
    follower_count: t.follower_base + t.followers.size,
    followed_by_me: t.followers.has(viewer),
    average_score: t.average_score,
    my_role: mine?.role ?? null,
    founded: t.founded_at !== null,
    pending_founders:
      t.founded_at === null ? t.requests.filter((r) => r.founding).map((r) => brief(r.username)) : [],
    created_at: t.created_at,
  };
}
