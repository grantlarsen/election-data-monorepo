import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    // Windows bind mounts can miss filesystem events inside Docker Desktop.
    watch: { usePolling: process.env.VITE_USE_POLLING === '1', interval: 300 },
    proxy: {
      '/api': { target: process.env.API_PROXY_TARGET ?? 'http://127.0.0.1:8000' },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    restoreMocks: true,
  },
});
