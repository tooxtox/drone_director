import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

const backend = process.env.TS_API_TARGET || 'http://127.0.0.1:8011';
export default defineConfig({
  plugins: [vue()],
  server: { port: 5173, strictPort: true, proxy: {
    '/api': { target: backend, ws: true },
  } },
  build: { rollupOptions: { output: { manualChunks: {
    three: ['three'], charts: ['echarts'], vue: ['vue'],
  } } } },
});
