// Hooks for endpoints the frontend needs but the API doesn't have yet
// (docs/components/frontend.md, Known gaps). Only the mock API answers
// them. Each is shaped like the existing routes, so when the backend adds
// it, `make web-types` brings it into schema.ts, the call moves to the
// typed client, and this file shrinks.
import { useInfiniteQuery } from '@tanstack/react-query';
import type { Client } from 'openapi-fetch';
import { unwrap } from '../client.ts';
import { useApi } from '../context.tsx';
import type { FeedPage } from '../types.ts';
import { keys } from './keys.ts';

/** The routes below, in the same shape openapi-typescript generates. */
interface ProposedPaths {
  '/users/{username}/clips': {
    parameters: { query?: never; header?: never; path?: never; cookie?: never };
    get: {
      parameters: {
        query?: { limit?: number; cursor?: string | null };
        header?: never;
        path: { username: string };
        cookie?: never;
      };
      requestBody?: never;
      responses: { 200: { headers: { [name: string]: unknown }; content: { 'application/json': FeedPage } } };
    };
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
}

/**
 * PROPOSED `GET /users/{username}/clips`: a user's published clips, newest
 * first, keyset-paginated like the feed. Profiles need it for their clip grid.
 */
export function useUserClips(username: string) {
  const api = useApi() as unknown as Client<ProposedPaths>;
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
