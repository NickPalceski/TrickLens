import styles from './Logo.module.css';

/** The skateboard mark plus the wordmark. Colors follow the theme. */
export function Logo({ size = 28, wordmark = true }: { size?: number; wordmark?: boolean }) {
  return (
    <span className={styles.logo}>
      <svg width={size} height={size} viewBox="0 0 30 30" fill="none" aria-hidden="true">
        <rect x="3" y="12" width="24" height="5.5" rx="2.75" fill="var(--ink)" />
        <circle cx="8.5" cy="22.5" r="3.2" fill="var(--azure)" stroke="var(--ink)" strokeWidth="1.6" />
        <circle cx="21.5" cy="22.5" r="3.2" fill="var(--azure)" stroke="var(--ink)" strokeWidth="1.6" />
        <path
          d="M6 12 Q7 7 10.5 6.5 M24 12 Q23 7 19.5 6.5"
          stroke="var(--ink)"
          strokeWidth="2.2"
          strokeLinecap="round"
        />
      </svg>
      {wordmark ? (
        <span className={styles.word}>TrickLens</span>
      ) : (
        <span className="visually-hidden">TrickLens</span>
      )}
    </span>
  );
}
