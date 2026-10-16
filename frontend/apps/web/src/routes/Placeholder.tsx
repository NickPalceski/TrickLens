import styles from './Placeholder.module.css';

interface PlaceholderProps {
  title: string;
  /** What the finished screen does. */
  summary: string;
  /** Which build phase delivers it (docs/components/frontend.md, Build phases). */
  phase: 2 | 3 | 4;
  /** Artboard names on the design canvas. */
  artboards: string[];
}

/** Stand-in for a screen that's designed but not built yet. */
export function Placeholder({ title, summary, phase, artboards }: PlaceholderProps) {
  return (
    <section className={styles.page}>
      <h1 className={styles.title}>{title}</h1>
      <p className={styles.summary}>{summary}</p>
      <div className={styles.card}>
        <span className="label">Coming in phase {phase}</span>
        <p>
          Designed on the canvas as <strong>{artboards.join(', ')}</strong>.
        </p>
      </div>
    </section>
  );
}
