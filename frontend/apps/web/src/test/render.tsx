import { render } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { Providers } from '../app/Providers.tsx';
import { routes } from '../router.tsx';

/** Renders the whole app (real routes, providers and mock API) at a URL. */
export function renderApp(url = '/feed') {
  const router = createMemoryRouter(routes, { initialEntries: [url] });
  const user = userEvent.setup();
  const view = render(
    <Providers>
      <RouterProvider router={router} />
    </Providers>,
  );
  return { ...view, router, user };
}
