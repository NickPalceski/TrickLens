import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { handlers } from '@tricklens/api/mocks';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll } from 'vitest';

// The same mock handlers the browser uses, so tests run the real client.
export const server = setupServer(...handlers);

beforeAll(() => server.listen({ onUnhandledFrame: 'error' }));
afterEach(() => {
  cleanup();
  server.resetHandlers();
  localStorage.clear();
  document.documentElement.removeAttribute('data-theme');
});
afterAll(() => server.close());
