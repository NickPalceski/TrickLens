/** Every query key in one place, so invalidation can't miss a spelling. */
export const keys = {
  me: ['users', 'me'] as const,
  user: (username: string) => ['users', username] as const,
  userClips: (username: string) => ['users', username, 'clips'] as const,
  drafts: ['users', 'me', 'drafts'] as const,
  myTeams: ['users', 'me', 'teams'] as const,
  feed: ['feed'] as const,
  clip: (id: string) => ['clips', id] as const,
  comments: (clipId: string) => ['clips', clipId, 'comments'] as const,
  discoverClips: (sort: 'score' | 'engagement') => ['discover', 'clips', sort] as const,
  discoverTeams: ['discover', 'teams'] as const,
  team: (slug: string) => ['teams', slug] as const,
  teamMembers: (slug: string) => ['teams', slug, 'members'] as const,
  teamClips: (slug: string) => ['teams', slug, 'clips'] as const,
  joinRequests: (slug: string) => ['teams', slug, 'join-requests'] as const,
  myJoinRequest: (slug: string) => ['teams', slug, 'join-requests', 'mine'] as const,
  myInvites: ['teams', 'invites', 'mine'] as const,
};
