import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { expectOk, unwrap } from '../client.ts';
import { useApi } from '../context.tsx';
import type { components } from '../schema.ts';
import type { UserMe, UserPublic } from '../types.ts';
import { keys } from './keys.ts';

/** The signed-in user (GET /users/me). */
export function useMe() {
  const api = useApi();
  return useQuery({
    queryKey: keys.me,
    queryFn: async () => unwrap(await api.GET('/users/me')),
  });
}

/** Any user's public profile (GET /users/{username}). */
export function useUser(username: string) {
  const api = useApi();
  return useQuery({
    queryKey: keys.user(username),
    queryFn: async () => unwrap(await api.GET('/users/{username}', { params: { path: { username } } })),
  });
}

/** A user's published clips (GET /users/{username}/clips), newest first, for the profile grid. */
export function useUserClips(username: string) {
  const api = useApi();
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
 * Follow or unfollow, shown immediately and rolled back if the API refuses.
 * Pass the user as currently displayed; the mutation flips it.
 */
export function useToggleFollow() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (user: UserPublic) => {
      const params = { params: { path: { username: user.username } } };
      expectOk(
        user.followed_by_me
          ? await api.DELETE('/users/{username}/follow', params)
          : await api.POST('/users/{username}/follow', params),
      );
    },
    onMutate: (user) => {
      const flip = (u: UserPublic): UserPublic => ({
        ...u,
        followed_by_me: !user.followed_by_me,
        follower_count: u.follower_count + (user.followed_by_me ? -1 : 1),
      });
      qc.setQueryData<UserPublic>(keys.user(user.username), (u) => (u ? flip(u) : u));
    },
    onError: (_e, user) => qc.setQueryData(keys.user(user.username), user),
    onSettled: (_d, _e, user) => {
      void qc.invalidateQueries({ queryKey: keys.user(user.username), exact: true });
      void qc.invalidateQueries({ queryKey: keys.feed });
    },
  });
}

export type ProfileFields = components['schemas']['ProfileUpdate'];
export interface ProfileEdit {
  user: components['schemas']['UserUpdate'];
  profile: ProfileFields;
}

/** Saves the editable parts of the signed-in user: name, bio, and setup. */
export function useUpdateMe() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    // The profile route returns only the profile, so it goes first and the
    // user route's full UserMe becomes the new cached `me`.
    mutationFn: async ({ user, profile }: ProfileEdit): Promise<UserMe> => {
      unwrap(await api.PATCH('/users/me/profile', { body: profile }));
      return unwrap(await api.PATCH('/users/me', { body: user }));
    },
    onSuccess: (me) => {
      qc.setQueryData(keys.me, me);
      void qc.invalidateQueries({ queryKey: keys.user(me.username) });
    },
  });
}

/** Registers the Cognito user with the API after sign-up (POST /users). */
export function useRegister() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: components['schemas']['UserCreate']) =>
      unwrap(await api.POST('/users', { body })),
    onSuccess: (me) => qc.setQueryData(keys.me, me),
  });
}
