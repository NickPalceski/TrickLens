import type { JoinPolicy, TeamLevel } from '@tricklens/api';
import { Field, Segmented, TextArea } from '../../components/ui/controls.tsx';
import styles from './teams.module.css';

export const LEVELS = [
  { value: 'beginner', label: 'Beginner' },
  { value: 'intermediate', label: 'Intermediate' },
  { value: 'advanced', label: 'Advanced' },
] as const;

export const POLICIES: { value: JoinPolicy; label: string; description: string }[] = [
  { value: 'open', label: 'Open', description: 'Anyone can join instantly. No approval needed.' },
  {
    value: 'request',
    label: 'Request to join',
    description: 'Anyone can ask to join; an owner or admin approves each request.',
  },
  {
    value: 'invite_only',
    label: 'Invite only',
    description: 'No join button. An owner or admin invites people directly.',
  },
];

export const levelLabel = (l: TeamLevel) => LEVELS.find((x) => x.value === l)?.label ?? l;
export const policyLabel = (p: JoinPolicy) => POLICIES.find((x) => x.value === p)?.label ?? p;

export const SLUG_RE = /^[a-z0-9_]{3,30}$/; // backend app/schemas/team.py

/** A slug suggestion from the team name: "Downtown Skaters" → "downtown_skaters". */
export function slugFrom(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 30);
}

export interface TeamBasics {
  name: string;
  slug: string;
  description: string;
  level: TeamLevel;
  join_policy: JoinPolicy;
}

export function basicsErrors(v: TeamBasics, withSlug: boolean): Partial<Record<keyof TeamBasics, string>> {
  const e: Partial<Record<keyof TeamBasics, string>> = {};
  if (!v.name.trim()) e.name = 'Give the team a name.';
  if (withSlug && !SLUG_RE.test(v.slug)) e.slug = '3 to 30 lowercase letters, digits or underscores.';
  return e;
}

/** Who can join, as cards with an explanation (real radio inputs underneath). */
function PolicyPicker({ value, onChange }: { value: JoinPolicy; onChange: (p: JoinPolicy) => void }) {
  return (
    <fieldset className={styles.policies}>
      <legend className={styles.fieldLabel}>Who can join</legend>
      {POLICIES.map((p) => (
        <label key={p.value} className={styles.policy}>
          <input
            type="radio"
            name="join_policy"
            value={p.value}
            checked={value === p.value}
            onChange={() => onChange(p.value)}
            className="visually-hidden"
          />
          <span className={styles.radio} aria-hidden="true" />
          <span>
            <span className={styles.policyName}>{p.label}</span>
            <span className={styles.policyText}>{p.description}</span>
          </span>
        </label>
      ))}
    </fieldset>
  );
}

/** Name, slug (on create only: it's permanent), description, level and join policy. */
export function TeamFields({
  value,
  onChange,
  errors,
  slugEditable,
  onSlugEdited,
}: {
  value: TeamBasics;
  onChange: (v: TeamBasics) => void;
  errors: Partial<Record<keyof TeamBasics, string>>;
  slugEditable: boolean;
  onSlugEdited?: () => void;
}) {
  const set = <K extends keyof TeamBasics>(k: K, v: TeamBasics[K]) => onChange({ ...value, [k]: v });
  return (
    <div className={styles.fields}>
      <Field
        label="Team name"
        value={value.name}
        maxLength={60}
        onChange={(e) => set('name', e.target.value)}
        error={errors.name}
      />
      {slugEditable ? (
        <Field
          label="Team address"
          value={value.slug}
          maxLength={30}
          autoCapitalize="none"
          onChange={(e) => {
            onSlugEdited?.();
            set('slug', e.target.value.toLowerCase());
          }}
          help={`Your team's address: tricklens.app/t/${value.slug || 'your_team'}. It can't change once the team exists.`}
          error={errors.slug}
        />
      ) : (
        <p className="muted">tricklens.app/t/{value.slug} (a team's address can't change)</p>
      )}
      <TextArea
        label="Description"
        value={value.description}
        maxLength={2000}
        rows={3}
        onChange={(e) => set('description', e.target.value)}
      />
      <div className={styles.choice}>
        <span className={styles.fieldLabel}>Team level</span>
        <Segmented
          label="Team level"
          options={LEVELS}
          value={value.level}
          onChange={(l) => set('level', l)}
          block
        />
        <span className="muted">How skilled the team is as a whole. You can change it later.</span>
      </div>
      <PolicyPicker value={value.join_policy} onChange={(p) => set('join_policy', p)} />
    </div>
  );
}
