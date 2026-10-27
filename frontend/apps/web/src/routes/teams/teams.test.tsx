import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { renderApp } from '../../test/render.tsx';

describe('teams list', () => {
  it('shows your teams with your role, and invites waiting for you', async () => {
    renderApp('/teams');
    const mine = await screen.findByRole('region', { name: 'Your teams' });
    expect(await within(mine).findByRole('link', { name: /Downtown Skaters.*owner/ })).toHaveAttribute(
      'href',
      '/t/downtown_skaters',
    );
    const invites = await screen.findByRole('region', { name: /Invites/ });
    expect(within(invites).getByRole('link', { name: /Ledge Lords/ })).toHaveAttribute(
      'href',
      '/t/ledge_lords',
    );
  });
});

describe('create a team', () => {
  it('walks basics, founders and review, then shows the team forming', async () => {
    const { user, router } = renderApp('/teams/new');
    await user.click(screen.getByRole('button', { name: 'Continue' }));
    expect(screen.getByText('Give the team a name.')).toBeInTheDocument();

    await user.type(screen.getByLabelText('Team name'), 'Rail Rats');
    expect(screen.getByLabelText('Team address')).toHaveValue('rail_rats');
    await user.click(screen.getByRole('radio', { name: /Invite only/ }));
    await user.click(screen.getByRole('button', { name: 'Continue' }));

    expect(screen.getByRole('heading', { name: 'Invite founding members' })).toBeInTheDocument();
    expect(screen.queryByText('Add at least 2 founding members.')).not.toBeInTheDocument();
    await user.type(screen.getByLabelText('Username'), 'nobody_here');
    await user.click(screen.getByRole('button', { name: 'Add' }));
    expect(await screen.findByText('No skater called @nobody_here.')).toBeInTheDocument();

    for (const u of ['marcosandoval', '@leotran']) {
      await user.clear(screen.getByLabelText('Username'));
      await user.type(screen.getByLabelText('Username'), u);
      await user.click(screen.getByRole('button', { name: 'Add' }));
      await screen.findByText(`@${u.replace('@', '')}`);
    }
    await user.click(screen.getByRole('button', { name: 'Continue' }));

    expect(screen.getByRole('heading', { name: 'Review your team' })).toBeInTheDocument();
    expect(screen.getByText('Invite only')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Create team' }));

    await waitFor(() => expect(router.state.location.pathname).toBe('/t/rail_rats'));
    expect(await screen.findByRole('heading', { name: 'Rail Rats is forming' })).toBeInTheDocument();
    expect(screen.getAllByText('Pending')).toHaveLength(2);

    await user.click(screen.getByRole('button', { name: 'Cancel team creation' }));
    await user.click(screen.getByRole('button', { name: 'Cancel it for everyone' }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/teams'));
  });

  it('sends you back to fix a taken address', async () => {
    const { user } = renderApp('/teams/new');
    await user.type(screen.getByLabelText('Team name'), 'Night Shift');
    await user.click(screen.getByRole('button', { name: 'Continue' }));
    for (const u of ['marcosandoval', 'leotran']) {
      await user.clear(screen.getByLabelText('Username'));
      await user.type(screen.getByLabelText('Username'), u);
      await user.click(screen.getByRole('button', { name: 'Add' }));
      await screen.findByText(`@${u}`);
    }
    await user.click(screen.getByRole('button', { name: 'Continue' }));
    await user.click(screen.getByRole('button', { name: 'Create team' }));
    expect(await screen.findByText('That address is taken. Try another.')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Basics' })).toBeInTheDocument();
  });
});

describe('founding invite', () => {
  it('accepting the last founding invite makes the team live', async () => {
    const { user } = renderApp('/t/ledge_lords');
    expect(await screen.findByText('This is bigger than a join request')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Accept and help found it' }));
    const members = await screen.findByRole('region', { name: 'Members' });
    expect(await within(members).findByText('Julia Vance')).toBeInTheDocument();
  });

  it('declining asks first, then cancels the team for everyone', async () => {
    const { user, router } = renderApp('/t/ledge_lords');
    await user.click(await screen.findByRole('button', { name: 'Decline' }));
    expect(screen.getByText('Cancel Ledge Lords for everyone?')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Decline and cancel it' }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/teams'));

    await router.navigate('/t/ledge_lords');
    expect(await screen.findByText('team not found')).toBeInTheDocument();
  });
});

describe('a live team', () => {
  it('lets the owner promote a member and approve a join request', async () => {
    const { user } = renderApp('/t/downtown_skaters');
    const members = await screen.findByRole('region', { name: 'Members' });
    await within(members).findByText('Leo Tran');
    const leo = within(members).getByText('Leo Tran').closest('li') as HTMLElement;
    await user.click(within(leo).getByLabelText('Manage @leotran'));
    await user.click(within(leo).getByRole('button', { name: 'Make an admin' }));
    await waitFor(() => expect(within(leo).getByText('admin')).toBeInTheDocument());

    const requests = screen.getByRole('region', { name: /Join requests/ });
    const priya = (await within(requests).findByText('@priyanair')).closest('li') as HTMLElement;
    await user.click(within(priya).getByRole('button', { name: 'Approve' }));
    expect(await within(members).findByText('Priya Nair')).toBeInTheDocument();
    await waitFor(() => expect(within(requests).queryByText('@priyanair')).not.toBeInTheDocument());
  });

  it('removes a member only after confirming', async () => {
    const { user } = renderApp('/t/downtown_skaters');
    const members = await screen.findByRole('region', { name: 'Members' });
    const destiny = (await within(members).findByText('Destiny Foster')).closest('li') as HTMLElement;
    await user.click(within(destiny).getByLabelText('Manage @destinyfoster'));
    await user.click(within(destiny).getByRole('button', { name: 'Remove from team' }));
    await user.click(within(destiny).getByRole('button', { name: 'Remove' }));
    await waitFor(() => expect(within(members).queryByText('Destiny Foster')).not.toBeInTheDocument());
  });

  it('asks to join a request-only team, and remembers the request', async () => {
    const { user, router } = renderApp('/t/westside_ledge_club');
    await user.click(await screen.findByRole('button', { name: 'Request to join' }));
    expect(await screen.findByRole('button', { name: 'Request sent · Withdraw' })).toBeInTheDocument();

    await router.navigate('/teams');
    await router.navigate('/t/westside_ledge_club');
    await user.click(await screen.findByRole('button', { name: 'Request sent · Withdraw' }));
    expect(await screen.findByRole('button', { name: 'Request to join' })).toBeInTheDocument();
  });

  it('joins an open team, then can leave it', async () => {
    const { user } = renderApp('/t/night_shift');
    await user.click(await screen.findByRole('button', { name: 'Join' }));
    await user.click(await screen.findByRole('button', { name: 'Leave team' }));
    await user.click(screen.getByRole('button', { name: 'Leave Night Shift' }));
    expect(await screen.findByRole('button', { name: 'Join' })).toBeInTheDocument();
  });

  it('explains an invite-only team instead of offering to join', async () => {
    renderApp('/t/curb_cult');
    expect(await screen.findByText('Invite only. Ask an owner or admin to invite you.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Join' })).not.toBeInTheDocument();
  });

  it('follows a team', async () => {
    const { user } = renderApp('/t/night_shift');
    await user.click(await screen.findByRole('button', { name: 'Follow' }));
    expect(await screen.findByRole('button', { name: '✓ Following' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
  });

  it("shows the team's clips", async () => {
    renderApp('/t/downtown_skaters');
    expect(await screen.findByRole('link', { name: 'Kickflip by @marcosandoval' })).toBeInTheDocument();
  });
});

describe('team settings', () => {
  it('saves changes for the owner', async () => {
    const { user, router } = renderApp('/t/downtown_skaters/settings');
    const name = await screen.findByLabelText('Team name');
    await user.clear(name);
    await user.type(name, 'Downtown Crew');
    await user.click(screen.getByRole('radio', { name: /^Open/ }));
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/t/downtown_skaters'));
    expect(await screen.findByRole('heading', { name: 'Downtown Crew' })).toBeInTheDocument();
  });

  it('deletes only after the name is typed', async () => {
    const { user, router } = renderApp('/t/downtown_skaters/settings');
    const del = await screen.findByRole('button', { name: 'Delete team' });
    expect(del).toBeDisabled();
    await user.type(screen.getByLabelText('Type Downtown Skaters to confirm'), 'Downtown Skaters');
    await user.click(del);
    await waitFor(() => expect(router.state.location.pathname).toBe('/teams'));
  });

  it("is the owner's only", async () => {
    renderApp('/t/night_shift/settings');
    expect(await screen.findByText("Only the team's owner can change its settings.")).toBeInTheDocument();
  });
});
