import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  build: {
    outDir: '../public',
    emptyOutDir: false,
    rollupOptions: {
      output: {
        manualChunks: (id: string) => id.includes('three') ? 'three' : undefined,
      },
    },
  },
  server: {
    proxy: {
      '/api': 'http://localhost:3000',
    },
  },
})
