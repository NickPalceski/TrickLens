import { useQuery } from '@tanstack/react-query';
import { unwrap } from '../client.ts';
import { useApi } from '../context.tsx';

export const userKeys = {
  me: ['users', 'me'] as const,
  byUsername: (username: string) => ['users', username] as const,
};

/** The signed-in user (GET /users/me). */
export function useMe() {
  const api = useApi();
  return useQuery({
    queryKey: userKeys.me,
    queryFn: async () => unwrap(await api.GET('/users/me')),
  });
}

/** Any user's public profile (GET /users/{username}). */
export function useUser(username: string) {
  const api = useApi();
  return useQuery({
    queryKey: userKeys.byUsername(username),
    queryFn: async () => unwrap(await api.GET('/users/{username}', { params: { path: { username } } })),
  });
}
