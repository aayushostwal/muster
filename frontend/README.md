# Muster frontend

Muster's command center is a Next.js App Router application built with
TypeScript, Tailwind CSS, Framer Motion, and TanStack Query. It provides the
project dashboard, capability management, live task board, and streaming agent
console.

Task responses render GitHub-flavored Markdown, including tables, task lists,
links, block quotes, and fenced code blocks with one-click copy. Raw HTML is
not interpreted.

The default task view is a live terminal transcript. It opens at the latest
turn, follows new output while the reader remains near the bottom, and offers
a jump-to-latest control after scrolling into history. Earlier assistant
updates in a turn collapse behind an expandable progress row so the most
recent response remains prominent.

Task metadata and controls share one compact command header: project/task
identity, runtime state, view switching, live connection health, actions, and
an expandable token HUD. Invocation and retry history move to the Run Details
drawer, leaving the full content width for the terminal.

The global Agent, Skill, and MCP registry pages include an import workflow
that scans the local user-level Claude Code and Codex environments through the
native backend. It supports source/type filtering, redacted configuration
previews, collision warnings, bulk selection, and idempotent re-sync.
Capabilities from enabled marketplace packages, including Nexus, appear with
a **Plugin** badge in the same picker; select them and use **Import selected**
exactly like user-authored capabilities.

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

## Global task composer

A persistent compact composer is available on every route. Open it from the
floating action or with `Cmd/Ctrl+J`, type `@` to select one project, and send
the execution brief with Enter. The new task inherits that project's
runtime/model defaults and opens directly in its live task console.

## Runtime configuration

The Docker image reads `MUSTER_API_URL` when the container starts and writes a
small runtime configuration file. One built image can therefore connect to
different backend addresses without being rebuilt. `NEXT_PUBLIC_API_URL` and
the former `VITE_API_URL` name remain accepted as fallbacks.

## Production container

The multi-stage Dockerfile builds Next.js in standalone mode and runs it as an
unprivileged user on port 3000.
