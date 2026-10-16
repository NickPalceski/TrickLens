// Sample data for the mock API: the same people and numbers as the design
// canvas. Typed against the generated schema, so it can't drift from what
// the real API returns. Marked as sample data wherever the UI shows it.
import type { UserMe, UserPublic } from '../types.ts';

const created = '2026-08-02T17:20:00Z';

export const me: UserMe = {
  id: '0b6f3c1e-5d2a-4c8e-9a71-2f4e8d6b1a01',
  username: 'juliavance',
  email: 'julia@westlot.co',
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
  followed_by_me: false,
  average_score: '79.30',
  created_at: created,
};

export const users: Record<string, UserPublic> = {
  juliavance: { ...me },
  destinyfoster: {
    id: '5a1d2e3f-6b7c-4d8e-9f01-2a3b4c5d6e02',
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
    followed_by_me: false,
    average_score: '77.70',
    created_at: created,
  },
};
