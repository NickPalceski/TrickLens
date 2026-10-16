import {
  type InputHTMLAttributes,
  type ReactNode,
  type TextareaHTMLAttributes,
  useId,
  useState,
} from 'react';
import { Icon } from '../icons/Icon.tsx';
import { Button } from './Button.tsx';
import styles from './ui.module.css';

const cx = (...c: (string | false | undefined)[]) => c.filter(Boolean).join(' ');

// ---- Chip ----------------------------------------------------------------

export function Chip({
  tone = 'plain',
  children,
}: {
  tone?: 'plain' | 'azure' | 'yellow' | 'danger';
  children: ReactNode;
}) {
  return <span className={cx(styles.chip, tone !== 'plain' && styles[`chip-${tone}`])}>{children}</span>;
}

// ---- Field ---------------------------------------------------------------

interface FieldShared {
  label: string;
  help?: ReactNode;
  error?: string | null;
}

/** A labelled text input with optional help and error text, wired up for screen readers. */
export function Field({
  label,
  help,
  error,
  type = 'text',
  ...input
}: FieldShared & InputHTMLAttributes<HTMLInputElement>) {
  const id = useId();
  const [shown, setShown] = useState(false);
  const describedBy = [help && `${id}-help`, error && `${id}-error`].filter(Boolean).join(' ') || undefined;
  const isPassword = type === 'password';
  return (
    <div className={styles.field}>
      <label className={styles.fieldLabel} htmlFor={id}>
        {label}
      </label>
      <div className={styles.inputWrap}>
        <input
          id={id}
          className={styles.input}
          type={isPassword && shown ? 'text' : type}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          {...input}
        />
        {isPassword && (
          <button
            type="button"
            className={styles.inputAction}
            onClick={() => setShown((s) => !s)}
            aria-label={shown ? 'Hide password' : 'Show password'}
            aria-pressed={shown}
          >
            <Icon name={shown ? 'eyeOff' : 'eye'} size={18} />
          </button>
        )}
      </div>
      {help && (
        <span id={`${id}-help`} className={styles.help}>
          {help}
        </span>
      )}
      {error && (
        <span id={`${id}-error`} className={styles.error} role="alert">
          {error}
        </span>
      )}
    </div>
  );
}

export function TextArea({
  label,
  help,
  error,
  ...input
}: FieldShared & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const id = useId();
  const describedBy = [help && `${id}-help`, error && `${id}-error`].filter(Boolean).join(' ') || undefined;
  return (
    <div className={styles.field}>
      <label className={styles.fieldLabel} htmlFor={id}>
        {label}
      </label>
      <textarea
        id={id}
        className={styles.input}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        {...input}
      />
      {help && (
        <span id={`${id}-help`} className={styles.help}>
          {help}
        </span>
      )}
      {error && (
        <span id={`${id}-error`} className={styles.error} role="alert">
          {error}
        </span>
      )}
    </div>
  );
}

// ---- Choice groups -------------------------------------------------------

interface ChoiceProps<T extends string> {
  /** Accessible name of the group. */
  label: string;
  options: readonly { value: T; label: string }[];
  value: T | null;
  onChange: (value: T) => void;
}

/** One choice from a few, as connected segments (real radio inputs underneath). */
export function Segmented<T extends string>({
  label,
  options,
  value,
  onChange,
  block = false,
}: ChoiceProps<T> & { block?: boolean }) {
  const name = useId();
  return (
    <fieldset className={cx(styles.segmented, block && styles.segmentedBlock)}>
      <legend className="visually-hidden">{label}</legend>
      {options.map((o) => (
        <label key={o.value} className={styles.segment}>
          <input
            type="radio"
            name={name}
            value={o.value}
            checked={value === o.value}
            onChange={() => onChange(o.value)}
            className="visually-hidden"
          />
          {o.label}
        </label>
      ))}
    </fieldset>
  );
}

/** One choice from a few, as separate pills (real radio inputs underneath). */
export function Pills<T extends string>({ label, options, value, onChange }: ChoiceProps<T>) {
  const name = useId();
  return (
    <fieldset className={styles.pills}>
      <legend className="visually-hidden">{label}</legend>
      {options.map((o) => (
        <label key={o.value} className={styles.pill}>
          <input
            type="radio"
            name={name}
            value={o.value}
            checked={value === o.value}
            onChange={() => onChange(o.value)}
            className="visually-hidden"
          />
          {o.label}
        </label>
      ))}
    </fieldset>
  );
}

/** An on/off setting with a label and optional explanation (a checkbox underneath). */
export function Switch({
  label,
  description,
  checked,
  onChange,
  disabled,
}: {
  label: string;
  description?: ReactNode;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <label className={styles.switch}>
      <input
        type="checkbox"
        role="switch"
        aria-checked={checked}
        className="visually-hidden"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className={styles.switchTrack} aria-hidden="true" />
      <span>
        <span className="display" style={{ fontWeight: 600, fontSize: '0.9375rem' }}>
          {label}
        </span>
        {description && (
          <span className={styles.help} style={{ display: 'block' }}>
            {description}
          </span>
        )}
      </span>
    </label>
  );
}

// ---- Status --------------------------------------------------------------

export function Loading({ label = 'Loading' }: { label?: string }) {
  return (
    <div className={styles.status} role="status">
      <span className={styles.spinner} aria-hidden="true" />
      <span className="visually-hidden">{label}</span>
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof Error ? error.message : 'Something went wrong.';
  return (
    <div className={styles.status} role="alert">
      <span className={styles.statusTitle}>Couldn't load this</span>
      <span>{message}</span>
      {onRetry && (
        <Button variant="ghost" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className={styles.status}>
      <span className={styles.statusTitle}>{title}</span>
      {children}
    </div>
  );
}

export function SectionHeading({ children, id }: { children: ReactNode; id?: string }) {
  return (
    <h2 id={id} className={cx('label', styles.section)}>
      {children}
    </h2>
  );
}
