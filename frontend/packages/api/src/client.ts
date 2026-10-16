import createClient, { type Client, type Middleware } from 'openapi-fetch';
import type { paths } from './schema.ts';

export type ApiClient = Client<paths>;

export interface ApiClientOptions {
  /** Origin of the FastAPI service, e.g. http://localhost:8000. */
  baseUrl: string;
  /** Returns the Cognito ID token, or null when signed out. */
  getToken?: () => string | null | Promise<string | null>;
  fetch?: typeof globalThis.fetch;
}

/** An HTTP error from the API, carrying FastAPI's `detail` when there is one. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: unknown,
  ) {
    super(typeof detail === 'string' ? detail : `API request failed with ${status}`);
    this.name = 'ApiError';
  }
}

/**
 * A typed client for every route in the OpenAPI spec. Paths, params, bodies
 * and responses are all checked against schema.ts, so an API change that
 * breaks the frontend fails `pnpm typecheck` after `make web-types`.
 */
export function createApiClient({ baseUrl, getToken, fetch }: ApiClientOptions): ApiClient {
  const client = createClient<paths>({ baseUrl, ...(fetch ? { fetch } : {}) });
  const auth: Middleware = {
    async onRequest({ request }) {
      const token = await getToken?.();
      if (token) request.headers.set('Authorization', `Bearer ${token}`);
      return request;
    },
  };
  client.use(auth);
  return client;
}

/** Unwraps an openapi-fetch result: the data, or an ApiError. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.error !== undefined || result.data === undefined) {
    const detail = (result.error as { detail?: unknown } | undefined)?.detail ?? result.error;
    throw new ApiError(result.response.status, detail);
  }
  return result.data;
}
