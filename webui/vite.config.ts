import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

// Dev: `npm run dev` proxies API + WS to the FastAPI backend on :8765.
// Prod: `npm run build` emits ../src/airscope/web/static/, served by FastAPI.
export default defineConfig(() => {
  return defineConfig({
    plugins: [svelte()],
    server: {
      port: 5173,
      proxy: {
        '/api': { target: 'http://127.0.0.1:8765', changeOrigin: true },
        '/api/ws': { target: 'ws://127.0.0.1:8765', ws: true }
      }
    },
    build: {
      outDir: '../src/airscope/web/static',
      emptyOutDir: true
    }
  });
});
