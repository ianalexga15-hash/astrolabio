import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// Sin secretos en el cliente: el panel solo usa la sesión de cookie del backend.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { '/api': 'http://127.0.0.1:8770' } },
  build: { outDir: 'dist', sourcemap: false },
});
