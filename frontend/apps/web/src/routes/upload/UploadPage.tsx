import {
  type ClipOut,
  formatTimeAgo,
  uploadToStorage,
  useCompleteClip,
  useCreateClip,
  useMyDrafts,
  useTagTricks,
} from '@tricklens/api';
import { type ChangeEvent, type DragEvent, type FormEvent, useEffect, useId, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { trickNames } from '../../components/clip/ClipMedia.tsx';
import { TrickNameInput, TrickSuggestions } from '../../components/clip/TrickNameInput.tsx';
import { Icon } from '../../components/icons/Icon.tsx';
import { Button } from '../../components/ui/Button.tsx';
import { Chip, Pills, SectionHeading, Switch } from '../../components/ui/controls.tsx';
import { apiMode } from '../../env.ts';
import { ACCEPTED_TYPES, MAX_DURATION_MS, readVideoDuration, rememberPreview } from '../../lib/video.ts';
import page from '../page.module.css';
import styles from './UploadPage.module.css';

/** The browser can't read a file's frame rate; the worker replaces this with ffprobe's (backend 6a). */
const ASSUMED_FPS = 30;
const MAX_TAGS = 5; // TagTricksRequest in the API

type Outcome = 'single' | 'line' | 'stepoff' | 'failed';
const OUTCOMES = [
  { value: 'single', label: 'One trick' },
  { value: 'line', label: 'Three-trick line' },
  { value: 'stepoff', label: 'Ends with a step-off' },
  { value: 'failed', label: "Couldn't score" },
] as const;

interface Picked {
  file: File;
  url: string;
  durationMs: number;
}

const statusLabel = (c: ClipOut) =>
  !c.analyze && (c.status === 'queued' || c.status === 'analyzing') ? 'Processing' : STATUS_LABEL[c.status];

const STATUS_LABEL: Record<ClipOut['status'], string> = {
  draft: 'Uploading',
  queued: 'Queued',
  analyzing: 'Analyzing',
  analyzed: 'Ready to publish',
  unanalyzable: "Couldn't score",
  published: 'Published',
};

/** Clips you started and haven't published, so one left mid-analysis isn't lost. */
function InProgress() {
  const drafts = useMyDrafts();
  const items = drafts.data?.items ?? [];
  if (!items.length) return null;
  return (
    <section className={styles.drafts} aria-labelledby="drafts-title">
      <SectionHeading id="drafts-title">In progress</SectionHeading>
      <ul className={styles.draftList}>
        {items.map((c) => (
          <li key={c.id}>
            <Link to={`/upload/${c.id}`} className={styles.draft}>
              <span className={styles.draftName}>{trickNames(c) || 'Untitled clip'}</span>
              <span className="muted">{formatTimeAgo(c.created_at)}</span>
              <Chip
                tone={c.status === 'analyzed' ? 'azure' : c.status === 'unanalyzable' ? 'danger' : 'plain'}
              >
                {statusLabel(c)}
              </Chip>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function UploadPage() {
  const navigate = useNavigate();
  const create = useCreateClip();
  const complete = useCompleteClip();
  const tag = useTagTricks();
  const fileId = useId();
  const recordId = useId();

  const [picked, setPicked] = useState<Picked | null>(null);
  const [pickError, setPickError] = useState<string | null>(null);
  const [analyze, setAnalyze] = useState(true);
  const nextTag = useRef(1);
  const [tags, setTags] = useState<{ id: number; value: string }[]>([{ id: 0, value: '' }]);
  const [outcome, setOutcome] = useState<Outcome>('single');
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [touched, setTouched] = useState(false);
  const busy = progress !== null;

  // Prototype only: tell the simulated worker what this upload turns out to be.
  useEffect(() => {
    if (apiMode !== 'mock') return;
    void import('@tricklens/api/mocks').then((m) => m.setNextMockOutcome(outcome));
  }, [outcome]);

  const pick = async (file: File | undefined) => {
    setPickError(null);
    if (!file) return;
    if (!(ACCEPTED_TYPES as readonly string[]).includes(file.type)) {
      setPickError('Choose an MP4, MOV or WebM video.');
      return;
    }
    try {
      const durationMs = await readVideoDuration(file);
      if (durationMs > MAX_DURATION_MS) {
        setPickError(`That clip is ${Math.round(durationMs / 1000)} seconds. Trim it to 30 seconds or less.`);
        return;
      }
      if (picked) URL.revokeObjectURL(picked.url);
      setPicked({ file, url: URL.createObjectURL(file), durationMs });
    } catch (e) {
      setPickError(e instanceof Error ? e.message : "Couldn't read that file.");
    }
  };

  const onFile = (e: ChangeEvent<HTMLInputElement>) => void pick(e.target.files?.[0]);
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    void pick(e.dataTransfer.files[0]);
  };

  const cleanTags = tags.map((t) => t.value.trim()).filter(Boolean);
  const tagsMissing = !analyze && cleanTags.length === 0;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (!picked || tagsMissing) return;
    setError(null);
    setProgress(0);
    try {
      const { clip, upload_url } = await create.mutateAsync({
        content_type: picked.file.type,
        duration_ms: picked.durationMs,
        source_fps: ASSUMED_FPS,
        analyze,
      });
      await uploadToStorage(upload_url, picked.file, picked.file.type, setProgress);
      rememberPreview(clip.id, picked.file);
      await complete.mutateAsync(clip.id);
      // Analysis off: the names are known now, and the API takes them before
      // the worker has finished preparing the video.
      if (!analyze) await tag.mutateAsync({ clipId: clip.id, tricks: cleanTags.map((name) => ({ name })) });
      navigate(`/upload/${clip.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The upload failed. Try again.');
      setProgress(null);
    }
  };

  return (
    <div className={`${page.page} ${styles.page}`}>
      <div className={page.head}>
        <div>
          <h1 className={page.title}>Upload a clip</h1>
          <p className={page.lead}>Up to 30 seconds. We score the execution; you name the tricks.</p>
        </div>
      </div>

      <form className={styles.layout} onSubmit={submit} noValidate>
        {/* biome-ignore lint/a11y/noStaticElementInteractions: dropping a file is a mouse extra; the Choose and Record buttons inside give keyboard access */}
        <div
          className={`${styles.drop} ${picked ? styles.hasFile : ''}`}
          onDragOver={(e) => e.preventDefault()}
          onDrop={onDrop}
        >
          {picked ? (
            <>
              {/* biome-ignore lint/a11y/useMediaCaption: a preview of your own footage */}
              <video className={styles.preview} src={picked.url} controls playsInline />
              <div className={styles.fileRow}>
                <span className="mono">
                  {picked.file.name} · {(picked.durationMs / 1000).toFixed(1)}s
                </span>
                <label htmlFor={fileId} className={styles.textButton}>
                  Choose another
                </label>
              </div>
            </>
          ) : (
            <>
              <span className={styles.dropIcon}>
                <Icon name="upload" size={26} strokeWidth={2.25} />
              </span>
              <span className={styles.dropTitle}>Drop your clip here</span>
              <span className="muted">MP4, MOV or WebM, up to 30 seconds</span>
              <div className={styles.pickRow}>
                <label htmlFor={fileId} className={styles.pickButton}>
                  Choose a clip
                </label>
                <label htmlFor={recordId} className={`${styles.pickButton} ${styles.record}`}>
                  <Icon name="camera" size={16} /> Record
                </label>
              </div>
            </>
          )}
          <input
            id={fileId}
            type="file"
            accept={ACCEPTED_TYPES.join(',')}
            className="visually-hidden"
            onChange={onFile}
            disabled={busy}
          />
          {/* On phones this opens the camera. */}
          <input
            id={recordId}
            type="file"
            accept="video/*"
            capture="environment"
            className="visually-hidden"
            onChange={onFile}
            disabled={busy}
          />
          {(pickError || (touched && !picked)) && (
            <p className={styles.error} role="alert">
              {pickError ?? 'Choose a clip to upload.'}
            </p>
          )}
        </div>

        <div className={styles.options}>
          <div className={styles.option}>
            <Switch
              label="Analyze the clip"
              description={
                analyze
                  ? "We find each trick and score how you landed it. You'll name the tricks after."
                  : 'No score. Name the tricks now; your clip is ready to post once the video is prepared.'
              }
              checked={analyze}
              onChange={setAnalyze}
              disabled={busy}
            />
          </div>

          {!analyze && (
            <fieldset className={styles.tags}>
              <legend className={styles.legend}>Tricks in this clip</legend>
              <TrickSuggestions />
              {tags.map((t, i) => (
                <div key={t.id} className={styles.tagRow}>
                  <TrickNameInput
                    label={tags.length > 1 ? `Trick ${i + 1}` : 'Trick'}
                    value={t.value}
                    onChange={(e) =>
                      setTags(tags.map((x) => (x.id === t.id ? { ...x, value: e.target.value } : x)))
                    }
                    error={touched && i === 0 && tagsMissing ? 'Name at least one trick.' : null}
                    disabled={busy}
                  />
                  {tags.length > 1 && (
                    <button
                      type="button"
                      className={styles.remove}
                      onClick={() => setTags(tags.filter((x) => x.id !== t.id))}
                      aria-label={`Remove trick ${i + 1}`}
                    >
                      <Icon name="close" size={16} />
                    </button>
                  )}
                </div>
              ))}
              {tags.length < MAX_TAGS && (
                <button
                  type="button"
                  className={styles.textButton}
                  onClick={() => setTags([...tags, { id: nextTag.current++, value: '' }])}
                >
                  + Add another trick
                </button>
              )}
            </fieldset>
          )}

          {analyze && apiMode === 'mock' && (
            <div className={styles.prototype}>
              <span className="label">Prototype: what the analyzer finds</span>
              <Pills
                label="Sample analysis result"
                options={OUTCOMES}
                value={outcome}
                onChange={setOutcome}
              />
            </div>
          )}

          {busy && (
            <div className={styles.progress}>
              <div
                className={styles.bar}
                role="progressbar"
                aria-label="Upload progress"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={Math.round((progress ?? 0) * 100)}
              >
                <div style={{ width: `${Math.round((progress ?? 0) * 100)}%` }} />
              </div>
              <span className="mono muted">{Math.round((progress ?? 0) * 100)}%</span>
            </div>
          )}
          {error && (
            <p className={styles.error} role="alert">
              {error}
            </p>
          )}
          <Button type="submit" block disabled={busy}>
            {busy ? 'Uploading…' : 'Upload clip'}
          </Button>
        </div>
      </form>

      <InProgress />
    </div>
  );
}
