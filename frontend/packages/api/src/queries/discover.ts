import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { unwrap } from '../client.ts';
import { useApi } from '../context.tsx';
import { keys } from './keys.ts';

export type DiscoverSort = 'score' | 'engagement';

/** This week's ranked clips (GET /discover/clips), offset-paginated. */
export function useDiscoverClips(sort: DiscoverSort) {
  const api = useApi();
  return useInfiniteQuery({
    queryKey: keys.discoverClips(sort),
    initialPageParam: 0,
    queryFn: async ({ pageParam }) =>
      unwrap(await api.GET('/discover/clips', { params: { query: { sort, limit: 12, offset: pageParam } } })),
    getNextPageParam: (last) => last.next_offset ?? undefined,
  });
}

/** Teams ranked by average-score increase over ~7 days (GET /discover/teams). */
export function useDiscoverTeams() {
  const api = useApi();
  return useQuery({
    queryKey: keys.discoverTeams,
    queryFn: async () => unwrap(await api.GET('/discover/teams', { params: { query: { limit: 10 } } })),
  });
}
