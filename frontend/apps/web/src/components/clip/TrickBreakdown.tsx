import { type AnalyzedTrick, formatClipTime, trickScore } from '@tricklens/api';
import { useId, useState } from 'react';
import { Icon } from '../icons/Icon.tsx';
import { Chip } from '../ui/controls.tsx';
import styles from './clip.module.css';
import { SubscoreBars } from './Score.tsx';

const isLanded = (t: AnalyzedTrick) => t.outcome === 'landed';

function outcomeChip(t: AnalyzedTrick) {
  if (isLanded(t)) return <Chip tone="azure">Landed</Chip>;
  if (t.outcome === 'bailed') return <Chip tone="danger">Bailed</Chip>;
  return <Chip>Not judged</Chip>;
}

/** Where each trick happens in the clip: azure for landed, red otherwise. */
export function TrickTimeline({ tricks, durationMs }: { tricks: AnalyzedTrick[]; durationMs: number }) {
  return (
    <div>
      <div className={styles.timeline} aria-hidden="true">
        {tricks.map((t) => (
          <span
            key={`${t.takeoff_ms}-${t.touchdown_ms}-${t.outcome}`}
            className={`${styles.mark} ${isLanded(t) ? '' : styles.bad}`}
            style={{ left: `${Math.min(100, ((t.takeoff_ms ?? 0) / durationMs) * 100)}%` }}
          />
        ))}
      </div>
      <div className={styles.legend} aria-hidden="true">
        <span>
          <i /> Landed
        </span>
        <span>
          <i className={styles.bad} /> Not scored
        </span>
      </div>
    </div>
  );
}

/**
 * Every trick the analyzer found, in clip order. Landed tricks expand to
 * their own breakdown. The analyzer doesn't name tricks and nothing matches
 * them to the skater's tags (backend AnalyzedTrickOut), so rows are numbered.
 */
export function TrickBreakdown({ tricks }: { tricks: AnalyzedTrick[] }) {
  const firstLanded = tricks.findIndex(isLanded);
  const [open, setOpen] = useState<number | null>(firstLanded >= 0 ? firstLanded : null);
  const baseId = useId();

  return (
    <ol className={styles.tricks}>
      {tricks.map((t, i) => {
        const score = trickScore(t.subscores);
        const expanded = open === i;
        const panelId = `${baseId}-${i}`;
        const reason = isLanded(t)
          ? null
          : t.outcome === 'bailed'
            ? 'Bailed tricks are left out of the clip score.'
            : t.outcome;
        return (
          <li key={`${t.takeoff_ms}-${t.touchdown_ms}-${t.outcome}`} className={styles.trick}>
            <button
              type="button"
              className={styles.trickHead}
              aria-expanded={expanded}
              aria-controls={panelId}
              onClick={() => setOpen(expanded ? null : i)}
            >
              <span className={styles.trickIndex}>{i + 1}</span>
              <span className={styles.trickName}>
                Trick {i + 1}
                <span className={styles.trickMeta}>
                  {outcomeChip(t)}
                  {t.takeoff_ms !== null && t.takeoff_ms !== undefined && (
                    <span>at {formatClipTime(t.takeoff_ms)}</span>
                  )}
                </span>
              </span>
              {score !== null ? (
                <span className={styles.num} style={{ fontSize: '1.75rem' }}>
                  {Math.round(score)}
                </span>
              ) : (
                <span className="muted" style={{ fontSize: '0.875rem' }}>
                  Not scored
                </span>
              )}
              <Icon name={expanded ? 'chevronDown' : 'chevronRight'} size={18} />
            </button>
            {expanded && (
              <div id={panelId} className={styles.trickBody}>
                {t.subscores ? (
                  <SubscoreBars breakdown={t.subscores} notes={false} tight />
                ) : (
                  <p className="muted">{reason}</p>
                )}
              </div>
            )}
          </li>
        );
      })}
    </ol>
  );
}
