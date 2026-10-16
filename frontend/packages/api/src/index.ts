export {
  type ApiClient,
  type ApiClientOptions,
  ApiError,
  createApiClient,
  expectOk,
  unwrap,
} from './client.ts';
export { ApiProvider, useApi } from './context.tsx';
export {
  formatAverage,
  formatClipTime,
  formatCount,
  formatScore,
  formatTimeAgo,
  toNumber,
} from './format.ts';
export { patchClip } from './queries/cache.ts';
export {
  useClip,
  useFeed,
  useRecordView,
  useSetScoreIncluded,
  useToggleLike,
} from './queries/clips.ts';
export { useAddComment, useComments, useDeleteComment } from './queries/comments.ts';
export { type DiscoverSort, useDiscoverClips, useDiscoverTeams } from './queries/discover.ts';
export { keys } from './queries/keys.ts';
export { useUserClips } from './queries/proposed.ts';
export {
  type ProfileEdit,
  type ProfileFields,
  useMe,
  useRegister,
  useToggleFollow,
  useUpdateMe,
  useUser,
} from './queries/users.ts';
export { SUBSCORES, type SubscoreKey, type SubscoreValue, subscoreList, trickScore } from './subscores.ts';
export type * from './types.ts';
