import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { handlers, resetMockDb } from '@tricklens/api/mocks';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll } from 'vitest';

// jsdom has no object URLs; the upload flow makes one for the preview.
URL.createObjectURL ??= () => 'blob:test-preview';
URL.revokeObjectURL ??= () => {};

// The same mock handlers the browser uses, so tests run the real client.
export const server = setupServer(...handlers);

beforeAll(() => server.listen({ onUnhandledFrame: 'error' }));
afterEach(() => {
  cleanup();
  server.resetHandlers();
  resetMockDb();
  localStorage.clear();
  document.documentElement.removeAttribute('data-theme');
});
afterAll(() => server.close());
