import { ApiError, type UserBrief, useApi, useCreateTeam, useMe } from '@tricklens/api';
import { type FormEvent, useState } from 'react';
import { useNavigate } from 'react-router';
import { TeamMark } from '../../components/clip/People.tsx';
import { Icon } from '../../components/icons/Icon.tsx';
import { Avatar } from '../../components/ui/Avatar.tsx';
import { Button } from '../../components/ui/Button.tsx';
import { Chip, Field } from '../../components/ui/controls.tsx';
import page from '../page.module.css';
import {
  basicsErrors,
  levelLabel,
  policyLabel,
  slugFrom,
  type TeamBasics,
  TeamFields,
} from './TeamFields.tsx';
import styles from './teams.module.css';

const MIN_FOUNDERS = 2; // TEAM_MIN_FOUNDING_INVITES in the API
const STEP_TITLES = ['Basics', 'Invite founding members', 'Review your team'] as const;

/** /teams/new: basics, founding invites, review. The team goes live once every founder accepts. */
export function CreateTeamPage() {
  const api = useApi();
  const navigate = useNavigate();
  const create = useCreateTeam();
  const { data: me } = useMe();
  const [step, setStep] = useState(0);
  const [basics, setBasics] = useState<TeamBasics>({
    name: '',
    slug: '',
    description: '',
    level: 'intermediate',
    join_policy: 'request',
  });
  const [slugEdited, setSlugEdited] = useState(false);
  // The step whose Continue was last pressed: its errors show, later steps' don't yet.
  const [attempted, setAttempted] = useState(-1);
  const [founders, setFounders] = useState<UserBrief[]>([]);
  const [handle, setHandle] = useState('');
  const [lookup, setLookup] = useState<{ busy: boolean; error: string | null }>({ busy: false, error: null });
  const [slugTaken, setSlugTaken] = useState<string | null>(null);

  const errors = attempted >= 0 ? basicsErrors(basics, true) : {};
  if (slugTaken && basics.slug === slugTaken) errors.slug = 'That address is taken. Try another.';

  const onBasics = (v: TeamBasics) => setBasics(slugEdited ? v : { ...v, slug: slugFrom(v.name) });

  // There's no user search in the API, so founders are added by exact username and checked.
  const addFounder = async (e: FormEvent) => {
    e.preventDefault();
    const username = handle.trim().replace(/^@/, '').toLowerCase();
    if (!username) return;
    if (username === me?.username)
      return setLookup({ busy: false, error: "You're the owner; invite others." });
    if (founders.some((f) => f.username === username))
      return setLookup({ busy: false, error: 'Already added.' });
    setLookup({ busy: true, error: null });
    const res = await api.GET('/users/{username}', { params: { path: { username } } });
    if (res.data) {
      const u = res.data;
      setFounders([
        ...founders,
        { id: u.id, username: u.username, display_name: u.display_name, avatar_url: u.avatar_url },
      ]);
      setHandle('');
      setLookup({ busy: false, error: null });
    } else {
      setLookup({
        busy: false,
        error:
          res.response.status === 404 ? `No skater called @${username}.` : "Couldn't check that username.",
      });
    }
  };

  const next = () => {
    setAttempted(step);
    if (step === 0 && Object.keys(basicsErrors(basics, true)).length) return;
    if (step === 1 && founders.length < MIN_FOUNDERS) return;
    setStep(step + 1);
  };

  const submit = () =>
    create.mutate(
      {
        name: basics.name.trim(),
        slug: basics.slug,
        description: basics.description.trim() || null,
        level: basics.level,
        join_policy: basics.join_policy,
        invitee_usernames: founders.map((f) => f.username),
      },
      {
        onSuccess: (team) => navigate(`/t/${team.slug}`),
        onError: (err) => {
          if (err instanceof ApiError && err.status === 409) {
            setSlugTaken(basics.slug);
            setStep(0);
          }
        },
      },
    );

  return (
    <div className={`${page.page} ${styles.narrow}`}>
      <p className="label">
        Create a team · step {step + 1} of {STEP_TITLES.length}
      </p>
      <ol className={styles.steps} aria-hidden="true">
        {STEP_TITLES.map((t, i) => (
          <li key={t} className={i <= step ? styles.reached : ''} />
        ))}
      </ol>
      <h1 className={page.title}>{STEP_TITLES[step]}</h1>
      <div style={{ marginTop: '1.5rem' }}>
        {step === 0 && (
          <TeamFields
            value={basics}
            onChange={onBasics}
            errors={errors}
            slugEditable
            onSlugEdited={() => setSlugEdited(true)}
          />
        )}

        {step === 1 && (
          <>
            <p className="muted">
              Pick at least {MIN_FOUNDERS} people to found {basics.name || 'the team'} with you. It goes live
              only when everyone you invite accepts, and if anyone declines, the team is cancelled.
            </p>
            <form className={styles.addRow} onSubmit={addFounder} style={{ marginTop: '1rem' }}>
              <Field
                label="Username"
                value={handle}
                autoCapitalize="none"
                placeholder="@marcosandoval"
                onChange={(e) => setHandle(e.target.value)}
                error={lookup.error}
              />
              <Button type="submit" variant="ghost" disabled={lookup.busy || !handle.trim()}>
                Add
              </Button>
            </form>
            <ul className={styles.people} aria-label="Founding members">
              {founders.map((f) => (
                <li key={f.id} className={styles.person}>
                  <Avatar name={f.display_name ?? f.username} src={f.avatar_url} />
                  <span className={styles.personText}>
                    <span className={styles.personName}>{f.display_name ?? f.username}</span>
                    <span className="mono muted">@{f.username}</span>
                  </span>
                  <button
                    type="button"
                    className={styles.iconButton}
                    onClick={() => setFounders(founders.filter((x) => x.id !== f.id))}
                    aria-label={`Remove @${f.username}`}
                  >
                    <Icon name="close" size={16} />
                  </button>
                </li>
              ))}
            </ul>
            <p style={{ marginTop: '0.75rem' }}>
              <Chip tone={founders.length >= MIN_FOUNDERS ? 'azure' : 'plain'}>
                {founders.length} added · {MIN_FOUNDERS} minimum
              </Chip>
            </p>
          </>
        )}

        {step === 2 && (
          <div className={styles.fields}>
            <div className={styles.summary}>
              <div className={styles.summaryHead}>
                <TeamMark name={basics.name} size={3.25} />
                <div>
                  <div className={styles.teamName}>{basics.name}</div>
                  <div className="mono muted">tricklens.app/t/{basics.slug}</div>
                </div>
              </div>
              <div className={styles.chips}>
                <Chip tone="azure">{levelLabel(basics.level)}</Chip>
                <Chip>{policyLabel(basics.join_policy)}</Chip>
              </div>
              {basics.description && <p className="muted">{basics.description}</p>}
            </div>
            <ul className={styles.people} aria-label="Founding members">
              {me && (
                <li className={styles.person}>
                  <Avatar name={me.display_name ?? me.username} src={me.avatar_url} />
                  <span className={styles.personText}>
                    <span className={styles.personName}>{me.display_name ?? me.username}</span>
                    <span className="mono muted">@{me.username}</span>
                  </span>
                  <Chip tone="yellow">You · owner</Chip>
                </li>
              )}
              {founders.map((f) => (
                <li key={f.id} className={styles.person}>
                  <Avatar name={f.display_name ?? f.username} src={f.avatar_url} />
                  <span className={styles.personText}>
                    <span className={styles.personName}>{f.display_name ?? f.username}</span>
                    <span className="mono muted">@{f.username}</span>
                  </span>
                  <Chip>Invited</Chip>
                </li>
              ))}
            </ul>
            <p className={styles.note}>
              Nothing is public yet. Each founder gets an invite, and the team goes live once everyone says
              yes.
            </p>
            {create.isError && !(create.error instanceof ApiError && create.error.status === 409) && (
              <p className={styles.error} role="alert">
                Couldn't create the team: {create.error.message}
              </p>
            )}
          </div>
        )}
      </div>

      {step === 1 && attempted === 1 && founders.length < MIN_FOUNDERS && (
        <p className={styles.error} role="alert" style={{ marginTop: '1rem' }}>
          Add at least {MIN_FOUNDERS} founding members.
        </p>
      )}
      <div className={styles.footer}>
        {step === 0 ? (
          <Button variant="ghost" onClick={() => navigate('/teams')}>
            Cancel
          </Button>
        ) : (
          <Button variant="ghost" onClick={() => setStep(step - 1)}>
            ← Back
          </Button>
        )}
        {step < 2 ? (
          <Button onClick={next}>Continue</Button>
        ) : (
          <Button onClick={submit} disabled={create.isPending}>
            {create.isPending ? 'Creating…' : 'Create team'}
          </Button>
        )}
      </div>
    </div>
  );
}
