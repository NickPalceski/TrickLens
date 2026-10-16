import { Link, useLocation, useNavigate } from 'react-router';
import { useAuth } from '../../app/auth.tsx';
import { Button } from '../../components/ui/Button.tsx';
import { Logo } from '../../components/ui/Logo.tsx';
import styles from './AuthPages.module.css';

/**
 * Stand-ins until phase 2 builds the real forms (canvas: "Login",
 * "Signup"). The prototype has one sample account, so signing in is a
 * single button.
 */
function DemoSignIn({ title, alt }: { title: string; alt: { text: string; to: string; label: string } }) {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const from = (useLocation().state as { from?: string } | null)?.from ?? '/feed';

  return (
    <div className={styles.wrap}>
      <div className={styles.card}>
        <Logo size={32} />
        <h1 className={styles.title}>{title}</h1>
        <p className="muted">
          The real form arrives in phase 2. For now the prototype runs on sample data with one sample account.
        </p>
        <Button
          block
          onClick={() => {
            signIn();
            navigate(from, { replace: true });
          }}
        >
          Continue as @juliavance
        </Button>
        <p className={styles.alt}>
          {alt.text}{' '}
          <Link className="link" to={alt.to}>
            {alt.label}
          </Link>
        </p>
      </div>
    </div>
  );
}

export const LoginPage = () => (
  <DemoSignIn title="Log in" alt={{ text: 'New to TrickLens?', to: '/signup', label: 'Create an account' }} />
);

export const SignupPage = () => (
  <DemoSignIn
    title="Create your account"
    alt={{ text: 'Already have an account?', to: '/login', label: 'Log in' }}
  />
);
