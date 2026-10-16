import { createContext, type ReactNode, useCallback, useContext, useMemo, useState } from 'react';
import { Navigate, useLocation } from 'react-router';

/**
 * Auth for the prototype: a fake session, signed in by default. Phase 4
 * swaps this for real Cognito sign-in behind the same interface, so pages
 * only ever see `session`, `signIn` and `signOut`.
 */
interface Session {
  token: string;
}

interface AuthContextValue {
  session: Session | null;
  signIn: () => void;
  signOut: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const MOCK_SESSION: Session = { token: 'mock-id-token' };

export function AuthProvider({
  children,
  initiallySignedIn = true,
}: {
  children: ReactNode;
  initiallySignedIn?: boolean;
}) {
  const [session, setSession] = useState<Session | null>(initiallySignedIn ? MOCK_SESSION : null);
  const signIn = useCallback(() => setSession(MOCK_SESSION), []);
  const signOut = useCallback(() => setSession(null), []);
  const value = useMemo(() => ({ session, signIn, signOut }), [session, signIn, signOut]);
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
