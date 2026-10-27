import styles from './Avatar.module.css';

function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  const letters = parts.length > 1 ? `${parts[0]?.[0] ?? ''}${parts.at(-1)?.[0] ?? ''}` : name.slice(0, 2);
  return letters.toUpperCase();
}

interface AvatarProps {
  /** Display name, or the username when there isn't one. */
  name: string;
  src?: string | null;
  /** Size in rem. */
  size?: number;
  /** Yellow instead of azure, e.g. to mark the clip owner in a thread. */
  highlight?: boolean;
}

export function Avatar({ name, src, size = 2.25, highlight = false }: AvatarProps) {
  const style = { width: `${size}rem`, height: `${size}rem`, fontSize: `${(size * 0.36).toFixed(3)}rem` };
  if (src) return <img className={styles.avatar} src={src} alt="" style={style} />;
  return (
    <span
      className={`${styles.avatar} ${highlight ? styles.highlight : ''}`}
      style={style}
      aria-hidden="true"
    >
      {initials(name)}
    </span>
  );
}
