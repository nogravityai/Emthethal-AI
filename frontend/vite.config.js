import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      }
    }
  },
  build: {
    chunkSizeWarningLimit: 800, // Increase warning limit to 800 kB
    rollupOptions: {
      output: {
        manualChunks(id) {
          // Separate node_modules packages to avoid a single giant vendor chunk
          if (id.includes('node_modules')) {
            if (id.includes('framer-motion')) {
              return 'framer-motion';
            }
            if (id.includes('react') || id.includes('scheduler')) {
              return 'react-core';
            }
            if (id.includes('axios') || id.includes('zustand')) {
              return 'network-state';
            }
            return 'vendor'; // fallback for other dependencies
          }
        }
      }
    }
  }
})
