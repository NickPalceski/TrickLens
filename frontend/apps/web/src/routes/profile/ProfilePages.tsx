import { type ProfileFields, useMe, useUpdateMe, useUser } from '@tricklens/api';
import { type FormEvent, useState } from 'react';
import { Navigate, useNavigate, useParams } from 'react-router';
import { Avatar } from '../../components/ui/Avatar.tsx';
import { Button } from '../../components/ui/Button.tsx';
import { ErrorState, Field, Loading, Segmented, TextArea } from '../../components/ui/controls.tsx';
import page from '../page.module.css';
import styles from './ProfilePages.module.css';
import { ProfileView } from './ProfileView.tsx';

/** /profile: the signed-in skater. */
export function ProfilePage() {
  const me = useMe();
  if (me.isPending) return <Loading label="Loading your profile" />;
  if (me.isError) return <ErrorState error={me.error} onRetry={() => void me.refetch()} />;
  return <ProfileView user={me.data} own />;
}

/** /u/:username: anyone. Your own username goes to /profile. */
export function SkaterPage() {
  const { username = '' } = useParams();
  const me = useMe();
  const user = useUser(username);
  if (me.data?.username === username) return <Navigate to="/profile" replace />;
  if (user.isPending) return <Loading label="Loading profile" />;
  if (user.isError) {
    return (
      <div className={page.page}>
        <ErrorState error={user.error} onRetry={() => void user.refetch()} />
      </div>
    );
  }
  return <ProfileView user={user.data} own={false} />;
}

const STANCES = [
  { value: 'regular', label: 'Regular' },
  { value: 'goofy', label: 'Goofy' },
] as const;
const STYLES = [
  { value: 'vert', label: 'Vert' },
  { value: 'street', label: 'Street' },
  { value: 'mix', label: 'Mix' },
] as const;

type Form = {
  display_name: string;
  bio: string;
  stance: 'regular' | 'goofy' | null;
  style: 'vert' | 'street' | 'mix' | null;
  board: string;
  board_size: string;
  wheels: string;
  wheel_size: string;
  trucks: string;
  bearings: string;
};

const blankToNull = (s: string) => (s.trim() ? s.trim() : null);

/** Limits from the API's ProfileUpdate schema. */
function validate(f: Form): Partial<Record<keyof Form, string>> {
  const e: Partial<Record<keyof Form, string>> = {};
  if (f.board_size && !(Number(f.board_size) >= 6 && Number(f.board_size) <= 12))
    e.board_size = 'Between 6 and 12 inches.';
  if (
    f.wheel_size &&
    !(/^\d+$/.test(f.wheel_size) && Number(f.wheel_size) >= 40 && Number(f.wheel_size) <= 80)
  ) {
    e.wheel_size = 'A whole number from 40 to 80 mm.';
  }
  return e;
}

function EditForm({ me }: { me: NonNullable<ReturnType<typeof useMe>['data']> }) {
  const save = useUpdateMe();
  const navigate = useNavigate();
  const p = me.profile;
  const [f, setF] = useState<Form>({
    display_name: me.display_name ?? '',
    bio: me.bio ?? '',
    stance: p?.stance ?? null,
    style: p?.style ?? null,
    board: p?.board ?? '',
    board_size: p?.board_size ?? '',
    wheels: p?.wheels ?? '',
    wheel_size: p?.wheel_size ? String(p.wheel_size) : '',
    trucks: p?.trucks ?? '',
    bearings: p?.bearings ?? '',
  });
  const [touched, setTouched] = useState(false);
  const errors = touched ? validate(f) : {};
  const set = (k: keyof Form) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (Object.keys(validate(f)).length) return;
    const profile: ProfileFields = {
      stance: f.stance,
      style: f.style,
      board: blankToNull(f.board),
      board_size: f.board_size ? Number(f.board_size) : null,
      wheels: blankToNull(f.wheels),
      wheel_size: f.wheel_size ? Number(f.wheel_size) : null,
      trucks: blankToNull(f.trucks),
      bearings: blankToNull(f.bearings),
    };
    save.mutate(
      { user: { display_name: blankToNull(f.display_name), bio: blankToNull(f.bio) }, profile },
      { onSuccess: () => navigate('/profile') },
    );
  };

  return (
    <form className={`${page.page} ${styles.page}`} onSubmit={submit} noValidate>
      <div className={styles.head}>
        <h1 className={page.title}>Edit profile</h1>
        <div className={styles.headButtons}>
          <Button variant="ghost" onClick={() => navigate('/profile')}>
            Cancel
          </Button>
          <Button type="submit" disabled={save.isPending}>
            {save.isPending ? 'Saving…' : 'Save changes'}
          </Button>
        </div>
      </div>
      {save.isError && (
        <p className={styles.error} role="alert">
          Couldn't save: {save.error.message}
        </p>
      )}
      <div className={styles.columns}>
        <section className={`${page.card} ${styles.card}`} aria-label="About you">
          <div className={styles.photo}>
            <Avatar name={me.display_name ?? me.username} src={me.avatar_url} size={4.5} />
            <p className={page.note}>Photo uploads aren't available yet.</p>
          </div>
          <Field label="Username" value={me.username} readOnly help="Usernames can't be changed yet." />
          <Field label="Display name" value={f.display_name} onChange={set('display_name')} maxLength={60} />
          <TextArea label="Bio" value={f.bio} onChange={set('bio')} maxLength={2000} rows={3} />
        </section>
        <section className={`${page.card} ${styles.card}`} aria-labelledby="setup-edit-title">
          <h2 id="setup-edit-title" className={styles.cardTitle}>
            Setup
          </h2>
          <div className={styles.choice}>
            <span className={styles.choiceLabel}>Stance</span>
            <Segmented
              label="Stance"
              options={STANCES}
              value={f.stance}
              onChange={(v) => setF({ ...f, stance: v })}
              block
            />
          </div>
          <div className={styles.choice}>
            <span className={styles.choiceLabel}>Style</span>
            <Segmented
              label="Style"
              options={STYLES}
              value={f.style}
              onChange={(v) => setF({ ...f, style: v })}
              block
            />
          </div>
          <div className={styles.pairs}>
            <Field
              label="Board"
              value={f.board}
              onChange={set('board')}
              maxLength={80}
              placeholder="Baker B1"
            />
            <Field
              label="Board width (in)"
              value={f.board_size}
              onChange={set('board_size')}
              inputMode="decimal"
              placeholder="8.0"
              error={errors.board_size}
            />
            <Field
              label="Wheels"
              value={f.wheels}
              onChange={set('wheels')}
              maxLength={80}
              placeholder="Spitfire F4"
            />
            <Field
              label="Wheel size (mm)"
              value={f.wheel_size}
              onChange={set('wheel_size')}
              inputMode="numeric"
              placeholder="54"
              error={errors.wheel_size}
            />
            <Field label="Trucks" value={f.trucks} onChange={set('trucks')} maxLength={80} />
            <Field label="Bearings" value={f.bearings} onChange={set('bearings')} maxLength={80} />
          </div>
        </section>
      </div>
    </form>
  );
}

/** /profile/edit */
export function ProfileEditPage() {
  const me = useMe();
  if (me.isPending) return <Loading label="Loading your profile" />;
  if (me.isError) return <ErrorState error={me.error} onRetry={() => void me.refetch()} />;
  return <EditForm me={me.data} />;
}
