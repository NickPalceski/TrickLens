import { handlers } from '@tricklens/api/mocks';
import { setupWorker } from 'msw/browser';

/** Starts the mock API in the browser (public/mockServiceWorker.js). */
export async function startMockApi() {
  const worker = setupWorker(...handlers);
  await worker.start({
    // Fonts, images and Vite's own requests aren't API calls: let them through.
    onUnhandledFrame: 'bypass',
    quiet: true,
  });
  console.info('[TrickLens] mock API on: every API call is answered with sample data');
}
