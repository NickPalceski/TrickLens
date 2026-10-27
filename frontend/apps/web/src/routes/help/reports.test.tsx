import { screen, waitFor, within } from '@testing-library/react';
import { mockState } from '@tricklens/api/mocks';
import { describe, expect, it, vi } from 'vitest';
import { renderApp } from '../../test/render.tsx';

vi.mock('../../lib/video.ts', async (original) => ({
  ...(await original<typeof import('../../lib/video.ts')>()),
  readVideoDuration: async () => 8000,
}));

const lastReport = () => mockState().reports.at(-1);

/** Uploads a clip with the given simulated result and lands on its status page. */
async function uploadedClip(outcome: 'Three-trick line' | "Couldn't score", analyze = true) {
  const app = renderApp('/upload');
  await app.user.upload(
    screen.getByLabelText('Choose a clip'),
    new File(['x'], 'line.mp4', { type: 'video/mp4' }),
  );
  if (analyze) await app.user.click(screen.getByRole('radio', { name: outcome }));
  else {
    await app.user.click(screen.getByRole('switch', { name: /Analyze the clip/ }));
    await app.user.type(screen.getByLabelText('Trick'), 'Ollie');
  }
  await app.user.click(screen.getByRole('button', { name: 'Upload clip' }));
  return app;
}

describe('report a problem with an analysis', () => {
  it('asks what went wrong, sends it, then returns you to publishing with your work intact', async () => {
    const { user, router } = await uploadedClip('Three-trick line');
    // Every trick named, so a stray publish would go through if a report submit leaked into the form.
    await user.type(await screen.findByLabelText('Trick 1'), 'Kickflip');
    await user.type(screen.getByLabelText('Trick 2'), 'Heelflip');
    await user.type(screen.getByLabelText('Trick 3'), 'Ollie');
    const reviewPath = router.state.location.pathname;

    await user.click(screen.getByRole('button', { name: 'Report a problem with this analysis' }));
    const dialog = screen.getByRole('dialog', { name: 'Report a problem with this analysis' });
    await user.click(within(dialog).getByRole('button', { name: 'Send report' }));
    expect(within(dialog).getByText('Tick what went wrong, or add a note.')).toBeInTheDocument();

    await user.click(within(dialog).getByRole('checkbox', { name: 'The score feels off' }));
    await user.selectOptions(
      within(dialog).getByLabelText('Which trick?'),
      'Trick 1: Kickflip (landed, 0:01.2)',
    );
    await user.click(within(dialog).getByRole('checkbox', { name: 'Pop' }));
    await user.click(within(dialog).getByRole('radio', { name: 'Too high' }));
    await user.type(within(dialog).getByLabelText('Anything else? (optional)'), 'Barely left the ground.');
    await user.click(within(dialog).getByRole('checkbox', { name: /keep and watch this clip/ }));
    await user.click(within(dialog).getByRole('button', { name: 'Send report' }));

    const sent = await screen.findByRole('dialog', { name: 'Report sent' });
    await user.click(within(sent).getByRole('button', { name: 'Back to publishing' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(router.state.location.pathname).toBe(reviewPath);
    expect(screen.getByLabelText('Trick 1')).toHaveValue('Kickflip');
    expect(screen.getByRole('status')).toHaveTextContent('Report sent.');
    expect(screen.getByRole('button', { name: 'Publish clip' })).toBeEnabled();
    // Reporting didn't publish anything.
    const clipId = reviewPath.split('/').at(-1);
    expect(mockState().clips.find((c) => c.id === clipId)?.status).toBe('analyzed');

    expect(lastReport()).toMatchObject({
      kind: 'analysis',
      body: {
        problems: ['score_off'],
        trick_index: 0,
        subscores: ['pop'],
        score_direction: 'too_high',
        note: 'Barely left the ground.',
        share_video: true,
      },
    });
  });

  it('keeps the video out of the report unless you tick the box', async () => {
    const { user } = await uploadedClip('Three-trick line');
    await user.click(await screen.findByRole('button', { name: 'Report a problem with this analysis' }));
    const dialog = screen.getByRole('dialog');
    await user.click(within(dialog).getByRole('checkbox', { name: 'It missed a trick' }));
    await user.click(within(dialog).getByRole('button', { name: 'Send report' }));
    await screen.findByRole('dialog', { name: 'Report sent' });
    expect(lastReport()).toMatchObject({
      body: { problems: ['missed_trick'], share_video: false, trick_index: null },
    });
  });

  it("works on a clip that couldn't be scored, with choices that fit", async () => {
    const { user } = await uploadedClip("Couldn't score");
    await user.click(await screen.findByRole('button', { name: 'Think this is wrong? Report a problem' }));
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).queryByRole('checkbox', { name: 'The score feels off' })).not.toBeInTheDocument();
    await user.click(within(dialog).getByRole('checkbox', { name: "I landed it, but it couldn't score it" }));
    await user.click(within(dialog).getByRole('button', { name: 'Send report' }));
    const sent = await screen.findByRole('dialog', { name: 'Report sent' });
    await user.click(within(sent).getByRole('button', { name: 'Back to your clip' }));
    expect(screen.getByRole('heading', { name: 'No landed trick detected' })).toBeInTheDocument();
    expect(lastReport()).toMatchObject({ body: { problems: ['should_have_scored'] } });
  });

  it('is not offered when the clip was never analyzed', async () => {
    await uploadedClip('Three-trick line', false);
    await screen.findByText('Not analyzed, so no score. It posts with just your trick names.');
    expect(screen.queryByRole('button', { name: /Report a problem/ })).not.toBeInTheDocument();
  });
});

describe('report a bug', () => {
  it('is one tap from any page and remembers where you were', async () => {
    const { user, router } = renderApp('/discover');
    await user.click(screen.getAllByRole('link', { name: 'Report a bug' })[0] as HTMLElement);
    expect(router.state.location.pathname).toBe('/report-bug');
    expect(screen.getByLabelText('Where did it happen? (optional)')).toHaveValue('/discover');

    await user.click(screen.getByRole('button', { name: 'Send report' }));
    expect(screen.getByText('Describe the problem in a few words.')).toBeInTheDocument();

    await user.type(
      screen.getByLabelText('What went wrong?'),
      'The Most active pill did nothing on my phone.',
    );
    await user.click(screen.getByRole('button', { name: 'Send report' }));
    expect(await screen.findByRole('heading', { name: 'Thanks, your report was sent' })).toBeInTheDocument();
    expect(lastReport()).toMatchObject({
      kind: 'bug',
      body: { page: '/discover', context: { app_version: 'prototype', api_mode: 'mock' } },
    });

    await user.click(screen.getByRole('link', { name: 'Back to where you were' }));
    expect(router.state.location.pathname).toBe('/discover');
  });

  it('can be reached from Settings and from an error, which it quotes', async () => {
    const { user } = renderApp('/clips/a1000000-0000-4000-8000-0000000000ff');
    const error = await screen.findByRole('alert');
    await user.click(within(error).getByRole('link', { name: 'Report a bug' }));
    expect(screen.getByLabelText('What went wrong?')).toHaveValue('I saw this error: "clip not found"\n\n');
  });

  it('works signed out, from the login screen', async () => {
    const { user, router } = renderApp('/settings');
    expect(screen.getByRole('region', { name: 'Help' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Log out' }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/login'));

    await user.click(screen.getByRole('link', { name: 'Report a bug' }));
    expect(router.state.location.pathname).toBe('/report-bug');
    expect(screen.queryByRole('navigation', { name: 'Main' })).not.toBeInTheDocument();
    await user.type(screen.getByLabelText('What went wrong?'), 'The login button spins forever.');
    await user.click(screen.getByRole('button', { name: 'Send report' }));
    expect(await screen.findByRole('heading', { name: 'Thanks, your report was sent' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Back to where you were' })).toHaveAttribute('href', '/login');
  });
});
