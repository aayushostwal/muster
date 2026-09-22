# Muster CLI guide

`musterctl` operates an installed Muster instance. It provides one interface
for the native backend service and the Docker-managed frontend and Postgres
services on both macOS and Linux.

This guide documents the commands implemented by [`cli/musterctl`](../cli/musterctl).
For development commands used from a repository checkout, run `make help`
instead; those Make targets are not part of `musterctl`.

## Install and verify

The production-style installer installs `musterctl` into `/usr/local/bin` when
that directory is writable, otherwise into `~/.local/bin`.

```bash
curl -fsSL https://muster.dev/install.sh | bash
command -v musterctl
musterctl help
```

If `command -v` cannot find the fallback installation, add it to your shell
path and restart the shell:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

The CLI supports macOS and Linux. It controls the backend with launchd on
macOS and a systemd user service on Linux. Docker Compose controls Postgres
and the frontend on both platforms.

## First-use workflow

```bash
# Start every Muster component.
musterctl start

# Check the running services and required agent CLIs.
musterctl status
musterctl doctor

# Open the command center in the default browser.
musterctl open
```

Run `musterctl help`, `musterctl --help`, or `musterctl -h` at any time to
print the command summary.

## Commands at a glance

| Command | Purpose |
|---|---|
| `musterctl install` | Re-run the installer from the installed source tree. |
| `musterctl start` | Start the backend, Postgres, and frontend. |
| `musterctl stop` | Stop all three components without deleting their data. |
| `musterctl restart` | Restart all three components. |
| `musterctl status` | Show backend service and container status. |
| `musterctl logs [target] [-f]` | Show recent logs or follow a component. |
| `musterctl upgrade` | Update source and dependencies, migrate the database, and restart Muster. |
| `musterctl uninstall [--purge] [--yes]` | Remove runtime services and containers, optionally deleting persisted data. |
| `musterctl db shell` | Open an interactive Postgres shell. |
| `musterctl db backup [path]` | Write a SQL backup. |
| `musterctl db restore <path>` | Apply a SQL backup to the Muster database. |
| `musterctl config` | Print the paths, ports, database identity, and detected OS used by the CLI. |
| `musterctl doctor` | Run installation, port, and agent-command checks. |
| `musterctl open` | Open the frontend in the default browser. |
| `musterctl help` | Print CLI usage. |

## Service lifecycle

### `musterctl start`

Starts the native backend service, then starts the `postgres` and `frontend`
Compose services in the background.

```bash
musterctl start
```

Calling `start` when the services are already running is safe.

### `musterctl stop`

Stops the backend and Compose services. Containers and persisted database
data remain available for the next start.

```bash
musterctl stop
```

### `musterctl restart`

Restarts the backend service and all services in the installed Compose file.

```bash
musterctl restart
```

### `musterctl status`

Shows whether the launchd/systemd backend service is active, followed by
`docker compose ps` output for Postgres and the frontend.

```bash
musterctl status
```

Use `musterctl doctor` when a component is shown as inactive and
`musterctl logs <target>` for the underlying error.

## Logs

The log target is one of `backend`, `frontend`, `postgres`, or `all`. Omitting
the target defaults to `all`. Without `-f`, the command prints the most recent
200 lines.

```bash
musterctl logs                 # recent backend and container logs
musterctl logs backend         # backend only
musterctl logs frontend        # frontend container only
musterctl logs postgres        # Postgres container only
musterctl logs all             # all components
musterctl logs backend -f      # follow backend logs
musterctl logs frontend -f     # follow frontend logs
musterctl logs all -f          # print backend history, then follow containers
```

When following all services, backend history is printed first and the
container stream remains attached. Press `Ctrl-C` to stop following logs;
this does not stop Muster.

Backend logs come from `~/Library/Logs/muster/backend.log` on macOS and the
systemd user journal on Linux. Frontend and Postgres logs come from Docker.

## Diagnostics and configuration

### `musterctl doctor`

Runs PASS/FAIL checks for:

- listeners on the configured backend, frontend, and Postgres ports;
- the dedicated Python virtual environment;
- the installed Compose file;
- the presence of `claude` and `codex` on `PATH`.

If `~/.muster/config.json` exists, `doctor` reports that it is readable;
otherwise that check is skipped. It does not validate HTTP responses, CLI
authentication, agent CLI versions, database credentials, or every configured
directory.

```bash
musterctl doctor
```

Because port listeners are part of the check, run `doctor` after `start` when
validating a stopped installation. The command exits non-zero when any
required check fails, so it can be used in local automation:

```bash
if ! musterctl doctor; then
  musterctl status
  musterctl logs all
fi
```

### `musterctl config`

Prints the resolved installation root, source directory, virtual environment,
Compose file, service ports, Postgres user/database, and operating system.
Passwords are never printed.

```bash
musterctl config
```

The default installation root is `~/.muster`. The following environment
variables override values used by `musterctl` for the current invocation:

| Variable | Default | Used for |
|---|---|---|
| `MUSTER_HOME` | `~/.muster` | Installation, configuration, backup, and Compose paths. |
| `MUSTER_BACKEND_PORT` | `8080` | `doctor` checks. |
| `MUSTER_FRONTEND_PORT` | `3000` | `doctor` checks and `open`. |
| `MUSTER_POSTGRES_PORT` | `5432` | `doctor` checks. |
| `MUSTER_POSTGRES_USER` | `muster` | Database shell, backup, and restore. |
| `MUSTER_POSTGRES_DB` | `muster` | Database shell, backup, and restore. |

Set the same overrides consistently when the installation itself uses custom
ports or database names. For example:

```bash
MUSTER_HOME="$HOME/muster-test" MUSTER_FRONTEND_PORT=3100 musterctl config
MUSTER_HOME="$HOME/muster-test" MUSTER_FRONTEND_PORT=3100 musterctl open
```

## Database commands

### `musterctl db shell`

Opens `psql` inside the running Postgres container using the configured user
and database.

```bash
musterctl db shell
```

Exit the shell with `\q`.

### `musterctl db backup [path]`

Creates a plain SQL dump. When no path is supplied, the CLI writes a
timestamped file under `~/.muster/backups/`. Parent directories are created
automatically.

```bash
musterctl db backup
musterctl db backup "$HOME/backups/muster-before-upgrade.sql"
```

The Postgres container must be running. Treat backup files as sensitive:
project secrets and operational data may be present in the database.

### `musterctl db restore <path>`

Feeds a plain SQL dump into the running Muster database.

```bash
musterctl stop
musterctl start
musterctl db backup "$HOME/backups/muster-before-restore.sql"
musterctl db restore "$HOME/backups/muster-known-good.sql"
```

Restore can overwrite or conflict with existing records. Take a backup first,
use a dump from a compatible Muster version, and avoid starting new tasks
during the restore.

## Upgrade

```bash
musterctl db backup
musterctl upgrade
musterctl doctor
```

`upgrade` performs these steps:

1. Runs `git pull --ff-only` in the installed source checkout. Installs made
   without a Git checkout skip this step with a warning.
2. Reinstalls backend dependencies into the existing virtual environment.
3. Applies all pending Alembic database migrations.
4. Pulls available container images, then recreates/starts Compose services.
5. Restarts the native backend service.

The command does not intentionally delete user data, but a database backup is
recommended before every upgrade because migrations change the schema.

## Re-run the installer

```bash
musterctl install
```

This executes `scripts/install.sh` from the installed source tree. Use it to
repair or re-provision an existing installation. If the source tree under
`~/.muster/app` is missing, run the bootstrap installer again instead.

## Uninstall and purge

```bash
musterctl uninstall
musterctl uninstall --purge
musterctl uninstall --purge --yes
```

- `uninstall` stops the backend, removes its launchd/systemd service file,
  and removes the Compose containers and network. Persisted data is retained.
- `--purge` additionally removes the Postgres Compose volume and
  `~/.muster/data`.
- `--yes` skips the destructive confirmation and only has an effect with
  `--purge`. Use it only in non-interactive automation where data loss is
  intended.

The CLI executable, installed source, virtual environment, Compose file, and
environment file are retained so the installation can be repaired or
reinstalled. Purged Postgres and `~/.muster/data` content cannot be recovered
unless it was backed up separately.

## Exit status and troubleshooting

`musterctl` returns `0` when a command completes successfully. Unknown
commands, missing required arguments, failed service operations, and failed
`doctor` checks return non-zero. With no command, the CLI prints usage and
returns `1`; explicit help returns `0`.

Common recovery sequence:

```bash
musterctl config
musterctl status
musterctl doctor
musterctl logs all
```

If Docker commands fail, verify that Docker is running and that
`docker compose version` succeeds. If only agent invocations fail, verify the
relevant CLI is both installed and authenticated in the same user environment
as the Muster backend service:

```bash
claude --version
codex --version
```

For service file locations and installation internals, see the
[`Operations Guide`](./OPERATIONS.md).
