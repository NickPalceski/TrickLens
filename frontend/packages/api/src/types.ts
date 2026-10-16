// Friendly names for the generated API types. schema.ts is generated from
// the backend's OpenAPI spec (`make web-types`) and never edited by hand.
import type { components, paths } from './schema.ts';

export type { components, paths };

type Schemas = components['schemas'];

export type UserMe = Schemas['UserMe'];
export type UserPublic = Schemas['UserPublic'];
export type UserBrief = Schemas['UserBrief'];
export type Profile = Schemas['ProfileOut'];
export type ClipOut = Schemas['ClipOut'];
export type ClipStatus = Schemas['ClipStatus'];
export type AnalysisOut = Schemas['AnalysisOut'];
export type AnalyzedTrick = Schemas['AnalyzedTrickOut'];
export type FeedPage = Schemas['FeedPage'];
export type CommentOut = Schemas['CommentOut'];
export type CommentPage = Schemas['CommentPage'];
export type TeamOut = Schemas['TeamOut'];
export type TeamBrief = Schemas['TeamBrief'];
export type TeamMember = Schemas['TeamMemberOut'];
export type DiscoverClipPage = Schemas['DiscoverClipPage'];
export type DiscoverTeamPage = Schemas['DiscoverTeamPage'];
