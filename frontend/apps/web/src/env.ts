// Build-time settings, from Vite env vars (override in apps/web/.env.local).
// See docs/components/frontend.md, Mock mode.

/** "mock": MSW answers every API call with sample data. "live": the real FastAPI service. */
export const apiMode: 'mock' | 'live' = import.meta.env.VITE_API_MODE === 'live' ? 'live' : 'mock';

export const apiUrl: string = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';
