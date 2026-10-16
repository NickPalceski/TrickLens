import { screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { renderApp } from '../../test/render.tsx';

const ranked = () => screen.getAllByRole('link', { name: /^#\d+ / }).map((a) => a.getAttribute('href'));

describe('discover', () => {
  it('ranks this week by score, leaving out clips whose score is not counted', async () => {
    renderApp('/discover');
    const first = await screen.findByRole('link', { name: '#1 Hardflip by @caseyoshiro, score 92' });
    expect(first).toHaveAttribute('href', expect.stringMatching(/^\/clips\//));
    expect(screen.queryByRole('link', { name: /Boardslide/ })).not.toBeInTheDocument();
  });

  it('re-ranks by activity, which includes uncounted clips', async () => {
    const { user, router } = renderApp('/discover');
    await screen.findByRole('link', { name: /^#1 / });
    const before = ranked();
    await user.click(screen.getByRole('radio', { name: 'Most active' }));
    expect(router.state.location.search).toBe('?sort=engagement');
    await screen.findByRole('link', { name: /Boardslide/ });
    expect(ranked()).not.toEqual(before);
  });

  it('shows rising teams with their 7-day change on the Teams tab', async () => {
    const { user } = renderApp('/discover');
    await user.click(screen.getByRole('radio', { name: 'Teams' }));
    const teams = await screen.findByRole('region', { name: 'Rising teams' });
    const first = within(teams).getAllByRole('listitem')[0] as HTMLElement;
    expect(within(first).getByRole('link', { name: 'Night Shift' })).toHaveAttribute(
      'href',
      '/t/night_shift',
    );
    expect(within(first).getByText('+7.4')).toBeInTheDocument();
  });
});
