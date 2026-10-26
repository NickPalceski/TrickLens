import { type ClipOut, formatTrickName } from '@tricklens/api';
import { type ReactNode, useEffect, useRef, useState } from 'react';
import { Icon } from '../icons/Icon.tsx';
import styles from './clip.module.css';
import { ScoreSticker } from './Score.tsx';

/** Stick-figure placeholder for clips without a poster frame. */
function Figure() {
  return (
    <svg
      className={styles.figure}
      viewBox="0 0 70 70"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      aria-hidden="true"
    >
      <circle cx="35" cy="16" r="6" />
      <path d="M35 22v18M35 30l-14 10M35 30l14 10M22 55l13-15M48 55l-13-15" />
    </svg>
  );
}

export const trickNames = (clip: ClipOut) =>
  clip.tricks.map((t) => formatTrickName(t.canonical_name)).join(' · ');

interface ClipMediaProps {
  clip: ClipOut;
  aspect?: string;
  /** The yellow score sticker. */
  showScore?: boolean;
  showTrick?: boolean;
  /** Tiles in grids aren't playable in place; they link to the clip. */
  playable?: boolean;
  /** Called once when playback starts (records a view). */
  onPlay?: () => void;
  /** Your own just-uploaded file: shown straight away as a player, instead of `clip.video_url`. */
  src?: string;
  /** Jump to a moment: changing `at` re-seeks even to the same `ms`. */
  seek?: { ms: number; at: number };
  children?: ReactNode;
}

/**
 * The clip's video. Shows the poster frame (or a placeholder) until played.
 * Sample clips in mock mode have no video file, so pressing play explains
 * that instead (docs/components/frontend.md, Mock mode).
 */
export function ClipMedia({
  clip,
  aspect = '4 / 5',
  showScore = true,
  showTrick = true,
  playable = true,
  onPlay,
  src,
  seek,
  children,
}: ClipMediaProps) {
  const [playing, setPlaying] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const url = src ?? clip.video_url;
  const hasVideo = /^(https?|blob):/.test(url);
  const names = trickNames(clip);

  // Seeking starts playback, then jumps once the video can.
  useEffect(() => {
    if (!seek) return;
    setPlaying(true);
    const v = videoRef.current;
    if (!v) return;
    const go = () => {
      v.currentTime = seek.ms / 1000;
      void v.play().catch(() => {});
    };
    if (v.readyState >= 1) go();
    else v.addEventListener('loadedmetadata', go, { once: true });
  }, [seek]);

  return (
    <div className={styles.media} style={{ aspectRatio: aspect }}>
      {src || (playing && hasVideo) ? (
        // biome-ignore lint/a11y/useMediaCaption: skate clips are user footage with no dialogue to caption
        <video
          ref={videoRef}
          src={url}
          poster={clip.thumb_url ?? undefined}
          controls
          autoPlay={!src}
          preload="metadata"
          playsInline
        />
      ) : (
        <>
          {clip.thumb_url ? <img src={clip.thumb_url} alt="" /> : <Figure />}
          {playable && (
            <button
              type="button"
              className={styles.play}
              aria-label={`Play ${names || 'clip'}`}
              onClick={() => {
                setPlaying(true);
                onPlay?.();
              }}
            >
              <span className={styles.playCircle}>
                <Icon name="play" size={18} />
              </span>
            </button>
          )}
          {playing && !hasVideo && (
            <span className={styles.sampleNote} role="status">
              Sample clip: video plays once the app uses the live API
            </span>
          )}
          {showTrick && names && <span className={styles.trickTag}>{names}</span>}
          {showScore && <ScoreSticker score={clip.steeze_score} />}
        </>
      )}
      {children}
    </div>
  );
}
