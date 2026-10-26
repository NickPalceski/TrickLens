import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { mockData } from '@tricklens/api/mocks';
import { HttpResponse, http } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { renderApp } from '../../test/render.tsx';
import { server } from '../../test/setup.ts';

// jsdom can't read video metadata; every picked clip "is" 3.2s unless a test says otherwise.
const duration = vi.hoisted(() => ({ ms: 3200 }));
vi.mock('../../lib/video.ts', async (original) => ({
  ...(await original<typeof import('../../lib/video.ts')>()),
  readVideoDuration: async () => duration.ms,
}));

const video = (name = 'line.mp4', type = 'video/mp4') => new File(['fake video bytes'], name, { type });

async function startUpload(file = video()) {
  const app = renderApp('/upload');
  await app.user.upload(screen.getByLabelText('Choose a clip'), file);
  return app;
}

describe('upload', () => {
  it('asks for a clip, and rejects other file types and clips over 30 seconds', async () => {
    const { user } = renderApp('/upload');
    await user.click(screen.getByRole('button', { name: 'Upload clip' }));
    expect(screen.getByText('Choose a clip to upload.')).toBeInTheDocument();

    // The file picker filters by `accept`; a dropped or forced file isn't filtered, so check our own guard.
    await userEvent
      .setup({ applyAccept: false })
      .upload(screen.getByLabelText('Choose a clip'), video('notes.txt', 'text/plain'));
    expect(screen.getByText('Choose an MP4, MOV or WebM video.')).toBeInTheDocument();

    duration.ms = 45_000;
    await user.upload(screen.getByLabelText('Choose a clip'), video());
    expect(screen.getByText('That clip is 45 seconds. Trim it to 30 seconds or less.')).toBeInTheDocument();
    duration.ms = 3200;
  });

  it('analyzes a line, then has you name each trick it found, in order, and publishes', async () => {
    const { user, router } = await startUpload();
    await user.click(screen.getByRole('radio', { name: 'Three-trick line' }));
    await user.click(screen.getByRole('button', { name: 'Upload clip' }));

    expect(await screen.findByRole('heading', { name: 'Review and publish' })).toBeInTheDocument();
    expect(router.state.location.pathname).toMatch(/^\/upload\/a2/);
    expect(screen.getByText('Name each of the 3 tricks we found')).toBeInTheDocument();
    expect(screen.getByText('2 of 3 landed')).toBeInTheDocument();

    // Every trick needs a name, bails included.
    await user.click(screen.getByRole('button', { name: 'Publish clip' }));
    expect(screen.getAllByText('Name this trick.')).toHaveLength(3);

    for (const [i, name] of ['Kickflip', 'Heelflip', 'Ollie'].entries()) {
      await user.type(screen.getByLabelText(`Trick ${i + 1}`), name);
    }
    await user.selectOptions(screen.getByLabelText(/Tag to a team/), 'Downtown Skaters');
    await user.click(screen.getByRole('button', { name: 'Publish clip' }));

    await waitFor(() => expect(router.state.location.pathname).toMatch(/^\/clips\/a2/));
    // The clip page names the analyzer's rows with the tags, in order.
    const rows = (await screen.findAllByRole('button')).filter((b) => b.hasAttribute('aria-expanded'));
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringContaining('Kickflip'),
      expect.stringContaining('Heelflip'),
      expect.stringContaining('Ollie'),
    ]);
    expect(screen.getByRole('link', { name: 'Downtown Skaters' })).toBeInTheDocument();
  });

  it('can skip analysis: name the tricks up front and post without a score', async () => {
    const { user, router } = await startUpload();
    await user.click(screen.getByRole('switch', { name: /Analyze the clip/ }));
    await user.click(screen.getByRole('button', { name: 'Upload clip' }));
    expect(screen.getByText('Name at least one trick.')).toBeInTheDocument();

    await user.type(screen.getByLabelText('Trick'), 'Ollie');
    await user.click(screen.getByRole('button', { name: '+ Add another trick' }));
    await user.type(screen.getByLabelText('Trick 2'), 'Pop shove-it');
    await user.click(screen.getByRole('button', { name: 'Upload clip' }));

    expect(
      await screen.findByText('Not analyzed, so no score. It posts with just your trick names.'),
    ).toBeInTheDocument();
    expect(screen.getByLabelText('Trick 1')).toHaveValue('Ollie');
    expect(screen.getByLabelText('Trick 2')).toHaveValue('Pop shove-it');
    expect(screen.queryByRole('switch', { name: /Include this score/ })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Publish clip' }));
    await waitFor(() => expect(router.state.location.pathname).toMatch(/^\/clips\/a2/));
  });

  it("shows why a clip couldn't be scored", async () => {
    const { user } = await startUpload();
    await user.click(screen.getByRole('radio', { name: "Couldn't score" }));
    await user.click(screen.getByRole('button', { name: 'Upload clip' }));
    expect(await screen.findByRole('heading', { name: 'No landed trick detected' })).toBeInTheDocument();
    const steps = screen.getByRole('list', { name: 'Clip status' });
    expect(within(steps).getByText("Couldn't score").closest('li')).toHaveTextContent(
      "Couldn't score: failed",
    );
    expect(screen.getByRole('link', { name: 'Upload another take' })).toHaveAttribute('href', '/upload');
  });

  it('lists unpublished clips so you can get back to them', async () => {
    renderApp('/upload');
    const list = await screen.findByRole('region', { name: 'In progress' });
    expect(within(list).getByRole('link', { name: /Heelflip.*Couldn't score/ })).toHaveAttribute(
      'href',
      expect.stringMatching(/^\/upload\//),
    );
  });

  it('shows a clip that is still being analyzed, without the publish form', async () => {
    const clipId = mockData.ids.clips.juliaHeelflipFailed;
    server.use(http.get(`*/clips/${clipId}`, () => HttpResponse.json({ ...analyzingClip, id: clipId })));
    renderApp(`/upload/${clipId}`);
    expect(await screen.findByRole('heading', { name: 'Analyzing your clip' })).toBeInTheDocument();
    const steps = screen.getByRole('list', { name: 'Clip status' });
    expect(within(steps).getByText('Analyzing').closest('li')).toHaveAttribute('aria-current', 'step');
    expect(screen.queryByRole('button', { name: 'Publish clip' })).not.toBeInTheDocument();
  });
});

const analyzingClip = {
  status: 'analyzing',
  author: { id: mockData.ids.julia, username: 'juliavance', display_name: 'Julia Vance', avatar_url: null },
  video_url: 'mock://video/x',
  tricks: [],
  analysis: null,
  like_count: 0,
  comment_count: 0,
  view_count: 0,
  liked_by_me: false,
  score_included: true,
  created_at: new Date().toISOString(),
};
