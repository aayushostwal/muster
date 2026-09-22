# Install scripts

`install.sh` is the one-shot installer (`curl -fsSL .../install.sh | bash`)
and the only place that actually builds `~/.muster/` from scratch: it
detects OS/arch, checks for Docker, Python 3.12+ (falling back to 3.11 with
a warning), and git; fetches the source (currently a git-clone/local-rsync
flow, with a tarball-based GitHub Releases flow stubbed in for once a real
release pipeline exists); creates a dedicated Python venv and installs the
backend into it; brings up Postgres and the frontend via `docker compose`,
polling `pg_isready` rather than sleeping a fixed duration; runs the Alembic
migration; installs and starts the platform-appropriate background service;
and installs `musterctl` onto `PATH`.

The most important thing it owns is `~/.muster/muster.env` — the single
source of truth for Postgres credentials. It's written once by `install.sh`
and then read by three different consumers that all need to agree on the
same values: the `alembic upgrade head` step, the Postgres container itself
(via an exported `POSTGRES_PASSWORD`), and the native backend service. That
last one is why the two platform templates below aren't identical in how
they consume it.

`launchd/com.muster.backend.plist.template` and
`systemd/muster.service.template` are the actual service definitions,
`sed`-substituted by `install.sh` at install time rather than hand-edited.
They intentionally differ in how they pick up Postgres credentials: launchd
has no notion of an external env file, so `install.sh` inlines the literal
`MUSTER_POSTGRES_*` values directly into the plist's `EnvironmentVariables`
dict; systemd natively supports `EnvironmentFile=`, so the Linux unit just
points at `~/.muster/muster.env` directly. Both give the same
always-running / restart-on-crash / start-on-login behavior a cross-compiled
binary would get from its OS service manager — see the "Pragmatic
simplification" note in `docs/OPERATIONS.md` for why the backend is a
supervised `uvicorn` process in a venv rather than a compiled binary.
