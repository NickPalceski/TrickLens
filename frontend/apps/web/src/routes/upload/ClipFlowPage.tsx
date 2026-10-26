import {
  type AnalyzedTrick,
  type ClipOut,
  formatClipTime,
  formatTimeAgo,
  formatTrickName,
  SUBSCORES,
  useClipProgress,
  useMyTeams,
  usePublishClip,
} from '@tricklens/api';
import { type FormEvent, useId, useState } from 'react';
import { Link, Navigate, useNavigate, useParams } from 'react-router';
import { ClipMedia } from '../../components/clip/ClipMedia.tsx';
import { FailureCard } from '../../components/clip/FailureCard.tsx';
import { ReportAnalysis } from '../../components/clip/ReportAnalysis.tsx';
import { confidenceLabel, ScoreBlock, SubscoreBars } from '../../components/clip/Score.tsx';
import { type Step, Stepper } from '../../components/clip/Stepper.tsx';
import { TrickBreakdown, TrickTimeline } from '../../components/clip/TrickBreakdown.tsx';
import { TrickNameInput, TrickSuggestions } from '../../components/clip/TrickNameInput.tsx';
import { Button } from '../../components/ui/Button.tsx';
import { Chip, ErrorState, Loading, Switch } from '../../components/ui/controls.tsx';
import { previewUrl } from '../../lib/video.ts';
import page from '../page.module.css';
import styles from './ClipFlowPage.module.css';

const MAX_TAGS = 5; // TagTricksRequest in the API

/** Where the clip is, as steps. Analysis off skips the middle two. */
function stepsFor(clip: ClipOut): Step[] {
  const skipped = clip.status === 'analyzed' && !clip.analysis;
  const order = ['draft', 'queued', 'analyzing', 'analyzed'] as const;
  const at = order.indexOf(clip.status as (typeof order)[number]);
  const step = (label: string, i: number): Step => ({
    label,
    kind: skipped && (i === 1 || i === 2) ? 'skipped' : i < at ? 'done' : i === at ? 'current' : 'upcoming',
  });
  if (clip.status === 'unanalyzable') {
    return [
      { label: 'Upload', kind: 'done' },
      { label: 'Queued', kind: 'done' },
      { label: 'Analyzing', kind: 'done' },
      { label: "Couldn't score", kind: 'failed' },
      { label: 'Published', kind: 'skipped' },
    ];
  }
  return [
    { ...step('Upload', 0), kind: at > 0 ? 'done' : 'current' },
    step('Queued', 1),
    step('Analyzing', 2),
    step('Ready', 3),
    { label: 'Published', kind: 'upcoming' },
  ];
}

function Waiting({ clip }: { clip: ClipOut }) {
  if (clip.status === 'draft') {
    return (
      <section className={`${page.card} ${styles.card}`}>
        <h2 className={styles.cardTitle}>This upload didn't finish</h2>
        <p className="muted">The video never reached us. Upload the clip again to start over.</p>
        <Link to="/upload" className="link">
          Upload it again
        </Link>
      </section>
    );
  }
  return (
    <section className={`${page.card} ${styles.card}`} aria-live="polite">
      <h2 className={styles.cardTitle}>
        {clip.status === 'queued' ? 'Waiting for the analyzer' : 'Analyzing your clip'}
      </h2>
      <p className="muted">
        Usually 30 to 90 seconds. You can leave this page; the clip waits under Upload, In progress.
      </p>
      <p className={styles.measuring}>Measuring {SUBSCORES.map((s) => s.label.toLowerCase()).join(', ')}.</p>
    </section>
  );
}

function outcomeChip(t: AnalyzedTrick) {
  if (t.outcome === 'landed') return <Chip tone="azure">Landed</Chip>;
  if (t.outcome === 'bailed') return <Chip tone="danger">Bailed</Chip>;
  return <Chip>Not judged</Chip>;
}

/** Name the tricks (one per analyzed trick, in order), pick a team, and publish. */
function Review({ clip, onSeek }: { clip: ClipOut; onSeek: (ms: number) => void }) {
  const navigate = useNavigate();
  const teams = useMyTeams();
  const publish = usePublishClip(clip.id);
  const teamId = useId();
  const analyzed = clip.analysis?.tricks ?? [];
  const perTrick = analyzed.length > 0;
  const tagged = clip.tricks.map((t) => formatTrickName(t.canonical_name));

  const [names, setNames] = useState<string[]>(() =>
    perTrick ? analyzed.map((_, i) => tagged[i] ?? '') : tagged.length ? tagged : [''],
  );
  const [team, setTeam] = useState<string>(clip.team?.id ?? '');
  const [included, setIncluded] = useState(clip.score_included);
  const [touched, setTouched] = useState(false);

  const tooMany = names.length > MAX_TAGS;
  const missing = names.map((n) => !n.trim());
  const scored = clip.steeze_score !== null && clip.steeze_score !== undefined;
  const founded = (teams.data ?? []).filter((t) => t.founded);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (tooMany || missing.some(Boolean)) return;
    publish.mutate(
      { tricks: names.map((n) => n.trim()), teamId: team || null, scoreIncluded: included },
      { onSuccess: (c) => navigate(`/clips/${c.id}`) },
    );
  };

  return (
    <div className={styles.review}>
      {scored ? (
        <section className={styles.score} aria-labelledby="score-title">
          <h2 id="score-title" className="label">
            {analyzed.length > 1 ? 'Clip score' : 'Steeze breakdown'}
          </h2>
          <ScoreBlock
            score={clip.steeze_score}
            size={3.5}
            chip={
              analyzed.length > 1
                ? `${analyzed.filter((t) => t.outcome === 'landed').length} of ${analyzed.length} landed`
                : confidenceLabel(clip.analysis?.confidence)
            }
          />
          {analyzed.length > 1 ? (
            <TrickBreakdown
              tricks={analyzed}
              names={names.map((n, i) => n.trim() || `Trick ${i + 1}`)}
              openFirst={false}
            />
          ) : (
            <SubscoreBars breakdown={clip.analysis?.steeze_breakdown} notes={false} tight />
          )}
        </section>
      ) : (
        <p className={styles.unscored}>Not analyzed, so no score. It posts with just your trick names.</p>
      )}
      {clip.analysis && <ReportAnalysis clip={clip} names={names} />}

      <form
        className={`${page.card} ${styles.card}`}
        aria-labelledby="publish-title"
        onSubmit={submit}
        noValidate
      >
        <h2 id="publish-title" className={styles.cardTitle}>
          Before you publish
        </h2>
        <TrickSuggestions />
        {perTrick ? (
          <fieldset className={styles.tricks}>
            <legend className={styles.legend}>
              Name {analyzed.length === 1 ? 'the trick' : `each of the ${analyzed.length} tricks`} we found
            </legend>
            <p className="muted">In the order they happen. Bails count too: name the trick you went for.</p>
            <ol className={styles.trickList}>
              {analyzed.map((t, i) => (
                <li key={`${t.takeoff_ms}-${t.outcome}`} className={styles.trickRow}>
                  <div className={styles.trickMeta}>
                    <span className={styles.index}>{i + 1}</span>
                    {outcomeChip(t)}
                    {t.takeoff_ms != null && (
                      <button
                        type="button"
                        className={styles.watch}
                        onClick={() => onSeek(Math.max(0, (t.takeoff_ms ?? 0) - 500))}
                        aria-label={`Watch trick ${i + 1}, at ${formatClipTime(t.takeoff_ms)}`}
                      >
                        ▶ {formatClipTime(t.takeoff_ms)}
                      </button>
                    )}
                  </div>
                  <TrickNameInput
                    label={`Trick ${i + 1}`}
                    value={names[i] ?? ''}
                    onChange={(e) => setNames(names.map((n, j) => (j === i ? e.target.value : n)))}
                    error={touched && missing[i] ? 'Name this trick.' : null}
                  />
                </li>
              ))}
            </ol>
            {tooMany && (
              <p className={styles.error} role="alert">
                We found {analyzed.length} tricks, but a clip can carry up to {MAX_TAGS} for now, so this one
                can't be published yet.
              </p>
            )}
          </fieldset>
        ) : (
          <fieldset className={styles.tricks}>
            <legend className={styles.legend}>Tricks in this clip</legend>
            {names.map((n, i) => (
              <TrickNameInput
                // biome-ignore lint/suspicious/noArrayIndexKey: rows are only appended, never reordered
                key={i}
                label={names.length > 1 ? `Trick ${i + 1}` : 'Trick'}
                value={n}
                onChange={(e) => setNames(names.map((x, j) => (j === i ? e.target.value : x)))}
                error={touched && missing[i] ? 'Name this trick.' : null}
              />
            ))}
            {names.length < MAX_TAGS && (
              <button type="button" className={styles.textButton} onClick={() => setNames([...names, ''])}>
                + Add another trick
              </button>
            )}
          </fieldset>
        )}

        <div className={styles.select}>
          <label htmlFor={teamId} className={styles.legend}>
            Tag to a team <span className="muted">(optional)</span>
          </label>
          <select id={teamId} className={styles.input} value={team} onChange={(e) => setTeam(e.target.value)}>
            <option value="">No team</option>
            {founded.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
          <span className="muted">Only teams you're on. It can't change after publishing.</span>
        </div>

        {scored && (
          <div className={styles.include}>
            <Switch
              label="Include this score"
              description="Turn it off if the angle or light was unfair. The clip still publishes; the score just won't count toward your or your team's average."
              checked={included}
              onChange={setIncluded}
            />
          </div>
        )}

        {publish.isError && (
          <p className={styles.error} role="alert">
            Couldn't publish: {publish.error.message}
          </p>
        )}
        <Button type="submit" block disabled={publish.isPending || tooMany}>
          {publish.isPending ? 'Publishing…' : 'Publish clip'}
        </Button>
      </form>
    </div>
  );
}

/** /upload/:clipId: a clip from upload to publish. */
export function ClipFlowPage() {
  const { clipId = '' } = useParams();
  const clip = useClipProgress(clipId);
  const [seek, setSeek] = useState<{ ms: number; at: number }>();

  if (clip.isPending) return <Loading label="Loading clip" />;
  if (clip.isError) {
    return (
      <div className={page.page}>
        <ErrorState error={clip.error} onRetry={() => void clip.refetch()} />
      </div>
    );
  }
  const c = clip.data;
  if (c.status === 'published') return <Navigate to={`/clips/${c.id}`} replace />;
  const tricks = c.analysis?.tricks ?? [];

  return (
    <div className={`${page.page} ${styles.page}`}>
      <div className={styles.head}>
        <p className="label">Clip status</p>
        <h1 className={page.title}>{c.status === 'analyzed' ? 'Review and publish' : 'Your clip'}</h1>
        <p className={page.lead}>
          Uploaded {formatTimeAgo(c.created_at) === 'now' ? 'just now' : `${formatTimeAgo(c.created_at)} ago`}
        </p>
      </div>
      <Stepper steps={stepsFor(c)} />
      <div className={styles.layout}>
        <div className={styles.media}>
          <ClipMedia clip={c} src={previewUrl(c.id)} showScore={false} seek={seek} />
          {tricks.length > 1 && <TrickTimeline tricks={tricks} durationMs={c.duration_ms ?? 1} />}
        </div>
        <div className={styles.main}>
          {c.status === 'analyzed' ? (
            <Review clip={c} onSeek={(ms) => setSeek({ ms, at: Date.now() })} />
          ) : c.status === 'unanalyzable' ? (
            <div className={styles.failed}>
              <FailureCard clip={c} />
              <ReportAnalysis clip={c} />
              <Link to="/upload" className={styles.again}>
                Upload another take
              </Link>
            </div>
          ) : (
            <Waiting clip={c} />
          )}
        </div>
      </div>
    </div>
  );
}
