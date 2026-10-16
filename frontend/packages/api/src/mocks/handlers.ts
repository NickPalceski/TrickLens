// Mock API handlers (MSW). They intercept the real client's requests, so
// the app runs its real data-fetching code against fake responses. Paths
// match the FastAPI routes on any origin ("*/..."), so the same handlers
// serve the browser (any VITE_API_URL) and the Node tests.
import { delay, HttpResponse, http } from 'msw';
import { me, users } from './data.ts';

/** Small, realistic latency so loading states are visible in the prototype. */
const LATENCY_MS = 250;

export const handlers = [
  http.get('*/users/me', async () => {
    await delay(LATENCY_MS);
    return HttpResponse.json(me);
  }),

  http.get('*/users/:username', async ({ params }) => {
    await delay(LATENCY_MS);
    const user = users[String(params.username)];
    return user ? HttpResponse.json(user) : HttpResponse.json({ detail: 'user not found' }, { status: 404 });
  }),
];
