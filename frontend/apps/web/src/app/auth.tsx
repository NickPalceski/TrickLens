import { createContext, type ReactNode, useCallback, useContext, useMemo, useState } from 'react';
import { Navigate, useLocation } from 'react-router';

/**
 * Auth for the prototype: a fake session behind the same calls Cognito will
 * answer in phase F4 (sign in, sign up, confirm the emailed code, sign out),
 * so pages never change when the real thing arrives. Every account signs in
 * as the sample skater @juliavance (docs/components/frontend.md, Mock mode).
 */
interface Session {
  token: string;
}

export interface SignUpDetails {
  username: string;
  email: string;
  password: string;
}

/** A sign-in or sign-up failure with a message fit to show the user. */
export class AuthError extends Error {
  override name = 'AuthError';
}

interface AuthContextValue {
  session: Session | null;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (details: SignUpDetails) => Promise<void>;
  confirmSignUp: (email: string, code: string) => Promise<void>;
  signOut: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const MOCK_SESSION: Session = { token: 'mock-id-token' };
const pause = () => new Promise((r) => setTimeout(r, 300));

/** Cognito's default password policy, which the dev and prod pools use. */
export const PASSWORD_RULES = [
  { test: (p: string) => p.length >= 8, label: 'At least 8 characters' },
  { test: (p: string) => /[a-z]/.test(p) && /[A-Z]/.test(p), label: 'Upper and lower case letters' },
  { test: (p: string) => /\d/.test(p), label: 'A number' },
  { test: (p: string) => /[^A-Za-z0-9]/.test(p), label: 'A symbol' },
] as const;

export function AuthProvider({
  children,
  initiallySignedIn = true,
}: {
  children: ReactNode;
  initiallySignedIn?: boolean;
}) {
  const [session, setSession] = useState<Session | null>(initiallySignedIn ? MOCK_SESSION : null);

  const signIn = useCallback(async (_email: string, password: string) => {
    await pause();
    // Mirrors Cognito's answer to a wrong password, so the error state can be seen.
    if (password.length < 8) throw new AuthError('Incorrect email or password.');
    setSession(MOCK_SESSION);
  }, []);

  const signUp = useCallback(async ({ password }: SignUpDetails) => {
    await pause();
    if (!PASSWORD_RULES.every((r) => r.test(password)))
      throw new AuthError("That password doesn't meet the rules.");
  }, []);

  const confirmSignUp = useCallback(async (_email: string, code: string) => {
    await pause();
    if (!/^\d{6}$/.test(code)) throw new AuthError('Enter the 6-digit code from the email.');
    setSession(MOCK_SESSION);
  }, []);

  const signOut = useCallback(() => setSession(null), []);

  const value = useMemo(
    () => ({ session, signIn, signUp, confirmSignUp, signOut }),
    [session, signIn, signUp, confirmSignUp, signOut],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth() needs an <AuthProvider> above it');
  return ctx;
}

/** Sends signed-out visitors to /login, remembering where they were going. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { session } = useAuth();
  const location = useLocation();
  if (!session) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return children;
}
