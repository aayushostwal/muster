# Muster frontend

Muster's command center is a Next.js App Router application built with
TypeScript, Tailwind CSS, Framer Motion, and TanStack Query. It provides the
project dashboard, capability management, live task board, and streaming agent
console.

## Local development

```bash
npm ci
npm run dev
```

The development server runs on `http://localhost:3000`. The backend defaults
to `http://localhost:8080`; set `NEXT_PUBLIC_API_URL` to use another address.

## Quality checks

```bash
npm run typecheck
npm run lint
npm run build
# or all three
npm run check
```

## Runtime configuration

The Docker image reads `MUSTER_API_URL` when the container starts and writes a
small runtime configuration file. One built image can therefore connect to
different backend addresses without being rebuilt. `NEXT_PUBLIC_API_URL` and
the former `VITE_API_URL` name remain accepted as fallbacks.

## Production container

The multi-stage Dockerfile builds Next.js in standalone mode and runs it as an
unprivileged user on port 3000.
