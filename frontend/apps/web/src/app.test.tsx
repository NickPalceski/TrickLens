import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { THEME_STORAGE_KEY } from './app/theme.tsx';
import { renderApp } from './test/render.tsx';

describe('app shell', () => {
  it('sends / to the feed and shows the signed-in user from the API', async () => {
    const { router } = renderApp('/');
    expect(router.state.location.pathname).toBe('/feed');
    expect(await screen.findByText('@juliavance')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Feed' })).toBeInTheDocument();
  });

  it('marks the current section in the nav', async () => {
    renderApp('/discover');
    const nav = screen.getAllByRole('navigation', { name: 'Main' })[0];
    if (!nav) throw new Error('no main nav');
    expect(within(nav).getByRole('link', { name: 'Discover' })).toHaveClass('active');
    expect(within(nav).getByRole('link', { name: 'Feed' })).not.toHaveClass('active');
  });

  it('shows a not-found page for unknown URLs', () => {
    renderApp('/nowhere');
    expect(screen.getByRole('heading', { name: 'Page not found' })).toBeInTheDocument();
  });
});

describe('settings', () => {
  it('switches theme, applies it to <html> and remembers it', async () => {
    const { user } = renderApp('/settings');
    expect(screen.getByRole('radio', { name: /Match system/ })).toBeChecked();

    await user.click(screen.getByRole('radio', { name: /Dark/ }));
    expect(document.documentElement).toHaveAttribute('data-theme', 'dark');
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark');

    await user.click(screen.getByRole('radio', { name: /Match system/ }));
    expect(document.documentElement).not.toHaveAttribute('data-theme');
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBeNull();
  });

  it('shows the account email from the API', async () => {
    renderApp('/settings');
    expect(await screen.findByText('julia@westlot.co')).toBeInTheDocument();
  });

  it('logs out to the login page, and signed-out visitors stay there', async () => {
    const { user, router } = renderApp('/settings');
    await user.click(screen.getByRole('button', { name: 'Log out' }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/login'));

    await router.navigate('/feed');
    await waitFor(() => expect(router.state.location.pathname).toBe('/login'));

    await user.click(screen.getByRole('button', { name: 'Continue as @juliavance' }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/feed'));
  });
});
