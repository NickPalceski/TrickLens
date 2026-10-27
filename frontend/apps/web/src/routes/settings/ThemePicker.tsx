import { themes } from '@tricklens/tokens';
import { type ThemePreference, useTheme } from '../../app/theme.tsx';
import { Icon, type IconName } from '../../components/icons/Icon.tsx';
import styles from './ThemePicker.module.css';

const OPTIONS: { value: ThemePreference; label: string; hint: string; icon: IconName }[] = [
  { value: 'light', label: 'Light', hint: 'Cream and brown', icon: 'sun' },
  { value: 'dark', label: 'Dark', hint: 'Deep brown, yellow accents', icon: 'moon' },
  { value: 'system', label: 'Match system', hint: 'Follows your device', icon: 'monitor' },
];

/** A tiny drawing of the app in one theme, so each option shows what it picks. */
function Preview({ theme }: { theme: 'light' | 'dark' }) {
  const t = themes[theme];
  return (
    <span className={styles.previewPane} style={{ background: t.bg }}>
      <span className={styles.previewTitle} style={{ background: t.ink }} />
      <span className={styles.previewCard} style={{ background: t.surface }}>
        <span className={styles.previewBar} style={{ background: t.track }}>
          <span style={{ width: '70%', background: 'var(--yellow)' }} />
        </span>
        <span className={styles.previewBar} style={{ background: t.track }}>
          <span style={{ width: '45%', background: 'var(--azure)' }} />
        </span>
      </span>
    </span>
  );
}

export function ThemePicker() {
  const { preference, setPreference } = useTheme();
  return (
    <fieldset className={styles.grid}>
      <legend className="visually-hidden">Theme</legend>
      {OPTIONS.map((o) => {
        const selected = preference === o.value;
        return (
          <label key={o.value} className={`${styles.option} ${selected ? styles.selected : ''}`}>
            <input
              type="radio"
              name="theme"
              value={o.value}
              checked={selected}
              onChange={() => setPreference(o.value)}
              className="visually-hidden"
            />
            <span className={styles.preview} aria-hidden="true">
              {o.value === 'system' ? (
                <>
                  <Preview theme="light" />
                  <Preview theme="dark" />
                </>
              ) : (
                <Preview theme={o.value} />
              )}
            </span>
            <span className={styles.meta}>
              <Icon name={o.icon} size={16} />
              <span className={styles.text}>
                <span className={styles.label}>{o.label}</span>
                <span className={styles.hint}>{o.hint}</span>
              </span>
              {selected && (
                <span className={styles.check}>
                  <Icon name="check" size={11} strokeWidth={3} />
                </span>
              )}
            </span>
          </label>
        );
      })}
    </fieldset>
  );
}
