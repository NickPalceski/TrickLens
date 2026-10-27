// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { HttpResponse, http } from 'msw';
import { setupServer } from 'msw/node';
import type { ReactNode } from 'react';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { ApiError, createApiClient, unwrap } from './client.ts';
import { ApiProvider } from './context.tsx';
import { formatAverage, formatCount, formatScore } from './format.ts';
import { handlers } from './mocks/handlers.ts';
import { useMe, useUser } from './queries/users.ts';

const server = setupServer(...handlers);
beforeAll(() => server.listen({ onUnhandledFrame: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const BASE = 'http://api.test';

function wrapper({ children }: { children: ReactNode }) {
  const client = createApiClient({ baseUrl: BASE, getToken: () => 'test-token' });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={queryClient}>
      <ApiProvider client={client}>{children}</ApiProvider>
    </QueryClientProvider>
  );
}

describe('api client against the mock handlers', () => {
  it('loads the signed-in user through the real hook', async () => {
    const { result } = renderHook(() => useMe(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.username).toBe('juliavance');
  });

  it('sends the bearer token', async () => {
    let seen: string | null = null;
    server.use(
      http.get('*/users/me', ({ request }) => {
        seen = request.headers.get('Authorization');
        return HttpResponse.json({});
      }),
    );
    const client = createApiClient({ baseUrl: BASE, getToken: () => 'abc' });
    await client.GET('/users/me');
    expect(seen).toBe('Bearer abc');
  });

  it("turns FastAPI's error detail into an ApiError", async () => {
    const { result } = renderHook(() => useUser('nobody'), { wrapper });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBeInstanceOf(ApiError);
    expect((result.current.error as ApiError).status).toBe(404);
    expect((result.current.error as ApiError).message).toBe('user not found');
  });

  it('unwrap passes data through', () => {
    expect(unwrap({ data: 1, response: new Response() })).toBe(1);
  });
});

describe('formatting', () => {
  it('reads Decimal strings from the API', () => {
    expect(formatScore('79.50')).toBe('80');
    expect(formatAverage('79.25')).toBe('79.3');
    expect(formatScore(null)).toBe('–');
  });

  it('compacts counts', () => {
    expect(formatCount(148)).toBe('148');
    expect(formatCount(1200)).toBe('1.2k');
    expect(formatCount(18_400)).toBe('18k');
  });
});
