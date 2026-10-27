import { useReportBug } from '@tricklens/api';
import { type FormEvent, useState } from 'react';
import { Link, useLocation } from 'react-router';
import { useAuth } from '../../app/auth.tsx';
import { Button } from '../../components/ui/Button.tsx';
import { Field, TextArea } from '../../components/ui/controls.tsx';
import { apiMode, appVersion } from '../../env.ts';
import page from '../page.module.css';
import styles from './BugReportPage.module.css';

/** What links here can pass along: where you were, and an error you saw. */
export interface BugReportState {
  from?: string;
  error?: string;
}

const MIN_LENGTH = 10;
const MAX_LENGTH = 4000;

/** Sent with every report, and listed on the page so people know what's in it. */
function collectContext() {
  const explicit = document.documentElement.getAttribute('data-theme');
  const systemDark =
    typeof window.matchMedia === 'function' && window.matchMedia('(prefers-color-scheme: dark)').matches;
  return {
    app_version: appVersion,
    user_agent: navigator.userAgent,
    viewport: `${window.innerWidth}×${window.innerHeight}`,
    theme: explicit ?? `${systemDark ? 'dark' : 'light'} (system)`,
    api_mode: apiMode,
  };
}

/** /report-bug: a problem with the app itself (wrong scores go through the clip's own report). */
export function BugReportPage() {
  const state = (useLocation().state as BugReportState | null) ?? {};
  const { session } = useAuth();
  const report = useReportBug();
  const [context] = useState(collectContext);
  const [where, setWhere] = useState(state.from ?? '');
  const [description, setDescription] = useState(state.error ? `I saw this error: "${state.error}"\n\n` : '');
  const [tried, setTried] = useState(false);
  const tooShort = description.trim().length < MIN_LENGTH;
  const back = state.from ?? (session ? '/feed' : '/login');

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setTried(true);
    if (tooShort) return;
    report.mutate({ description: description.trim(), page: where.trim() || null, context });
  };

  if (report.isSuccess) {
    return (
      <div className={`${page.page} ${page.narrow}`}>
        <h1 className={page.title}>Thanks, your report was sent</h1>
        <p className={page.lead}>
          It goes straight to the TrickLens team. Reports like this are how bugs get fixed.
        </p>
        <p style={{ marginTop: '1.5rem' }}>
          <Link className={styles.back} to={back}>
            Back to where you were
          </Link>
        </p>
      </div>
    );
  }

  return (
    <div className={`${page.page} ${page.narrow}`}>
      <h1 className={page.title}>Report a bug</h1>
      <p className={page.lead}>
        Something in the app not working? Tell us what happened. For a score or trick the analyzer got wrong,
        use "Report a problem with this analysis" on the clip instead.
      </p>
      <form className={styles.form} onSubmit={submit} noValidate>
        <TextArea
          label="What went wrong?"
          value={description}
          rows={6}
          maxLength={MAX_LENGTH}
          placeholder="What you did, what you expected, and what happened instead."
          onChange={(e) => setDescription(e.target.value)}
          error={tried && tooShort ? 'Describe the problem in a few words.' : null}
        />
        <Field
          label="Where did it happen? (optional)"
          value={where}
          placeholder="e.g. the upload page"
          onChange={(e) => setWhere(e.target.value)}
        />
        <details className={styles.context}>
          <summary>What's sent with your report</summary>
          <dl>
            <dt>App version</dt>
            <dd>{context.app_version}</dd>
            <dt>Browser</dt>
            <dd>{context.user_agent}</dd>
            <dt>Window size</dt>
            <dd>{context.viewport}</dd>
            <dt>Theme</dt>
            <dd>{context.theme}</dd>
            {session && (
              <>
                <dt>Account</dt>
                <dd>Your username, so we can follow up</dd>
              </>
            )}
          </dl>
        </details>
        {report.isError && (
          <p className={styles.error} role="alert">
            Couldn't send the report: {report.error.message}
          </p>
        )}
        <div className={styles.actions}>
          <Link className={styles.cancel} to={back}>
            Cancel
          </Link>
          <Button type="submit" disabled={report.isPending}>
            {report.isPending ? 'Sending…' : 'Send report'}
          </Button>
        </div>
      </form>
    </div>
  );
}
