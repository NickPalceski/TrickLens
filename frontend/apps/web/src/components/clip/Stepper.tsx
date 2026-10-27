import { Icon } from '../icons/Icon.tsx';
import styles from './Stepper.module.css';

export type StepKind = 'done' | 'current' | 'failed' | 'upcoming' | 'skipped';
export interface Step {
  label: string;
  kind: StepKind;
}

const SPOKEN: Record<StepKind, string> = {
  done: 'done',
  current: 'in progress',
  failed: 'failed',
  upcoming: 'not yet',
  skipped: 'skipped',
};

/** A clip's lifecycle as steps: across the page on desktop, down it on phones. */
export function Stepper({ steps, label = 'Clip status' }: { steps: Step[]; label?: string }) {
  return (
    <ol className={styles.steps} aria-label={label}>
      {steps.map((s, i) => (
        <li
          key={s.label}
          className={`${styles.step} ${styles[s.kind]}`}
          aria-current={s.kind === 'current' ? 'step' : undefined}
        >
          <span className={styles.dot} aria-hidden="true">
            {s.kind === 'done' && <Icon name="check" size={14} strokeWidth={3} />}
            {s.kind === 'failed' && <Icon name="close" size={14} strokeWidth={3} />}
            {s.kind === 'current' && <span className={styles.spin} />}
            {(s.kind === 'upcoming' || s.kind === 'skipped') && i + 1}
          </span>
          <span className={styles.label}>
            {s.label}
            <span className="visually-hidden">: {SPOKEN[s.kind]}</span>
          </span>
        </li>
      ))}
    </ol>
  );
}
