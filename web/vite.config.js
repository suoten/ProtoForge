import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd() + '/..', 'PROTOFORGE_')
  const backendPort = env.PROTOFORGE_PORT || 8000
  const backendHost = env.PROTOFORGE_HOST || 'localhost'

  return {
    plugins: [vue()],
    server: {
      port: 3000,
      proxy: {
        '/api': `http://${backendHost}:${backendPort}`,
        '/ws': {
          target: `ws://${backendHost}:${backendPort}`,
          ws: true,
        },
      },
    },
  }
})
