// Matching the skater's tags to the analyzer's tricks
// (docs/components/frontend.md, Tagging tricks).
import type { AnalyzedTrick, ClipOut } from './types.ts';

/**
 * Outcomes that are usually not a trick at all: since 6d-2 the analyzer
 * lists every pop it finds, and stepping or rolling off at the very end of
 * a clip comes back as one of these (docs/components/analyzer.md, Known
 * limits). The review step pre-ticks "Not a trick" for them.
 */
const USUALLY_NOT_A_TRICK = new Set(['clip ends too soon after the landing']);

export const usuallyNotATrick = (t: AnalyzedTrick) => USUALLY_NOT_A_TRICK.has(t.outcome);

export interface ShownTrick {
  trick: AnalyzedTrick;
  /** Its index in `analysis.tricks`. */
  index: number;
  /** The skater's tag for it, raw (format with formatTrickName). */
  name?: string;
}

/**
 * The analyzed tricks a clip shows, in clip order, with the tag naming each.
 * Tags that carry `analysis_index` name their trick directly, and an analyzed
 * trick no tag names is one the skater said isn't a trick, so it's left out.
 * Older tags have no index: then tag i names trick i when the counts match,
 * and otherwise every trick shows, unnamed.
 */
export function shownTricks(clip: ClipOut): ShownTrick[] {
  const analyzed = clip.analysis?.tricks ?? [];
  const byIndex = new Map<number, string>(
    clip.tricks.flatMap((t): [number, string][] =>
      t.analysis_index == null ? [] : [[t.analysis_index, t.canonical_name]],
    ),
  );
  if (byIndex.size > 0) {
    return analyzed.flatMap((trick, index) => {
      const name = byIndex.get(index);
      return name === undefined ? [] : [{ trick, index, name }];
    });
  }
  const positional = clip.tricks.length === analyzed.length;
  return analyzed.map((trick, index) => ({
    trick,
    index,
    name: positional ? clip.tricks[index]?.canonical_name : undefined,
  }));
}
