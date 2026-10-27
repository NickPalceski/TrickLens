import { formatScore, subscoreList, toNumber } from '@tricklens/api';
import { Chip } from '../ui/controls.tsx';
import styles from './clip.module.css';

type Breakdown = Record<string, number | null> | null | undefined;

/** The tilted yellow score on a clip's video. */
export function ScoreSticker({ score }: { score: string | null | undefined }) {
  if (toNumber(score) === null) return null;
  return (
    <span className={styles.sticker} role="img" aria-label={`Steeze ${formatScore(score)} out of 100`}>
      <span className={styles.stickerNum} aria-hidden="true">
        {formatScore(score)}
      </span>
      <span className={styles.stickerLabel} aria-hidden="true">
        STEEZE
      </span>
    </span>
  );
}

/** The compact six-subscore row under a feed post. */
export function SubscoreStrip({ breakdown }: { breakdown: Breakdown }) {
  return (
    <dl className={styles.strip} aria-label="Steeze breakdown">
      {subscoreList(breakdown).map((s) => (
        <div key={s.key} style={{ minWidth: 0 }}>
          <dt title={s.label}>{s.short}</dt>
          <dd>
            <div className={`${styles.bar} ${s.value === null ? styles.barNa : ''}`} aria-hidden="true">
              {s.value !== null && <div className={styles.barFill} style={{ width: `${s.value}%` }} />}
            </div>
            {s.value === null ? (
              <span className={styles.na} title="Doesn't apply to this trick">
                n/a
              </span>
            ) : (
              <span className={styles.num}>{Math.round(s.value)}</span>
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** The full breakdown: one labelled bar per subscore, with what it measures. */
export function SubscoreBars({
  breakdown,
  notes = true,
  tight = false,
}: {
  breakdown: Breakdown;
  notes?: boolean;
  tight?: boolean;
}) {
  return (
    <ul className={`${styles.bars} ${tight ? styles.tight : ''}`}>
      {subscoreList(breakdown).map((s) => (
        <li key={s.key}>
          <div className={styles.barRow}>
            <span className={`${styles.barLabel} ${s.value === null ? styles.off : ''}`}>{s.label}</span>
            {s.value === null ? (
              <span className={styles.na}>n/a</span>
            ) : (
              <span className={styles.num}>{Math.round(s.value)}</span>
            )}
          </div>
          <div className={`${styles.bar} ${s.value === null ? styles.barNa : ''}`} aria-hidden="true">
            {s.value !== null && <div className={styles.barFill} style={{ width: `${s.value}%` }} />}
          </div>
          {notes && (
            <p className={styles.note}>
              {s.value === null ? "Doesn't apply to this trick, so it's left out of the average." : s.note}
            </p>
          )}
        </li>
      ))}
    </ul>
  );
}

/** The big score with its context chip ("High confidence", "2 of 3 landed"). */
export function ScoreBlock({
  score,
  chip,
  size = 4.5,
}: {
  score: string | null | undefined;
  chip?: string;
  size?: number;
}) {
  return (
    <div className={styles.scoreBlock}>
      <span className={styles.bigScore}>
        <span className={styles.bigNum} style={{ fontSize: `${size}rem` }}>
          {formatScore(score)}
        </span>
        <span className={styles.outOf}>/100</span>
      </span>
      {chip && <Chip tone="azure">{chip}</Chip>}
    </div>
  );
}

/** "High confidence" etc., from the analysis's 0–1 confidence. */
export function confidenceLabel(confidence: string | number | null | undefined): string | undefined {
  const c = toNumber(confidence);
  if (c === null) return undefined;
  if (c >= 0.8) return 'High confidence';
  if (c >= 0.6) return 'Medium confidence';
  return 'Low confidence';
}
