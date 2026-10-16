import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  server: {
    // 0.0.0.0 so the dev server is reachable from outside the `web`
    // container; port 3000 is the API's default CORS origin (config.py).
    host: '0.0.0.0',
    port: 3000,
    strictPort: true,
  },
  preview: { host: '0.0.0.0', port: 3000 },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: { modules: { classNameStrategy: 'non-scoped' } },
  },
});
