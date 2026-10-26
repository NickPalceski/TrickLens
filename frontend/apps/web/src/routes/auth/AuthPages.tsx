import { useRegister } from '@tricklens/api';
import { type FormEvent, type ReactNode, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router';
import { AuthError, PASSWORD_RULES, useAuth } from '../../app/auth.tsx';
import { SubscoreBars } from '../../components/clip/Score.tsx';
import { Icon } from '../../components/icons/Icon.tsx';
import { Button } from '../../components/ui/Button.tsx';
import { Field } from '../../components/ui/controls.tsx';
import { Logo } from '../../components/ui/Logo.tsx';
import styles from './AuthPages.module.css';

const SAMPLE_BREAKDOWN = {
  pop: 82,
  landing_stability: 74,
  roll_away: 91,
  stomp: 68,
  compactness: 77,
  catch: 82,
};
const USERNAME_RE = /^[a-z0-9_]{3,30}$/; // backend app/schemas/user.py
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** The yellow (light) / brown (dark) brand panel with the headline and a sample score card. */
function Hero({ title, lead }: { title: string; lead: string }) {
  return (
    <section className={styles.hero}>
      <Logo size={32} />
      <div className={styles.heroText}>
        <h1 className={styles.headline}>{title}</h1>
        <p className={styles.lead}>{lead}</p>
      </div>
      <div className={styles.sample} aria-hidden="true">
        <div className={styles.sampleHead}>
          <span className="label">Sample steeze card</span>
          <span className={styles.sampleScore}>79</span>
        </div>
        <SubscoreBars breakdown={SAMPLE_BREAKDOWN} notes={false} tight />
      </div>
    </section>
  );
}

function AuthFrame({
  hero,
  switchTo,
  children,
}: {
  hero: { title: string; lead: string };
  switchTo: { text: string; to: string; label: string };
  children: ReactNode;
}) {
  const location = useLocation();
  return (
    <div className={styles.frame}>
      <Hero {...hero} />
      <div className={styles.formSide}>
        <p className={styles.switch}>
          {switchTo.text}{' '}
          <Link className="link" to={switchTo.to}>
            {switchTo.label}
          </Link>
        </p>
        <div className={styles.formWrap}>
          {children}
          <p className={styles.trouble}>
            Having trouble?{' '}
            <Link className="link" to="/report-bug" state={{ from: location.pathname }}>
              Report a bug
            </Link>
          </p>
        </div>
        <p className={`mono ${styles.foot}`}>© TrickLens · clips in, steeze out</p>
      </div>
    </div>
  );
}

const errorText = (e: unknown) => (e instanceof AuthError ? e.message : 'Something went wrong. Try again.');

export function LoginPage() {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const from = (useLocation().state as { from?: string } | null)?.from ?? '/feed';
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [touched, setTouched] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const emailError = touched && !EMAIL_RE.test(email) ? 'Enter your email address.' : null;
  const passwordError = touched && !password ? 'Enter your password.' : null;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (!EMAIL_RE.test(email) || !password) return;
    setBusy(true);
    setError(null);
    try {
      await signIn(email, password);
      navigate(from, { replace: true });
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthFrame
      hero={{
        title: 'Stick the landing.',
        lead: 'Tag your trick. We score the execution: pop, stomp, roll-away and the rest, broken down and never guessed.',
      }}
      switchTo={{ text: 'New to TrickLens?', to: '/signup', label: 'Create an account' }}
    >
      <h2 className={styles.title}>Log in</h2>
      <p className={styles.sub}>Good to see you again.</p>
      <form className={styles.form} onSubmit={submit} noValidate>
        <Field
          label="Email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          error={emailError}
        />
        <Field
          label="Password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          error={passwordError}
        />
        {error && (
          <p className={styles.formError} role="alert">
            {error}
          </p>
        )}
        <Button type="submit" block disabled={busy}>
          {busy ? 'Logging in…' : 'Log in'}
        </Button>
      </form>
      <p className={styles.note}>
        Prototype: any email and an 8+ character password signs you in as the sample skater.
      </p>
    </AuthFrame>
  );
}

export function SignupPage() {
  const { signUp, confirmSignUp } = useAuth();
  const register = useRegister();
  const navigate = useNavigate();
  const [step, setStep] = useState<'details' | 'confirm'>('details');
  const [form, setForm] = useState({ username: '', email: '', password: '', confirm: '' });
  const [code, setCode] = useState('');
  const [touched, setTouched] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const set = (k: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm({ ...form, [k]: e.target.value });
  const problems = {
    username: USERNAME_RE.test(form.username) ? null : '3 to 30 lowercase letters, digits or underscores.',
    email: EMAIL_RE.test(form.email) ? null : 'Enter a valid email address.',
    password: PASSWORD_RULES.every((r) => r.test(form.password))
      ? null
      : "This password doesn't meet the rules below.",
    confirm: form.confirm === form.password && form.confirm ? null : "The passwords don't match.",
  };

  const submitDetails = async (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (Object.values(problems).some(Boolean)) return;
    setBusy(true);
    setError(null);
    try {
      await signUp({ username: form.username, email: form.email, password: form.password });
      setStep('confirm');
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  const submitCode = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await confirmSignUp(form.email, code.trim());
      // Cognito knows the account now; the API learns about it here (POST /users).
      await register.mutateAsync({ username: form.username });
      navigate('/feed', { replace: true });
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthFrame
      hero={{
        title: 'Pull up.',
        lead: 'Upload clips, tag your own tricks, and get an honest read on the execution. No judges, no guessing.',
      }}
      switchTo={{ text: 'Already have an account?', to: '/login', label: 'Log in' }}
    >
      {step === 'details' ? (
        <>
          <h2 className={styles.title}>Create your account</h2>
          <p className={styles.sub}>Free, and it takes about a minute.</p>
          <form className={styles.form} onSubmit={submitDetails} noValidate>
            <Field
              label="Username"
              autoComplete="username"
              autoCapitalize="none"
              value={form.username}
              onChange={set('username')}
              help="Letters, numbers and underscores. Shown on your clips."
              error={touched ? problems.username : null}
            />
            <Field
              label="Email"
              type="email"
              autoComplete="email"
              value={form.email}
              onChange={set('email')}
              error={touched ? problems.email : null}
            />
            <Field
              label="Password"
              type="password"
              autoComplete="new-password"
              value={form.password}
              onChange={set('password')}
              error={touched ? problems.password : null}
            />
            <ul className={styles.rules} aria-label="Password rules">
              {PASSWORD_RULES.map((r) => {
                const ok = r.test(form.password);
                return (
                  <li key={r.label} className={ok ? styles.ruleOk : ''}>
                    <Icon name={ok ? 'check' : 'close'} size={12} strokeWidth={3} />
                    {r.label}
                    <span className="visually-hidden">{ok ? ': done' : ': not yet'}</span>
                  </li>
                );
              })}
            </ul>
            <Field
              label="Confirm password"
              type="password"
              autoComplete="new-password"
              value={form.confirm}
              onChange={set('confirm')}
              error={touched ? problems.confirm : null}
            />
            {error && (
              <p className={styles.formError} role="alert">
                {error}
              </p>
            )}
            <Button type="submit" block disabled={busy}>
              {busy ? 'Creating…' : 'Create account'}
            </Button>
          </form>
        </>
      ) : (
        <>
          <h2 className={styles.title}>Check your email</h2>
          <p className={styles.sub}>
            We sent a 6-digit code to <b>{form.email}</b>. Enter it to finish creating your account.
          </p>
          <form className={styles.form} onSubmit={submitCode} noValidate>
            <Field
              label="Verification code"
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
            />
            {error && (
              <p className={styles.formError} role="alert">
                {error}
              </p>
            )}
            <Button type="submit" block disabled={busy || code.length !== 6}>
              {busy ? 'Confirming…' : 'Confirm and continue'}
            </Button>
            <button type="button" className={styles.textButton} onClick={() => setStep('details')}>
              Use a different email
            </button>
          </form>
          <p className={styles.note}>Prototype: any 6 digits work.</p>
        </>
      )}
    </AuthFrame>
  );
}
