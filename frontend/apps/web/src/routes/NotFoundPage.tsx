// The not-found page. (Every other screen has its own folder under routes/.)
import { Link } from 'react-router';
import styles from './NotFound.module.css';

export const NotFoundPage = () => (
  <section className={styles.page}>
    <h1 className={styles.title}>Page not found</h1>
    <p className={styles.summary}>There's nothing at this address.</p>
    <p>
      <Link className="link" to="/feed">
        Back to your feed
      </Link>
    </p>
  </section>
);
