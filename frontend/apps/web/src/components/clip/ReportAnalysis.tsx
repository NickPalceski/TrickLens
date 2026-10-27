import {
  type AnalysisProblem,
  type ClipOut,
  formatClipTime,
  SUBSCORES,
  useReportAnalysis,
} from '@tricklens/api';
import { type FormEvent, useId, useState } from 'react';
import { appVersion } from '../../env.ts';
import { Icon } from '../icons/Icon.tsx';
import { Button } from '../ui/Button.tsx';
import { Checkbox, Segmented, TextArea } from '../ui/controls.tsx';
import { Dialog } from '../ui/Dialog.tsx';
import styles from './ReportAnalysis.module.css';

const FOR_SCORED: { value: AnalysisProblem; label: string }[] = [
  { value: 'missed_trick', label: 'It missed a trick' },
  { value: 'extra_trick', label: "It found a trick that isn't there" },
  { value: 'wrong_landed', label: 'It called a landing or a bail wrong' },
  { value: 'timing_off', label: 'It picked the wrong moment for a trick' },
  { value: 'score_off', label: 'The score feels off' },
];
const FOR_UNSCORED: { value: AnalysisProblem; label: string }[] = [
  { value: 'should_have_scored', label: "I landed it, but it couldn't score it" },
  { value: 'wrong_reason', label: "The reason it gave doesn't fit" },
  { value: 'missed_trick', label: 'It missed a trick' },
];
/** Problems about one particular trick, which make "Which trick?" worth asking. */
const PER_TRICK = new Set<AnalysisProblem>(['extra_trick', 'wrong_landed', 'timing_off', 'score_off']);
const DIRECTIONS = [
  { value: 'too_high', label: 'Too high' },
  { value: 'too_low', label: 'Too low' },
] as const;
const NOTE_MAX = 2000;

function ReportForm({ clip, names, onSent }: { clip: ClipOut; names?: string[]; onSent: () => void }) {
  const report = useReportAnalysis(clip.id);
  const trickId = useId();
  const unscored = clip.status === 'unanalyzable';
  const options = unscored ? FOR_UNSCORED : FOR_SCORED;
  const tricks = clip.analysis?.tricks ?? [];

  const [problems, setProblems] = useState<AnalysisProblem[]>([]);
  const [trick, setTrick] = useState('');
  const [parts, setParts] = useState<string[]>([]);
  const [direction, setDirection] = useState<'too_high' | 'too_low' | null>(null);
  const [note, setNote] = useState('');
  const [share, setShare] = useState(false);
  const [tried, setTried] = useState(false);

  const toggle = <T,>(list: T[], v: T, on: boolean) => (on ? [...list, v] : list.filter((x) => x !== v));
  const empty = problems.length === 0 && !note.trim();
  const askTrick = tricks.length > 1 && problems.some((p) => PER_TRICK.has(p));
  const scoreOff = problems.includes('score_off');

  const submit = (e: FormEvent) => {
    e.preventDefault();
    // React events bubble through portals: never let this submit reach a page form around the trigger.
    e.stopPropagation();
    setTried(true);
    if (empty) return;
    report.mutate(
      {
        problems,
        trick_index: askTrick && trick !== '' ? Number.parseInt(trick, 10) : null,
        subscores: scoreOff ? parts : [],
        score_direction: scoreOff ? direction : null,
        note: note.trim() || null,
        share_video: share,
        app_version: appVersion,
      },
      { onSuccess: onSent },
    );
  };

  return (
    <form className={styles.form} onSubmit={submit} noValidate>
      <p className="muted">
        The analyzer is new and learns from its mistakes. Tell us what it got wrong.{' '}
        {unscored ? '' : "It won't change your score, and you can still publish."}
      </p>

      <fieldset className={styles.group}>
        <legend className={styles.legend}>What went wrong?</legend>
        {options.map((o) => (
          <Checkbox
            key={o.value}
            label={o.label}
            checked={problems.includes(o.value)}
            onChange={(on) => setProblems(toggle(problems, o.value, on))}
          />
        ))}
      </fieldset>

      {askTrick && (
        <div className={styles.field}>
          <label htmlFor={trickId} className={styles.legend}>
            Which trick?
          </label>
          <select
            id={trickId}
            className={styles.select}
            value={trick}
            onChange={(e) => setTrick(e.target.value)}
          >
            <option value="">More than one, or not sure</option>
            {tricks.map((t, i) => (
              <option key={`${t.takeoff_ms}-${t.outcome}`} value={i}>
                {`Trick ${i + 1}${names?.[i]?.trim() ? `: ${names[i]?.trim()}` : ''} (${t.outcome}${
                  t.takeoff_ms != null ? `, ${formatClipTime(t.takeoff_ms)}` : ''
                })`}
              </option>
            ))}
          </select>
        </div>
      )}

      {scoreOff && (
        <fieldset className={styles.group}>
          <legend className={styles.legend}>Which parts feel off?</legend>
          <div className={styles.parts}>
            {SUBSCORES.map((s) => (
              <Checkbox
                key={s.key}
                label={s.label}
                checked={parts.includes(s.key)}
                onChange={(on) => setParts(toggle(parts, s.key as string, on))}
              />
            ))}
          </div>
          <Segmented label="The score is" options={DIRECTIONS} value={direction} onChange={setDirection} />
        </fieldset>
      )}

      <TextArea
        label="Anything else? (optional)"
        value={note}
        maxLength={NOTE_MAX}
        rows={3}
        placeholder="e.g. The second trick was a heelflip, and I rolled away clean."
        onChange={(e) => setNote(e.target.value)}
      />

      <div className={styles.consent}>
        <Checkbox
          label="Let TrickLens keep and watch this clip to improve the analyzer"
          description="Only the TrickLens team sees it. Without this, we only get what you wrote and the analysis numbers."
          checked={share}
          onChange={setShare}
        />
      </div>

      {tried && empty && (
        <p className={styles.error} role="alert">
          Tick what went wrong, or add a note.
        </p>
      )}
      {report.isError && (
        <p className={styles.error} role="alert">
          Couldn't send the report: {report.error.message}
        </p>
      )}
      <Button type="submit" block disabled={report.isPending}>
        {report.isPending ? 'Sending…' : 'Send report'}
      </Button>
    </form>
  );
}

/**
 * "Report a problem with this analysis": your own clip, scored or not,
 * before publishing. Sending never blocks publishing; the dialog confirms
 * and then returns you to the clip as you left it.
 */
export function ReportAnalysis({ clip, names }: { clip: ClipOut; names?: string[] }) {
  const [open, setOpen] = useState(false);
  const [sent, setSent] = useState(false);
  const back = clip.status === 'analyzed' ? 'Back to publishing' : 'Back to your clip';

  return (
    <>
      {sent && !open ? (
        <p className={styles.sent} role="status">
          <Icon name="check" size={14} strokeWidth={3} /> Report sent. Thanks for helping improve the
          analyzer.
        </p>
      ) : (
        <button type="button" className={styles.trigger} onClick={() => setOpen(true)}>
          <Icon name="flag" size={16} />
          {clip.status === 'unanalyzable'
            ? 'Think this is wrong? Report a problem'
            : 'Report a problem with this analysis'}
        </button>
      )}
      {open && (
        <Dialog
          title={sent ? 'Report sent' : 'Report a problem with this analysis'}
          onClose={() => setOpen(false)}
        >
          {sent ? (
            <div className={styles.form}>
              <p>Thanks. Reports like this are how the analyzer gets better at clips like yours.</p>
              <Button block onClick={() => setOpen(false)}>
                {back}
              </Button>
            </div>
          ) : (
            <ReportForm clip={clip} names={names} onSent={() => setSent(true)} />
          )}
        </Dialog>
      )}
    </>
  );
}
