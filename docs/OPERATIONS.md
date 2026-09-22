# Muster — Operations Guide

Covers installing, running, upgrading, and uninstalling a Muster instance.
For command syntax and usage examples, see the dedicated
[`Muster CLI guide`](./CLI.md). For the API/WebSocket/process-manager contract,
see [`SPEC.md`](./SPEC.md).

---

## Pragmatic simplification: no cross-compiled binary

The original PRD described Muster's native service as a single cross-compiled
binary supervised by the OS service manager (launchd on macOS, systemd on
Linux). The backend is a Python/FastAPI app, so instead:

- The "native service" is **`uvicorn` running inside a dedicated virtualenv**
  at `~/.muster/venv`, supervised by a launchd user agent (macOS) or a
  systemd `--user` unit (Linux). `KeepAlive`/`Restart=on-failure` +
  `RunAtLoad`/`WantedBy=default.target` reproduce the "always running,
  restarts on crash, starts on login" behavior a compiled binary would get
  from the same service managers.
- `musterctl` itself is a POSIX shell script, not a compiled CLI, installed
  to `/usr/local/bin/musterctl` (falling back to `~/.local/bin/musterctl` if
  that isn't writable).

This is a deliberate trade-off documented here explicitly rather than a
silent gap versus the PRD: it keeps the install path correct and simple
without standing up a cross-platform binary release pipeline. Postgres and
the frontend still run in Docker (`docker-compose.yml`); only the backend
runs natively, so it has direct filesystem access to any directory bound to
a project without container bind mounts.

---

## Install

```bash
curl -fsSL https://muster.dev/install.sh | bash
```

This runs `scripts/install.sh`, which:

1. Detects OS (darwin/linux) and arch (arm64/amd64).
2. Checks prerequisites: `docker`, `docker compose` (v2 plugin), `python3.12`
   (or `python3 >= 3.11` with a warning), `git`. Missing prerequisites abort
   with an install hint (e.g. `brew install ...` / `apt-get install ...`).
3. Fetches source into `~/.muster/app` — currently via `git clone`/local
   checkout copy (there's no tagged GitHub Release yet); a tarball-download
   path is stubbed in the script for when one exists.
4. Creates `~/.muster/venv` and installs `backend/requirements.txt`.
5. Copies `docker-compose.yml` to `~/.muster/docker-compose.yml` and runs
   `docker compose up -d postgres frontend`.
6. Polls Postgres (`pg_isready`) until ready (default timeout 90s — no fixed
   sleep), then runs `alembic upgrade head` from the venv.
7. Installs and starts the launchd agent (macOS) / systemd `--user` unit
   (Linux), with `__HOME__`/`__VENV__`/`__BACKEND_DIR__` substituted from
   the templates in `scripts/launchd/` and `scripts/systemd/`.
8. Installs `musterctl` to `/usr/local/bin` (or `~/.local/bin`, with a PATH
   warning if needed).
9. Prints a summary: frontend/backend URLs and next commands.

### Local dev (no install.sh)

See the root [`README.md`](../README.md) quick-start section — run Postgres
+ frontend via `docker compose`, and the backend directly with
`uvicorn --reload`.

---

## `musterctl` command reference

Canonical data/config root: `~/.muster` (override with `$MUSTER_HOME`).
See [`CLI.md`](./CLI.md) for detailed behavior, examples, environment
overrides, exit status, safety notes, and troubleshooting.

| Command | Description |
|---|---|
| `musterctl install` | Run/re-run `scripts/install.sh` |
| `musterctl start` | Start backend + postgres + frontend |
| `musterctl stop` | Stop backend + postgres + frontend |
| `musterctl restart` | Restart all three components |
| `musterctl status` | Live status of backend, postgres, frontend |
| `musterctl logs [backend\|frontend\|postgres\|all] [-f]` | Show/follow logs |
| `musterctl upgrade` | Pull source, reinstall venv deps, `alembic upgrade head`, `docker compose pull && up -d`, restart backend — no data touched |
| `musterctl uninstall [--purge] [--yes]` | Stop + remove service files and containers. `--purge` also drops the Postgres volume and `~/.muster/data` (interactive confirmation unless `--yes`) |
| `musterctl db shell` | `psql` shell into the postgres container |
| `musterctl db backup [path]` | `pg_dump`; default path `~/.muster/backups/muster-<timestamp>.sql` |
| `musterctl db restore <path>` | Restore from a `pg_dump` file |
| `musterctl config` | Print resolved ports / data dir / postgres connection info and source |
| `musterctl doctor` | PASS/FAIL checks: configured ports are bound, venv and Compose file are present, and `claude`/`codex` are on `PATH`; reports or skips `config.json` presence |
| `musterctl open` | Open the frontend URL in the default browser (`open` on macOS, `xdg-open` on Linux) |

`musterctl` detects macOS vs Linux at startup and branches all service-
management calls between `launchctl` and `systemctl --user` accordingly.

---

## Upgrade flow

```bash
musterctl upgrade
```

1. `git pull --ff-only` in `~/.muster/app` (or warns and skips if not a git
   checkout — e.g. installed from a future release tarball).
2. Reinstalls `backend/requirements.txt` into the existing venv.
3. `alembic upgrade head`.
4. `docker compose pull && docker compose up -d` for postgres + frontend.
5. Restarts the backend service.

No Postgres data, `~/.muster/data`, or secrets are touched by an upgrade.

## Uninstall flow

```bash
musterctl uninstall            # stop + remove service files and containers, data kept
musterctl uninstall --purge    # also drop the postgres volume and ~/.muster/data
```

`--purge` prompts for interactive confirmation unless `--yes` is also
passed.

---

## Log locations

| Component | macOS | Linux |
|---|---|---|
| Backend | `~/Library/Logs/muster/backend.log` (also `musterctl logs backend`) | `journalctl --user -u muster` (also `musterctl logs backend`) |
| Frontend | `musterctl logs frontend` (`docker compose logs frontend`) | same |
| Postgres | `musterctl logs postgres` (`docker compose logs postgres`) | same |

---

## Service files installed

| Platform | Path |
|---|---|
| macOS launchd agent | `~/Library/LaunchAgents/com.muster.backend.plist` |
| Linux systemd user unit | `~/.config/systemd/user/muster.service` |
| Compose file copy | `~/.muster/docker-compose.yml` |
| Postgres connection info | `~/.muster/muster.env` (`MUSTER_POSTGRES_*`, mode 600) |
| CLI | `/usr/local/bin/musterctl` or `~/.local/bin/musterctl` |

Templates for the service files live in `scripts/launchd/` and
`scripts/systemd/` and are substituted (`__HOME__`, `__VENV__`,
`__BACKEND_DIR__`, plus `__PG_*__` on macOS / `__ENV_FILE__` on Linux) by
`scripts/install.sh` at install time.

`~/.muster/muster.env` is the single source of truth for Postgres
credentials: `install.sh` writes it, `alembic upgrade head` sources it, the
`postgres` container is started with the same `POSTGRES_PASSWORD`, and the
native backend reads it too — inlined into the launchd plist's
`EnvironmentVariables` on macOS (launchd can't source a file), or via
`EnvironmentFile=` on Linux systemd. `app/config.py`'s `Settings` only reads
individual `MUSTER_POSTGRES_HOST/PORT/USER/PASSWORD/DB` vars (env_prefix
`MUSTER_`), not a combined `DATABASE_URL` — anything wiring Postgres
connection info into the backend's environment must use those names.
