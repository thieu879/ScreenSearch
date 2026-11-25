import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  envDir: '../',
  plugins: [react(), tailwindcss()],
  server: {
    // Let a `cloudflared` quick tunnel reach this server. Vite checks the Host header against an
    // allowlist and answers anything else with "Blocked request. This host is not allowed." — so
    // without this line every tester in the 7–12 August feedback sessions sees that string instead
    // of the app, and the tunnel looks broken when it is working perfectly.
    //
    // Scoped to the quick-tunnel domain rather than `true`, which would disable the check outright.
    // The check is a DNS-rebinding defence, and this is a dev server that proxies to :8000.
    allowedHosts: ['.trycloudflare.com'],
    // Proxy the API in development so the browser only ever talks to one origin. That removes CORS
    // from the dev loop entirely and — more usefully — lets the relative `thumb_url` the server
    // returns work unmodified, instead of every component having to know a base URL.
    //
    // The backend's CORS_ORIGINS already lists :5173, so running without the proxy also works. This
    // just means a misconfigured origin cannot break local development.
    // `127.0.0.1`, not `localhost`, and that is not cosmetic. `make run` binds uvicorn to
    // `0.0.0.0`, which is IPv4 only, while Node on Windows resolves `localhost` to `::1` first —
    // so the proxy dials an address nothing is listening on and the browser sees
    // `[vite] http proxy error` with `ECONNREFUSED`, which reads as a broken API rather than a
    // resolution mismatch. It cost a teammate an afternoon on 2026-08-14.
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/health': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
