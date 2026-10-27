import '@fontsource-variable/bricolage-grotesque';
import '@fontsource/barlow/400.css';
import '@fontsource/barlow/500.css';
import '@fontsource/barlow/600.css';
import '@fontsource/dm-mono/400.css';
import '@fontsource/dm-mono/500.css';
import { themeCss } from '@tricklens/tokens';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { RouterProvider } from 'react-router';
import { Providers } from './app/Providers.tsx';
import { apiMode } from './env.ts';
import { router } from './router.tsx';
import './styles/global.css';

// Theme variables come from @tricklens/tokens, so the web app and the
// future native app share one definition of every color.
const style = document.createElement('style');
style.id = 'tricklens-tokens';
style.textContent = themeCss();
document.head.prepend(style);

async function start() {
  if (apiMode === 'mock') {
    // Loaded only in mock mode, so MSW never ships in a live build's main chunk.
    const { startMockApi } = await import('./app/mocks.ts');
    await startMockApi();
  }
  const root = document.getElementById('root');
  if (!root) throw new Error('#root is missing from index.html');
  createRoot(root).render(
    <StrictMode>
      <Providers>
        <RouterProvider router={router} />
      </Providers>
    </StrictMode>,
  );
}

void start();
