import { describe, expect, it } from 'vitest';
import { shownTricks, usuallyNotATrick } from './tricks.ts';
import type { AnalyzedTrick, ClipOut, TrickTag } from './types.ts';

const trick = (outcome: string): AnalyzedTrick => ({ outcome, confidence: 0.9 });
const tag = (canonical_name: string, analysis_index: number | null = null): TrickTag => ({
  id: canonical_name,
  canonical_name,
  analysis_index,
});
const clipWith = (outcomes: string[], tricks: TrickTag[]) =>
  ({ analysis: { tricks: outcomes.map(trick) }, tricks }) as unknown as ClipOut;

describe('shownTricks', () => {
  const line = ['landed', 'bailed', 'clip ends too soon after the landing'];

  it('names tricks by index and leaves out the ones nobody named', () => {
    const shown = shownTricks(clipWith(line, [tag('kickflip', 0), tag('heelflip', 1)]));
    expect(shown.map((s) => [s.index, s.name])).toEqual([
      [0, 'kickflip'],
      [1, 'heelflip'],
    ]);
  });

  it('falls back to position for tags without an index, when the counts match', () => {
    const shown = shownTricks(clipWith(line, [tag('a'), tag('b'), tag('c')]));
    expect(shown.map((s) => s.name)).toEqual(['a', 'b', 'c']);
  });

  it('shows every trick unnamed when they can not be matched', () => {
    const shown = shownTricks(clipWith(line, [tag('a')]));
    expect(shown.map((s) => s.name)).toEqual([undefined, undefined, undefined]);
  });

  it('knows a step-off at the end is usually not a trick', () => {
    expect(line.map((o) => usuallyNotATrick(trick(o)))).toEqual([false, false, true]);
  });
});
