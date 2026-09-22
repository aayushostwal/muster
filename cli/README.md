# CLI (`musterctl`)

`musterctl` is the day-to-day interface for an installed Muster instance. It
normalizes service management across launchd on macOS, systemd user services
on Linux, and Docker Compose for Postgres and the frontend.

The complete user guide—including every command, arguments, environment
overrides, workflows, exit behavior, safety notes, and troubleshooting—is in
[`docs/CLI.md`](../docs/CLI.md).

Quick discovery:

```bash
musterctl help
musterctl doctor
musterctl status
```

The implementation is a Bash script in [`musterctl`](./musterctl).
`~/.muster/` is its default installation and configuration root; set
`MUSTER_HOME` to operate on a different installation. Installation layout and
service internals are documented in
[`docs/OPERATIONS.md`](../docs/OPERATIONS.md).
