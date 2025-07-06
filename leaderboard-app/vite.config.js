import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path' // Import the 'path' module

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      // This alias tells Vite that whenever it sees '@/' in an import path,
      // it should look inside the 'src' directory.
      '@': path.resolve(__dirname, './src'),
    },
  },
})