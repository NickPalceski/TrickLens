import { Outlet } from 'react-router';
import styles from './AuthLayout.module.css';

/** Frame for the signed-out screens (login, signup): no app nav. */
export function AuthLayout() {
  return (
    <div className={styles.frame}>
      <Outlet />
    </div>
  );
}
