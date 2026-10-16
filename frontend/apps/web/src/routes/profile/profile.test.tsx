import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { renderApp } from '../../test/render.tsx';

describe('profiles', () => {
  it('shows your own profile with setup, stats and clips, including uncounted ones', async () => {
    renderApp('/profile');
    expect(await screen.findByRole('heading', { name: 'Julia Vance' })).toBeInTheDocument();
    expect(screen.getByText('Baker B1 8.0″')).toBeInTheDocument();
    expect(screen.getByText('79.3')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Edit profile' })).toBeInTheDocument();
    const clips = await screen.findByRole('region', { name: 'Clips' });
    expect(await within(clips).findByText('Boardslide')).toBeInTheDocument();
    expect(within(clips).getByText('Not counted')).toBeInTheDocument();
  });

  it('follows and unfollows another skater', async () => {
    const { user } = renderApp('/u/destinyfoster');
    const follow = await screen.findByRole('button', { name: 'Follow' });
    expect(screen.getByText('312')).toBeInTheDocument();
    await user.click(follow);
    expect(await screen.findByRole('button', { name: '✓ Following' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(screen.getByText('313')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '✓ Following' }));
    expect(await screen.findByRole('button', { name: 'Follow' })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText('312')).toBeInTheDocument());
  });

  it('sends your own username to /profile', async () => {
    const { router } = renderApp('/u/juliavance');
    await waitFor(() => expect(router.state.location.pathname).toBe('/profile'));
  });

  it('says when a skater does not exist', async () => {
    renderApp('/u/nobody');
    expect(await screen.findByText('user not found')).toBeInTheDocument();
  });
});

describe('edit profile', () => {
  it('saves name, bio and setup, and shows them on the profile', async () => {
    const { user, router } = renderApp('/profile/edit');
    const name = await screen.findByLabelText('Display name');
    await user.clear(name);
    await user.type(name, 'Jules V');
    await user.click(screen.getByRole('radio', { name: 'Goofy' }));
    await user.clear(screen.getByLabelText('Trucks'));
    await user.type(screen.getByLabelText('Trucks'), 'Thunder 148');
    await user.click(screen.getByRole('button', { name: 'Save changes' }));

    await waitFor(() => expect(router.state.location.pathname).toBe('/profile'));
    expect(await screen.findByRole('heading', { name: 'Jules V' })).toBeInTheDocument();
    expect(screen.getByText('Goofy')).toBeInTheDocument();
    expect(screen.getByText('Thunder 148')).toBeInTheDocument();
  });

  it('checks wheel and board sizes against the API limits', async () => {
    const { user, router } = renderApp('/profile/edit');
    const wheels = await screen.findByLabelText('Wheel size (mm)');
    await user.clear(wheels);
    await user.type(wheels, '99');
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(screen.getByText('A whole number from 40 to 80 mm.')).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/profile/edit');
  });

  it('keeps the username read-only', async () => {
    renderApp('/profile/edit');
    expect(await screen.findByLabelText('Username')).toHaveAttribute('readonly');
  });
});
