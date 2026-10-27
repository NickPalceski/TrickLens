import { type TeamOut, useDeleteTeam, useTeam, useUpdateTeam } from '@tricklens/api';
import { type FormEvent, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { Button } from '../../components/ui/Button.tsx';
import { ErrorState, Field, Loading } from '../../components/ui/controls.tsx';
import page from '../page.module.css';
import { basicsErrors, type TeamBasics, TeamFields } from './TeamFields.tsx';
import styles from './teams.module.css';

function SettingsForm({ team }: { team: TeamOut }) {
  const navigate = useNavigate();
  const update = useUpdateTeam(team.slug);
  const remove = useDeleteTeam(team.slug);
  const [v, setV] = useState<TeamBasics>({
    name: team.name,
    slug: team.slug,
    description: team.description ?? '',
    level: team.level,
    join_policy: team.join_policy,
  });
  const [touched, setTouched] = useState(false);
  const [confirmName, setConfirmName] = useState('');
  const errors = touched ? basicsErrors(v, false) : {};

  const save = (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (Object.keys(basicsErrors(v, false)).length) return;
    update.mutate(
      {
        name: v.name.trim(),
        description: v.description.trim() || null,
        level: v.level,
        join_policy: v.join_policy,
      },
      { onSuccess: () => navigate(`/t/${team.slug}`) },
    );
  };

  return (
    <div className={`${page.page} ${styles.narrow}`}>
      <p className="label">{team.name}</p>
      <form onSubmit={save} noValidate>
        <div className={page.head} style={{ marginTop: '0.375rem' }}>
          <h1 className={page.title}>Team settings</h1>
          <div className={styles.actions}>
            <Link to={`/t/${team.slug}`} className={styles.linkButton}>
              Cancel
            </Link>
            <Button type="submit" disabled={update.isPending}>
              {update.isPending ? 'Saving…' : 'Save changes'}
            </Button>
          </div>
        </div>
        {update.isError && (
          <p className={styles.error} role="alert">
            Couldn't save: {update.error.message}
          </p>
        )}
        <TeamFields value={v} onChange={setV} errors={errors} slugEditable={false} />
      </form>

      <section className={styles.dangerZone} style={{ marginTop: '2rem' }} aria-labelledby="danger-title">
        <h2 id="danger-title" className={styles.dangerTitle}>
          Delete {team.name}
        </h2>
        <p>
          This removes the team for all {team.member_count} members and can't be undone. Clips tagged to it
          stay up without a team. There's no ownership transfer, so deleting is the only way for an owner to
          step away.
        </p>
        <Field
          label={`Type ${team.name} to confirm`}
          value={confirmName}
          onChange={(e) => setConfirmName(e.target.value)}
          autoComplete="off"
        />
        {remove.isError && (
          <p className={styles.error} role="alert">
            Couldn't delete: {remove.error.message}
          </p>
        )}
        <Button
          variant="danger"
          disabled={confirmName.trim() !== team.name || remove.isPending}
          onClick={() => remove.mutate(undefined, { onSuccess: () => navigate('/teams') })}
        >
          Delete team
        </Button>
      </section>
    </div>
  );
}

/** /t/:slug/settings: owner only. */
export function TeamSettingsPage() {
  const { slug = '' } = useParams();
  const team = useTeam(slug);
  if (team.isPending) return <Loading label="Loading team" />;
  if (team.isError) return <ErrorState error={team.error} onRetry={() => void team.refetch()} />;
  if (team.data.my_role !== 'owner') {
    return (
      <div className={page.page}>
        <ErrorState error={new Error("Only the team's owner can change its settings.")} />
      </div>
    );
  }
  return <SettingsForm team={team.data} />;
}
