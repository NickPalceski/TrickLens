// The six subscores, in the API's fixed order (backend
// app/analyzer/calibration.py, SUBSCORES), with the words the UI uses.
import { toNumber } from './format.ts';

export const SUBSCORES = [
  { key: 'pop', label: 'Pop', short: 'Pop', note: 'How much air came off the tail.' },
  {
    key: 'landing_stability',
    label: 'Landing stability',
    short: 'Land',
    note: 'How clean the landing held on impact.',
  },
  { key: 'roll_away', label: 'Roll-away', short: 'Roll', note: 'How steady the ride-out was.' },
  { key: 'stomp', label: 'Stomp', short: 'Stomp', note: 'How committed and controlled the stomp looked.' },
  {
    key: 'compactness',
    label: 'Compactness',
    short: 'Comp',
    note: "How tight the trick's shape stayed in the air.",
  },
  { key: 'catch', label: 'Catch', short: 'Catch', note: 'How cleanly the board was caught underfoot.' },
] as const;

export type SubscoreKey = (typeof SUBSCORES)[number]['key'];

export interface SubscoreValue {
  key: SubscoreKey;
  label: string;
  short: string;
  note: string;
  /** 0–100, or null when it doesn't apply to the trick (catch on an ollie). */
  value: number | null;
}

/** A breakdown dict from the API as an ordered list; missing keys read as n/a. */
export function subscoreList(breakdown: Record<string, number | null> | null | undefined): SubscoreValue[] {
  return SUBSCORES.map((s) => ({ ...s, value: toNumber(breakdown?.[s.key] ?? null) }));
}

/** One trick's score: the mean of its subscores that apply, as the analyzer computes it. */
export function trickScore(subscores: Record<string, number | null> | null | undefined): number | null {
  const xs = subscoreList(subscores)
    .map((s) => s.value)
    .filter((v): v is number => v !== null);
  return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null;
}
