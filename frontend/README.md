# Frontend

React + Vite + TypeScript single-page app — the only UI in Muster. It never
talks to Postgres or spawns agent processes itself; every read and write
goes through the backend's REST API, and every live update (new chat
messages, status changes, retry attempts, token usage) arrives over a
per-task WebSocket rather than polling.

## What it does

Four route-level pages carry the whole app: a Projects list, a Project
detail view (tabbed panels for directory bindings, MCP servers, tools,
artifacts, cron jobs, and secrets — all scoped to that one Project), a
Kanban-style Task board grouped by status, and a Task detail view that is
effectively the whole point of the product: a persistent chat thread against
the running agent, with a composer that can attach media, a model and
context-strategy switcher, a live token-usage indicator, a "compress
context" action, a raw-transcript expand/collapse toggle, and a "Retry now"
banner that appears the moment the backend reports a task backing off after
a transient failure.

State is split cleanly in two directions: server state (Projects, Tasks,
Messages, bindings, etc.) goes through `@tanstack/react-query`, so cache
invalidation is explicit and there's no bespoke global store to keep in
sync; live push events from the WebSocket flow through a small
`useTaskSocket` hook that both updates local UI state directly (status,
token usage) and invalidates the relevant React Query cache so REST and
WebSocket state never disagree.

The typed API client mirrors the backend's Pydantic schemas field-for-field
(snake_case, same enum values), so there's no translation layer to keep in
sync by hand when the backend's data model changes — a type error at compile
time is the signal something drifted.

## Configuring the API URL

- **Dev**: set `VITE_API_URL` in a `.env.local` file, or leave it unset — the
  client falls back to `http://localhost:8080`.
- **Docker / docker-compose**: `VITE_API_URL` is a *runtime* container env
  var, not a build-time one. Since Vite normally only inlines
  `import.meta.env.*` when the bundle is built, a small entrypoint script
  regenerates a `runtime-config.js` file from the live env var on container
  start, and the API client prefers that value over the build-time one — so
  the same built image can point at a different backend per deployment
  without a rebuild.

## Develop

```bash
npm install
npm run dev       # http://localhost:5173
npm run build     # tsc -b && vite build
npx tsc --noEmit  # type-check only
```
