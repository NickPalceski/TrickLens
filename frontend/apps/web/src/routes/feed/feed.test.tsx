import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { renderApp } from '../../test/render.tsx';

const post = (name: RegExp) => screen.findByRole('article', { name });

describe('feed', () => {
  it('shows clips from followed skaters and teams, newest first, with the breakdown', async () => {
    renderApp('/feed');
    const posts = await screen.findAllByRole('article');
    expect(posts.map((p) => p.getAttribute('aria-label'))).toEqual([
      'Kickflip by @marcosandoval',
      'Backside 180 by @leotran',
      'Heelflip by @destinyfoster',
    ]);
    const marco = posts[0] as HTMLElement;
    expect(within(marco).getByRole('img', { name: 'Steeze 83 out of 100' })).toBeInTheDocument();
    expect(within(marco).getByRole('link', { name: 'Downtown Skaters' })).toHaveAttribute(
      'href',
      '/t/downtown_skaters',
    );
  });

  it('shows n/a for a subscore that does not apply', async () => {
    renderApp('/feed');
    const leo = await post(/Backside 180/);
    expect(within(leo).getByText('n/a')).toBeInTheDocument();
  });

  it('likes and unlikes, updating the count straight away', async () => {
    const { user } = renderApp('/feed');
    const marco = await post(/Kickflip by @marcosandoval/);
    await user.click(within(marco).getByRole('button', { name: 'Unlike, 148 likes' }));
    expect(within(marco).getByRole('button', { name: 'Like, 147 likes' })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
    await user.click(within(marco).getByRole('button', { name: 'Like, 147 likes' }));
    expect(within(marco).getByRole('button', { name: 'Unlike, 148 likes' })).toBeInTheDocument();
  });

  it('records a view when a clip is played', async () => {
    const { user } = renderApp('/feed');
    const leo = await post(/Backside 180/);
    expect(within(leo).getByText('410')).toBeInTheDocument();
    await user.click(within(leo).getByRole('button', { name: 'Play Backside 180' }));
    expect(await within(leo).findByText('411')).toBeInTheDocument();
    expect(within(leo).getByRole('status')).toHaveTextContent('Sample clip');
  });
});

describe('comments', () => {
  async function openComments() {
    const app = renderApp('/feed');
    const marco = await post(/Kickflip by @marcosandoval/);
    await app.user.click(within(marco).getByRole('button', { name: /^Comments, 9$/ }));
    const dialog = await screen.findByRole('dialog', { name: /Comments/ });
    await within(dialog).findByText('First try or are we not talking about it');
    return { ...app, dialog };
  }

  it('opens as a sheet with threads, the clip owner marked, and long threads folded', async () => {
    const { dialog } = await openComments();
    expect(within(dialog).getAllByText('Clip owner').length).toBeGreaterThan(0);
    expect(within(dialog).getByRole('button', { name: 'Show 1 more reply' })).toBeInTheDocument();
    expect(within(dialog).queryByText('we do not talk about the other nineteen')).not.toBeInTheDocument();
  });

  it('replies inside the thread, starting with the handle', async () => {
    const { user, dialog } = await openComments();
    const thread = within(dialog)
      .getByText('That catch was so clean. Pop looks higher than 86 to me though.')
      .closest('li');
    if (!thread) throw new Error('no thread');
    await user.click(within(thread).getAllByRole('button', { name: 'Reply' })[0] as HTMLElement);

    const input = within(dialog).getByRole('textbox', { name: 'Reply to @leotran' });
    expect(input).toHaveValue('@leotran ');
    await user.type(input, 'agreed');
    await user.click(within(dialog).getByRole('button', { name: 'Post' }));
    expect(await within(thread).findByText('@leotran agreed')).toBeInTheDocument();
    await waitFor(() =>
      expect(within(dialog).getByRole('heading', { name: /Comments/ })).toHaveTextContent('Comments 10'),
    );
  });

  it('deletes your own comment after confirming', async () => {
    const { user, dialog } = await openComments();
    const mine = within(dialog)
      .getByText(/Roll-away 88 is crazy/)
      .closest('li');
    if (!mine) throw new Error('no comment');
    await user.click(within(mine).getByRole('button', { name: 'Delete' }));
    expect(within(mine).getByText('Delete this comment?')).toBeInTheDocument();
    await user.click(within(mine).getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(within(dialog).queryByText(/Roll-away 88 is crazy/)).not.toBeInTheDocument());
  });

  it("doesn't offer delete on other people's comments on someone else's clip", async () => {
    const { dialog } = await openComments();
    const leos = within(dialog)
      .getByText(/That catch was so clean/)
      .closest('li');
    if (!leos) throw new Error('no comment');
    expect(within(leos).queryByRole('button', { name: 'Delete' })).toBeNull();
  });

  it('closes with Escape', async () => {
    const { user } = await openComments();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
