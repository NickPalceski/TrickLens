import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ApiProvider, createApiClient } from '@tricklens/api';
import { type ReactNode, useRef, useState } from 'react';
import { apiUrl } from '../env.ts';
import { AuthProvider, useAuth } from './auth.tsx';
import { ThemeProvider } from './theme.tsx';

/** One API client for the app's lifetime; it reads the current token at request time. */
function Api({ children }: { children: ReactNode }) {
  const { session } = useAuth();
  const token = useRef<string | null>(null);
  token.current = session?.token ?? null;
  const [client] = useState(() => createApiClient({ baseUrl: apiUrl, getToken: () => token.current }));
  return <ApiProvider client={client}>{children}</ApiProvider>;
}

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({ defaultOptions: { queries: { staleTime: 30_000, refetchOnWindowFocus: false } } }),
  );
  return (
    <ThemeProvider>
      <AuthProvider>
        <QueryClientProvider client={queryClient}>
          <Api>{children}</Api>
        </QueryClientProvider>
      </AuthProvider>
    </ThemeProvider>
  );
}
