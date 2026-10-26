import type { ClipOut } from '@tricklens/api';
import { Icon } from '../icons/Icon.tsx';
import { Chip } from '../ui/controls.tsx';
import styles from './FailureCard.module.css';

/** What to try next, by failure reason (backend app/analyzer/reasons.py and media.py). */
export const TIPS: Record<string, string> = {
  'no landed trick detected': 'Keep the board and both feet in frame through the landing.',
  'no clean airtime found': 'Make sure the pop and the board leaving the ground are in the shot.',
  'trick left the frame': 'Keep the whole trick in the shot, from pop to roll-away.',
  'skater too far from camera': 'Get closer or zoom in so you fill more of the frame.',
  'body not clearly visible': "Keep your whole body in view and don't film straight into the sun.",
  'clip ends too soon after the landing': 'Keep filming for about a second after you roll away.',
  'too dark': 'Film in daylight or under a strong light.',
  'unreadable video file': 'Re-export the clip as MP4 or MOV and upload it again.',
  'no video stream found': 'Re-export the clip as MP4 or MOV and upload it again.',
  'clip too short': 'Upload a clip that is at least a couple of seconds long.',
  'analysis failed': "That one's on us. Upload the clip again.",
};

/** Why a clip couldn't be scored, and what to change for the next take. */
export function FailureCard({ clip }: { clip: ClipOut }) {
  const reason = clip.analysis?.failure_reason;
  return (
    <section className={styles.card} aria-labelledby="failed-title">
      <Chip tone="danger">
        <Icon name="alert" size={12} strokeWidth={2.5} /> Couldn't score
      </Chip>
      <h2 id="failed-title" className={styles.title}>
        {reason ? reason[0]?.toUpperCase() + reason.slice(1) : "We couldn't score this clip"}
      </h2>
      {reason && TIPS[reason] && <p>{TIPS[reason]}</p>}
      <p className={styles.note}>A clip without a score can't be published. It stays private to you.</p>
    </section>
  );
}
