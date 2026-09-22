# Muster frontend

React + Vite + TypeScript SPA for the Muster control plane.

## Develop

```bash
npm install
npm run dev
```

Opens on `http://localhost:5173` (Vite's default dev port) and talks to the
API defined by `VITE_API_URL`.

## Configuring the API URL

- **Dev**: set `VITE_API_URL` in a `.env.local` file (e.g.
  `VITE_API_URL=http://localhost:8080`), or leave it unset — the client
  falls back to `http://localhost:8080`.
- **Docker / docker-compose**: `VITE_API_URL` is passed as a runtime
  container env var (see `docker-compose.yml`, service `frontend`). Since
  Vite normally only inlines `import.meta.env.*` at build time,
  `docker-entrypoint.sh` regenerates `dist/runtime-config.js` from the env
  var on container start, and `src/api/client.ts` prefers that
  runtime-injected value over the build-time one. This lets the same image
  point at different backends without a rebuild.

## Build

```bash
npm run build     # tsc -b && vite build, outputs to dist/
npm run preview   # serves dist/ on port 3000
```

## Type-check only

```bash
npx tsc --noEmit
```

## Structure

```
src/
  api/          typed REST client (client.ts) + WebSocket client (ws.ts)
  types/        API entity types mirroring backend/app/db/models.py
  pages/        route-level components (Projects, Project detail, Board, Task detail)
  components/   shared UI (Layout, ChatThread, Composer, project tab panels)
  styles/       global.css
```
