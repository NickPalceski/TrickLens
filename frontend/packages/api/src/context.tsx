import { createContext, type ReactNode, useContext } from 'react';
import type { ApiClient } from './client.ts';

const ApiContext = createContext<ApiClient | null>(null);

/** Makes one API client available to every query hook below it. */
export function ApiProvider({ client, children }: { client: ApiClient; children: ReactNode }) {
  return <ApiContext.Provider value={client}>{children}</ApiContext.Provider>;
}

export function useApi(): ApiClient {
  const client = useContext(ApiContext);
  if (!client) throw new Error('useApi() needs an <ApiProvider> above it');
  return client;
}
