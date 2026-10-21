import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// The Python transport replaces "__ATLAS_BASE__/" in index.html with the real mount path
// (e.g. "/admin/") at request time, so one build works under any prefix.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: '__ATLAS_BASE__/',
  build: {
    outDir: '../src/atlas/static',
    emptyOutDir: true,
    modulePreload: false,
    rollupOptions: { output: { codeSplitting: false } },
  },
  server: {
    proxy: { '/admin/_api': 'http://127.0.0.1:8000' },
  },
})
