/**
 * The API sends Decimal fields (steeze_score, average_score, confidence) as
 * JSON strings such as "79.50", which keeps their precision exact. Parse
 * them here, at the edge, rather than in every component.
 */
export function toNumber(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null;
  const n = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

/** A steeze score for display: whole numbers on clips ("79"). */
export function formatScore(value: string | number | null | undefined): string {
  const n = toNumber(value);
  return n === null ? '–' : String(Math.round(n));
}

/** An average for display: one decimal ("79.3"). */
export function formatAverage(value: string | number | null | undefined): string {
  const n = toNumber(value);
  return n === null ? '–' : n.toFixed(1);
}

/** Compact counts for likes and views: 1.2k, 18k, 2.4M. */
export function formatCount(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(n < 10_000 ? 1 : 0).replace(/\.0$/, '')}k`;
  return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`;
}

/** "now", "12m", "5h", "3d", "6w": compact relative time for posts and comments. */
export function formatTimeAgo(iso: string, now: number = Date.now()): string {
  const s = Math.max(0, (now - Date.parse(iso)) / 1000);
  if (s < 60) return 'now';
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86_400) return `${Math.floor(s / 3600)}h`;
  if (s < 7 * 86_400) return `${Math.floor(s / 86_400)}d`;
  return `${Math.floor(s / (7 * 86_400))}w`;
}

/** Milliseconds into a clip as m:ss.s ("0:03.9"). */
export function formatClipTime(ms: number): string {
  const total = ms / 1000;
  const m = Math.floor(total / 60);
  return `${m}:${(total - m * 60).toFixed(1).padStart(4, '0')}`;
}
