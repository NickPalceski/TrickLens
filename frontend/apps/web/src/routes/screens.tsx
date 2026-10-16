// Every signed-in screen that phase 2/3 replaces with the real thing. Each
// points at its artboards on the design canvas.
import { Link, useParams } from 'react-router';
import styles from './Placeholder.module.css';
import { Placeholder } from './Placeholder.tsx';

export const FeedPage = () => (
  <Placeholder
    title="Feed"
    summary="New clips from skaters and teams you follow, with the steeze breakdown and comments."
    phase={2}
    artboards={['Home Feed', 'Phone — Home Feed', 'Phone — Comments Sheet']}
  />
);

export const DiscoverPage = () => (
  <Placeholder
    title="Discover"
    summary="This week's top clips by score or activity, and the teams rising fastest."
    phase={2}
    artboards={['Discover', 'Phone — Discover · Clips', 'Phone — Discover · Teams']}
  />
);

export const UploadPage = () => (
  <Placeholder
    title="Upload a clip"
    summary="Pick a clip, tag the trick, and follow it through analysis to publishing."
    phase={3}
    artboards={['Upload Clip', 'Clip Status', 'Clip Review']}
  />
);

export const ClipPage = () => {
  const { clipId } = useParams();
  return (
    <Placeholder
      title="Clip"
      summary={`Clip ${clipId ?? ''}: the video, the score breakdown per landed trick, likes and comments.`}
      phase={2}
      artboards={['Clip Detail', 'Clip Detail — Multi-Trick Line']}
    />
  );
};

export const ProfilePage = () => (
  <Placeholder
    title="Your profile"
    summary="Your clips, setup, followers and average steeze."
    phase={2}
    artboards={['Profile — View', 'Phone — Profile']}
  />
);

export const ProfileEditPage = () => (
  <Placeholder
    title="Edit profile"
    summary="Name, bio, photo and setup."
    phase={2}
    artboards={['Profile — Edit']}
  />
);

export const SkaterPage = () => {
  const { username } = useParams();
  return (
    <Placeholder
      title={`@${username ?? ''}`}
      summary="Another skater's profile, with Follow."
      phase={2}
      artboards={['Profile — Another Skater']}
    />
  );
};

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
