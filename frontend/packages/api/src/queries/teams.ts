import {
  type QueryClient,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';
import { expectOk, unwrap } from '../client.ts';
import { useApi } from '../context.tsx';
import type { TeamCreate, TeamOut, TeamRole, TeamUpdate } from '../types.ts';
import { keys } from './keys.ts';

const path = (slug: string) => ({ params: { path: { slug } } });

/** Refresh everything about one team, plus the lists it appears in. */
function invalidateTeam(qc: QueryClient, slug: string) {
  void qc.invalidateQueries({ queryKey: keys.team(slug) });
  void qc.invalidateQueries({ queryKey: keys.myTeams });
  void qc.invalidateQueries({ queryKey: keys.myInvites });
}

/** A team (GET /teams/{slug}): founded, or forming and you're its owner or a founding invitee. */
export function useTeam(slug: string) {
  const api = useApi();
  return useQuery({
    queryKey: keys.team(slug),
    queryFn: async () => unwrap(await api.GET('/teams/{slug}', path(slug))),
  });
}

/**
 * Teams you're a member of (GET /users/me/teams), with your role
 * (`my_role`), forming ones you own included. The Teams tab, and "Tag to a
 * team" before publishing, which may only offer your own teams.
 */
export function useMyTeams() {
  const api = useApi();
  return useQuery({
    queryKey: keys.myTeams,
    queryFn: async () => unwrap(await api.GET('/users/me/teams')),
  });
}

/** A team's published clips (GET /teams/{slug}/clips), newest first. */
export function useTeamClips(slug: string, enabled = true) {
  const api = useApi();
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
 * Whether you've asked to join (GET /teams/{slug}/join-requests/mine).
 * `TeamOut` doesn't say, so without it "Request sent" wouldn't survive a reload.
 */
export function useMyJoinRequest(slug: string, enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: keys.myJoinRequest(slug),
    enabled,
    queryFn: async () => unwrap(await api.GET('/teams/{slug}/join-requests/mine', path(slug))),
  });
}

export function useTeamMembers(slug: string, enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: keys.teamMembers(slug),
    enabled,
    queryFn: async () => unwrap(await api.GET('/teams/{slug}/members', path(slug))),
  });
}

/** Pending join requests (owner and admins only). */
export function useJoinRequests(slug: string, enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: keys.joinRequests(slug),
    enabled,
    queryFn: async () => unwrap(await api.GET('/teams/{slug}/join-requests', path(slug))),
  });
}

/** Invites waiting for you, founding or not (GET /teams/invites/mine). */
export function useMyInvites() {
  const api = useApi();
  return useQuery({
    queryKey: keys.myInvites,
    queryFn: async () => unwrap(await api.GET('/teams/invites/mine')),
  });
}

export function useCreateTeam() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: TeamCreate) => unwrap(await api.POST('/teams', { body })),
    onSuccess: (team) => {
      qc.setQueryData(keys.team(team.slug), team);
      void qc.invalidateQueries({ queryKey: keys.myTeams });
    },
  });
}

/** Owner only. The slug can't change. */
export function useUpdateTeam(slug: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: TeamUpdate) => unwrap(await api.PATCH('/teams/{slug}', { ...path(slug), body })),
    onSuccess: (team) => {
      qc.setQueryData(keys.team(slug), team);
      void qc.invalidateQueries({ queryKey: keys.myTeams });
    },
  });
}

/** Owner only: deletes the team, or cancels it while it's still forming. */
export function useDeleteTeam(slug: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => expectOk(await api.DELETE('/teams/{slug}', path(slug))),
    onSuccess: () => {
      qc.removeQueries({ queryKey: keys.team(slug) });
      void qc.invalidateQueries({ queryKey: keys.myTeams });
    },
  });
}

export function useToggleTeamFollow() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (team: TeamOut) =>
      unwrap(
        team.followed_by_me
          ? await api.DELETE('/teams/{slug}/follow', path(team.slug))
          : await api.POST('/teams/{slug}/follow', path(team.slug)),
      ),
    onMutate: (team) =>
      qc.setQueryData<TeamOut>(keys.team(team.slug), (t) =>
        t
          ? {
              ...t,
              followed_by_me: !team.followed_by_me,
              follower_count: t.follower_count + (team.followed_by_me ? -1 : 1),
            }
          : t,
      ),
    onError: (_e, team) => qc.setQueryData(keys.team(team.slug), team),
    onSuccess: (team) => {
      qc.setQueryData(keys.team(team.slug), team);
      void qc.invalidateQueries({ queryKey: keys.feed });
    },
  });
}

/** Join an open team, or ask to join a request-only one. */
export function useJoinTeam(slug: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => unwrap(await api.POST('/teams/{slug}/join', path(slug))),
    onSuccess: (team) => {
      qc.setQueryData(keys.team(slug), team);
      void qc.invalidateQueries({ queryKey: keys.myJoinRequest(slug) });
      void qc.invalidateQueries({ queryKey: keys.teamMembers(slug) });
      void qc.invalidateQueries({ queryKey: keys.myTeams });
    },
  });
}

/** Take back a pending join request. */
export function useWithdrawJoin(slug: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => unwrap(await api.DELETE('/teams/{slug}/join', path(slug))),
    onSuccess: (team) => {
      qc.setQueryData(keys.team(slug), team);
      void qc.invalidateQueries({ queryKey: keys.myJoinRequest(slug) });
    },
  });
}

/** Owner/admin: approve or turn down someone's request to join. */
export function useAnswerJoinRequest(slug: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ username, accept }: { username: string; accept: boolean }) => {
      const p = { params: { path: { slug, username } } };
      if (accept) unwrap(await api.POST('/teams/{slug}/join-requests/{username}/accept', p));
      else expectOk(await api.POST('/teams/{slug}/join-requests/{username}/reject', p));
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.joinRequests(slug) });
      void qc.invalidateQueries({ queryKey: keys.teamMembers(slug) });
      void qc.invalidateQueries({ queryKey: keys.team(slug), exact: true });
    },
  });
}

/** Owner/admin: invite someone to a founded team. */
export function useInviteMember(slug: string) {
  const api = useApi();
  return useMutation({
    mutationFn: async (username: string) =>
      expectOk(await api.POST('/teams/{slug}/invites', { ...path(slug), body: { username } })),
  });
}

/**
 * Accept or reject an invite to you. For a founding invite, rejecting
 * cancels the whole team, and the last acceptance founds it.
 */
export function useAnswerInvite(slug: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (accept: boolean) => {
      if (accept) unwrap(await api.POST('/teams/{slug}/invites/mine/accept', path(slug)));
      else expectOk(await api.POST('/teams/{slug}/invites/mine/reject', path(slug)));
    },
    onSuccess: (_d, accept) => {
      if (accept) invalidateTeam(qc, slug);
      else {
        qc.removeQueries({ queryKey: keys.team(slug) });
        void qc.invalidateQueries({ queryKey: keys.myInvites });
      }
      void qc.invalidateQueries({ queryKey: keys.teamMembers(slug) });
    },
  });
}

/** Owner only: make a member an admin, or back. */
export function useSetMemberRole(slug: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ username, role }: { username: string; role: Exclude<TeamRole, 'owner'> }) =>
      unwrap(
        await api.PATCH('/teams/{slug}/members/{username}', {
          params: { path: { slug, username } },
          body: { role },
        }),
      ),
    onSuccess: () => void qc.invalidateQueries({ queryKey: keys.teamMembers(slug) }),
  });
}

/** Remove a member (owner: anyone but themselves; admin: members only), or leave (yourself). */
export function useRemoveMember(slug: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (username: string) =>
      expectOk(
        await api.DELETE('/teams/{slug}/members/{username}', { params: { path: { slug, username } } }),
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.teamMembers(slug) });
      invalidateTeam(qc, slug);
    },
  });
}
