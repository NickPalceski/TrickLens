// Signed-in screens still to build in phase F3, each pointing at its
// artboards on the design canvas, plus the not-found page.
import { Link, useParams } from 'react-router';
import styles from './Placeholder.module.css';
import { Placeholder } from './Placeholder.tsx';

export const UploadPage = () => (
  <Placeholder
    title="Upload a clip"
    summary="Pick a clip, tag the trick, and follow it through analysis to publishing."
    phase={3}
    artboards={['Upload Clip', 'Clip Status', 'Clip Review']}
  />
);

export const TeamsPage = () => (
  <Placeholder
    title="Teams"
    summary="Your teams, invites, and creating a new team."
    phase={3}
    artboards={['Create Team — 1. Basics', 'Team Is Forming']}
  />
);

export const TeamPage = () => {
  const { slug } = useParams();
  return (
    <Placeholder
      title="Team"
      summary={`Team ${slug ?? ''}: members, join requests, and following.`}
      phase={3}
      artboards={["Team Page — Live (Owner's View)", 'Team Settings']}
    />
  );
};

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
