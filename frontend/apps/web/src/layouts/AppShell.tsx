import { useMe } from '@tricklens/api';
import { Link, NavLink, Outlet } from 'react-router';
import { Icon, type IconName } from '../components/icons/Icon.tsx';
import { Avatar } from '../components/ui/Avatar.tsx';
import { Logo } from '../components/ui/Logo.tsx';
import styles from './AppShell.module.css';

const NAV: { to: string; label: string; icon: IconName }[] = [
  { to: '/feed', label: 'Feed', icon: 'feed' },
  { to: '/discover', label: 'Discover', icon: 'discover' },
  { to: '/upload', label: 'Upload', icon: 'plus' },
  { to: '/teams', label: 'Teams', icon: 'teams' },
  { to: '/profile', label: 'Profile', icon: 'user' },
];

const navClass = ({ isActive }: { isActive: boolean }) =>
  `${styles.navItem} ${isActive ? styles.active : ''}`;
const tabClass = ({ isActive }: { isActive: boolean }) => `${styles.tab} ${isActive ? styles.active : ''}`;

/**
 * The signed-in frame around every page. One component, two layouts by
 * width (docs/components/frontend.md, Responsive layout): desktop gets the
 * top nav, phones get a slim top bar and the bottom tab bar.
 */
export function AppShell() {
  const { data: me } = useMe();
  const name = me?.display_name ?? me?.username ?? '';

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <Link to="/feed" className={styles.brand} aria-label="TrickLens home">
          <Logo />
        </Link>

        <nav className={styles.nav} aria-label="Main">
          {NAV.map((item) => (
            <NavLink key={item.to} to={item.to} className={navClass}>
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className={styles.account}>
          <NavLink to="/settings" className={navClass} aria-label="Settings">
            <Icon name="gear" />
          </NavLink>
          {me ? (
            <Link to="/profile" className={styles.me}>
              <Avatar name={name} src={me.avatar_url} size={2.125} />
              <span className={`mono ${styles.handle}`}>@{me.username}</span>
            </Link>
          ) : (
            <span className={styles.mePlaceholder} aria-hidden="true" />
          )}
        </div>
      </header>

      <main className={styles.main}>
        <Outlet />
      </main>

      <nav className={styles.tabs} aria-label="Main">
        {NAV.map((item) =>
          item.to === '/upload' ? (
            <NavLink key={item.to} to={item.to} className={styles.uploadTab} aria-label="Upload a clip">
              <span className={styles.uploadButton}>
                <Icon name="plus" size={22} strokeWidth={2.75} />
              </span>
            </NavLink>
          ) : (
            <NavLink key={item.to} to={item.to} className={tabClass}>
              <span className={styles.tabIcon}>
                <Icon name={item.icon} />
              </span>
              <span>{item.label}</span>
            </NavLink>
          ),
        )}
      </nav>
    </div>
  );
}
