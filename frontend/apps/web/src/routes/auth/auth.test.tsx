import { screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { renderApp } from '../../test/render.tsx';

describe('log in', () => {
  it('asks for the missing fields instead of submitting', async () => {
    const { user, router } = renderApp('/login');
    await user.click(screen.getByRole('button', { name: 'Log in' }));
    expect(screen.getByText('Enter your email address.')).toBeInTheDocument();
    expect(screen.getByText('Enter your password.')).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/login');
  });

  it('shows a wrong-password error, then signs in and goes to the feed', async () => {
    const { user, router } = renderApp('/login');
    await user.type(screen.getByLabelText('Email'), 'julia@westlot.co');
    await user.type(screen.getByLabelText('Password'), 'short');
    await user.click(screen.getByRole('button', { name: 'Log in' }));
    expect(await screen.findByText('Incorrect email or password.')).toBeInTheDocument();

    await user.type(screen.getByLabelText('Password'), 'enough-now');
    await user.click(screen.getByRole('button', { name: 'Log in' }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/feed'));
  });

  it('can show the password', async () => {
    const { user } = renderApp('/login');
    const password = screen.getByLabelText('Password');
    expect(password).toHaveAttribute('type', 'password');
    await user.click(screen.getByRole('button', { name: 'Show password' }));
    expect(password).toHaveAttribute('type', 'text');
  });
});

describe('sign up', () => {
  it("checks the username rule, Cognito's password rules and the confirmation", async () => {
    const { user, router } = renderApp('/signup');
    await user.type(screen.getByLabelText('Username'), 'Bad Name');
    await user.type(screen.getByLabelText('Email'), 'new@skater.co');
    await user.type(screen.getByLabelText('Password'), 'weakpass');
    await user.type(screen.getByLabelText('Confirm password'), 'different');
    await user.click(screen.getByRole('button', { name: 'Create account' }));

    expect(screen.getByText('3 to 30 lowercase letters, digits or underscores.')).toBeInTheDocument();
    expect(screen.getByText("This password doesn't meet the rules below.")).toBeInTheDocument();
    expect(screen.getByText("The passwords don't match.")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/signup');
  });

  it('confirms the emailed code, registers with the API and lands on the feed', async () => {
    const { user, router } = renderApp('/signup');
    await user.type(screen.getByLabelText('Username'), 'new_skater');
    await user.type(screen.getByLabelText('Email'), 'new@skater.co');
    await user.type(screen.getByLabelText('Password'), 'Kickfl1p!');
    await user.type(screen.getByLabelText('Confirm password'), 'Kickfl1p!');
    await user.click(screen.getByRole('button', { name: 'Create account' }));

    expect(await screen.findByRole('heading', { name: 'Check your email' })).toBeInTheDocument();
    expect(screen.getByText('new@skater.co')).toBeInTheDocument();
    await user.type(screen.getByLabelText('Verification code'), '123456');
    await user.click(screen.getByRole('button', { name: 'Confirm and continue' }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/feed'));
  });
});
