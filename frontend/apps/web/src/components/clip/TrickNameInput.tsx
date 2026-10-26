import type { InputHTMLAttributes } from 'react';
import { Field } from '../ui/controls.tsx';

/** Common names, offered as suggestions. Any name is allowed; the API stores what you type. */
const SUGGESTIONS = [
  'Ollie',
  'Nollie',
  'Kickflip',
  'Heelflip',
  'Pop shove-it',
  'FS shove-it',
  'FS 180',
  'BS 180',
  'Varial flip',
  'Varial heelflip',
  'Hardflip',
  'Inward heelflip',
  'Tre flip',
  'Laser flip',
  '360 shove-it',
  'Impossible',
  'Boardslide',
  '50-50 grind',
  '5-0 grind',
  'Nosegrind',
  'Crooked grind',
  'Smith grind',
  'Feeble grind',
  'Manual',
  'Nose manual',
];

const LIST_ID = 'trick-name-suggestions';

/** The suggestion list, rendered once per page that has trick inputs. */
export function TrickSuggestions() {
  return (
    <datalist id={LIST_ID}>
      {SUGGESTIONS.map((s) => (
        <option key={s} value={s} />
      ))}
    </datalist>
  );
}

/** A trick name field (1–60 characters, like the API) with suggestions. */
export function TrickNameInput({
  label,
  error,
  help,
  ...input
}: { label: string; error?: string | null; help?: string } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <Field
      label={label}
      error={error}
      help={help}
      list={LIST_ID}
      maxLength={60}
      autoComplete="off"
      autoCapitalize="none"
      placeholder="e.g. Kickflip"
      {...input}
    />
  );
}
