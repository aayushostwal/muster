# CLI (`musterctl`)

A single POSIX shell script that is the one command a Muster user is
expected to run day-to-day — `musterctl` exists so nobody has to remember
whether the backend is a `launchctl` thing or the frontend is a `docker
compose` thing. It detects macOS vs. Linux once at the top and branches
service management (`launchctl` vs. `systemctl --user`) accordingly, while
`docker compose` handles Postgres and the frontend the same way on both
platforms.

It covers the full lifecycle: `install` (delegates to
`scripts/install.sh`), `start` / `stop` / `restart` for all three
components together, `status` and `logs [backend|frontend|postgres|all]`,
`upgrade` (pulls the latest source, reinstalls backend deps, runs
migrations, and refreshes the containers without touching any data),
`uninstall [--purge]` (the `--purge` flag additionally drops the Postgres
volume and `~/.muster/data`, gated behind a confirmation prompt), database
convenience commands (`db shell`, `db backup [path]`, `db restore <path>`),
`config` (prints the resolved ports/data-dir/Postgres connection and where
they came from), `doctor` (checks ports, venv presence, directory-binding
readability, and whether `claude`/`codex` are actually on `PATH` — the CLI's
own healthcheck, since a silently missing agent binary is otherwise a
confusing failure deep inside the process manager), and `open` (launches the
frontend in the default browser).

`~/.muster/` is the canonical root for everything it manages — data,
config, and the `muster.env` file that keeps Postgres credentials consistent
between the database container, `alembic`, and the native backend service
(see `scripts/README.md`).
