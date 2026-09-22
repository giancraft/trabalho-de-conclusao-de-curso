import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      // No container o backend é alcançado pelo nome do serviço; fora dele, por
      // localhost. O compose define VITE_API_PROXY; rodando o Vite no host, o
      // default vale.
      '/api': process.env.VITE_API_PROXY ?? 'http://localhost:8000',
    },
  },
})
