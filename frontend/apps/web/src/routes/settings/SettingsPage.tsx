import { useQueryClient } from '@tanstack/react-query';
import { useMe } from '@tricklens/api';
import { useNavigate } from 'react-router';
import { useAuth } from '../../app/auth.tsx';
import { Button } from '../../components/ui/Button.tsx';
import { apiMode } from '../../env.ts';
import styles from './SettingsPage.module.css';
import { ThemePicker } from './ThemePicker.tsx';

export function SettingsPage() {
  const { data: me, isPending } = useMe();
  const { signOut } = useAuth();
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const logOut = () => {
    signOut();
    queryClient.clear();
    navigate('/login', { replace: true });
  };

  return (
    <div className={styles.page}>
      <h1 className={styles.title}>Settings</h1>

      <section className={styles.card} aria-labelledby="appearance">
        <h2 id="appearance" className={styles.heading}>
          Appearance
        </h2>
        <p className={styles.lead}>Pick a theme. It's saved on this device.</p>
        <ThemePicker />
      </section>

      <section className={styles.card} aria-labelledby="account">
        <h2 id="account" className={styles.heading}>
          Account
        </h2>
        <dl className={styles.rows}>
          <div className={styles.row}>
            <dt>Email</dt>
            <dd>{isPending ? '…' : (me?.email ?? '–')}</dd>
          </div>
          <div className={styles.row}>
            <dt>Username</dt>
            <dd>{isPending ? '…' : `@${me?.username ?? ''}`}</dd>
          </div>
        </dl>
        <div className={styles.actions}>
          <Button variant="ghost-danger" onClick={logOut}>
            Log out
          </Button>
        </div>
      </section>

      <section className={`${styles.card} ${styles.about}`} aria-label="About">
        <span className={styles.heading}>About TrickLens</span>
        <span className="mono muted">prototype · {apiMode === 'mock' ? 'sample data' : 'live API'}</span>
      </section>
    </div>
  );
}
