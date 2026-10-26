import { screen, within } from '@testing-library/react';
import { mockData } from '@tricklens/api/mocks';
import { describe, expect, it } from 'vitest';
import { renderApp } from '../../test/render.tsx';

const { clips } = mockData.ids;

describe('clip detail', () => {
  it('breaks a single trick down with what each subscore measures', async () => {
    renderApp(`/clips/${clips.marcoKickflip}`);
    expect(await screen.findByRole('heading', { name: 'Steeze breakdown' })).toBeInTheDocument();
    expect(screen.getByText('High confidence')).toBeInTheDocument();
    expect(screen.getByText('How much air came off the tail.')).toBeInTheDocument();
    // Someone else's clip: no score-inclusion switch.
    expect(screen.queryByRole('switch')).not.toBeInTheDocument();
  });

  it('lists every trick in a line, scores only the landed ones, and shows n/a', async () => {
    const { user } = renderApp(`/clips/${clips.juliaLine}`);
    expect(await screen.findByRole('heading', { name: 'Clip score' })).toBeInTheDocument();
    expect(screen.getByText('2 of 3 landed')).toBeInTheDocument();
    expect(screen.getByText(/Averaged over the 2 landed tricks/)).toBeInTheDocument();

    // One tag per analyzed trick, so the rows are named by the tags, in order.
    const tricks = screen.getAllByRole('button').filter((b) => b.hasAttribute('aria-expanded'));
    expect(tricks.map((b) => b.textContent)).toEqual([
      expect.stringContaining('Kickflip'),
      expect.stringContaining('Heelflip'),
      expect.stringContaining('Ollie'),
    ]);
    expect(within(tricks[1] as HTMLElement).getByText('Bailed')).toBeInTheDocument();
    expect(within(tricks[1] as HTMLElement).getByText('Not scored')).toBeInTheDocument();

    await user.click(tricks[2] as HTMLElement);
    expect(tricks[2]).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('n/a')).toBeInTheDocument();
  });

  it('lets the owner take a score out of their average, and it sticks', async () => {
    const { user, router } = renderApp(`/clips/${clips.juliaKickflip}`);
    const toggle = await screen.findByRole('switch', { name: /Counts toward your average/ });
    expect(toggle).toBeChecked();
    await user.click(toggle);
    expect(toggle).not.toBeChecked();

    await router.navigate('/profile');
    await router.navigate(`/clips/${clips.juliaKickflip}`);
    expect(await screen.findByRole('switch', { name: /Counts toward your average/ })).not.toBeChecked();
  });

  it('explains why your own clip could not be scored', async () => {
    renderApp(`/clips/${clips.juliaHeelflipFailed}`);
    expect(await screen.findByRole('heading', { name: 'No landed trick detected' })).toBeInTheDocument();
    expect(
      screen.getByText('Keep the board and both feet in frame through the landing.'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Like/ })).not.toBeInTheDocument();
  });

  it('shows comments inline under the breakdown', async () => {
    renderApp(`/clips/${clips.juliaKickflip}`);
    expect(await screen.findByText('Third try is the charm every time.')).toBeInTheDocument();
  });

  it('says so when a clip does not exist', async () => {
    renderApp('/clips/a1000000-0000-4000-8000-0000000000ff');
    expect(await screen.findByText('clip not found')).toBeInTheDocument();
  });
});
