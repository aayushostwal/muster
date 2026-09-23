# Install scripts

`install.sh` is the one-shot installer (`curl -fsSL .../install.sh | bash`)
and the only place that actually builds `~/.muster/` from scratch: it
detects OS/arch and checks for Docker and git; fetches the source through a
staged Git clone or local checkout copy; creates a dedicated Python venv and
installs the backend into it; brings up Postgres and the frontend via
`docker compose`, polling `pg_isready` rather than sleeping a fixed duration;
runs the Alembic migration; installs and starts the platform-appropriate
background service; and installs `musterctl` onto `PATH`.

Python is self-contained at install time. A compatible host Python (3.11+) is
used only to create `~/.muster/venv`; when the host Python is missing or too
old, the installer bootstraps a pinned uv binary into `~/.muster/tools` and
uses uv's managed Python 3.12 under `~/.muster/python`. The system Python is
never upgraded or replaced.

Source is copied or cloned into a staging directory and activated only after
its required files are verified. This keeps the previous app tree intact when
a download/copy fails and prevents `musterctl install` from copying the
installed tree onto itself. `MUSTER_SOURCE_DIR` selects a local checkout
explicitly; otherwise a piped or installed copy fetches
`aayushostwal/muster` from GitHub.

The most important thing it owns is `~/.muster/muster.env` — the persisted
source of truth for Postgres credentials and installed ports. `install.sh`
passes those values directly to Alembic and Docker Compose, renders them into
the native backend service, and `musterctl` reads them for later operations
without printing the stored password.

`launchd/com.muster.backend.plist.template` and
`systemd/muster.service.template` are the actual service definitions,
rendered by `install.sh` at install time rather than hand-edited. The renderer
escapes values for XML on macOS and systemd unit syntax on Linux, then inlines
the `MUSTER_POSTGRES_*` settings into the service environment. Both give the
same always-running / restart-on-crash / start-on-login behavior a cross-compiled
binary would get from its OS service manager — see the "Pragmatic
simplification" note in `docs/OPERATIONS.md` for why the backend is a
supervised `uvicorn` process in a venv rather than a compiled binary.
