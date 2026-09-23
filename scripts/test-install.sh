#!/usr/bin/env bash
set -euo pipefail

# The Makefile exports local-development database values. Keep this smoke test
# hermetic so a caller's Muster configuration cannot override its fixtures.
unset MUSTER_HOME MUSTER_SOURCE_DIR MUSTER_BIN_DIR MUSTER_REPO_URL MUSTER_REPO_REF
unset MUSTER_POSTGRES_HOST MUSTER_POSTGRES_PORT MUSTER_POSTGRES_USER
unset MUSTER_POSTGRES_PASSWORD MUSTER_POSTGRES_DB MUSTER_BACKEND_PORT
unset MUSTER_FRONTEND_PORT MUSTER_PG_WAIT_TIMEOUT MUSTER_API_URL
unset MUSTER_PYTHON_VERSION MUSTER_UV_VERSION

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/muster-install-test.XXXXXX")"
FAKE_BIN="$TEST_ROOT/bin"
CALL_LOG="$TEST_ROOT/calls.log"
REAL_PYTHON="$(command -v python3)"
REAL_GIT="$(command -v git)"
export CALL_LOG REAL_PYTHON REAL_GIT REPO_ROOT

cleanup() { rm -rf "$TEST_ROOT"; }
trap cleanup EXIT

mkdir -p "$FAKE_BIN"

cat > "$FAKE_BIN/uname" <<'EOF'
#!/usr/bin/env bash
case "${1:-}" in
  -s) printf '%s\n' "${FAKE_UNAME_S:-Darwin}" ;;
  -m) printf '%s\n' "${FAKE_UNAME_M:-arm64}" ;;
  *) printf '%s\n' "${FAKE_UNAME_S:-Darwin}" ;;
esac
EOF

cat > "$FAKE_BIN/docker" <<'EOF'
#!/usr/bin/env bash
printf 'docker|pg=%s|frontend=%s|api=%s|%s\n' \
  "${MUSTER_POSTGRES_PORT:-}" "${MUSTER_FRONTEND_PORT:-}" \
  "${MUSTER_API_URL:-}" "$*" >> "$CALL_LOG"
exit 0
EOF

cat > "$FAKE_BIN/launchctl" <<'EOF'
#!/usr/bin/env bash
printf 'launchctl|%s\n' "$*" >> "$CALL_LOG"
exit 0
EOF

cat > "$FAKE_BIN/systemctl" <<'EOF'
#!/usr/bin/env bash
printf 'systemctl|%s\n' "$*" >> "$CALL_LOG"
exit 0
EOF

cat > "$FAKE_BIN/git" <<'EOF'
#!/usr/bin/env bash
if [ "${1:-}" = "clone" ]; then
  destination="${*: -1}"
  printf 'git|clone|%s\n' "$destination" >> "$CALL_LOG"
  mkdir -p "$destination"
  cp -R "$REPO_ROOT"/. "$destination"/
  rm -rf "$destination/.git" "$destination/.nexus" \
    "$destination/backend/.venv" "$destination/frontend/node_modules" \
    "$destination/frontend/.next"
  exit 0
fi
exec "$REAL_GIT" "$@"
EOF

cat > "$FAKE_BIN/python3" <<'EOF'
#!/usr/bin/env bash
if [ "${1:-}" = "-c" ]; then
  if [ -n "${FAKE_PYTHON_VERSION:-}" ]; then
    printf '%s\n' "$FAKE_PYTHON_VERSION"
    exit 0
  fi
  exec "$REAL_PYTHON" "$@"
fi
if [ "${1:-}" = "-m" ] && [ "${2:-}" = "venv" ]; then
  destination="${*: -1}"
  mkdir -p "$destination/bin"
  cat > "$destination/bin/pip" <<'PIP'
#!/usr/bin/env bash
printf 'pip|%s\n' "$*" >> "$CALL_LOG"
exit 0
PIP
  cat > "$destination/bin/python" <<'PYTHON'
#!/usr/bin/env bash
if [ "${1:-}" = "-m" ] && [ "${2:-}" = "alembic" ]; then
  printf 'alembic|%s\n' "$*" >> "$CALL_LOG"
  exit "${FAKE_ALEMBIC_EXIT:-0}"
fi
if [ "${1:-}" = "-c" ] && [[ "${2:-}" == *"sys.version_info"* ]]; then
  exit 0
fi
exec "$REAL_PYTHON" "$@"
PYTHON
  chmod +x "$destination/bin/pip" "$destination/bin/python"
  exit 0
fi
exec "$REAL_PYTHON" "$@"
EOF

cat > "$FAKE_BIN/curl" <<'EOF'
#!/usr/bin/env bash
printf 'curl|%s\n' "$*" >> "$CALL_LOG"
cat <<'INSTALLER'
#!/usr/bin/env sh
set -eu
mkdir -p "$UV_UNMANAGED_INSTALL"
cat > "$UV_UNMANAGED_INSTALL/uv" <<'UV'
#!/usr/bin/env bash
set -euo pipefail
printf 'uv|python_dir=%s|%s\n' "${UV_PYTHON_INSTALL_DIR:-}" "$*" >> "$CALL_LOG"
if [ "${1:-}" = "venv" ]; then
  destination="${*: -1}"
  mkdir -p "${UV_PYTHON_INSTALL_DIR:?}"
  python3 -m venv "$destination"
  exit 0
fi
exit 1
UV
chmod +x "$UV_UNMANAGED_INSTALL/uv"
INSTALLER
EOF

chmod +x "$FAKE_BIN"/*
ln -s python3 "$FAKE_BIN/python3.12"

assert_file() {
  [ -f "$1" ] || { printf 'Expected file: %s\n' "$1" >&2; exit 1; }
}

assert_contains() {
  local file="$1" expected="$2"
  grep -F -- "$expected" "$file" >/dev/null || {
    printf 'Expected %s to contain: %s\n' "$file" "$expected" >&2
    exit 1
  }
}

assert_mode_600() {
  "$REAL_PYTHON" - "$1" <<'PY'
import os
import stat
import sys

mode = stat.S_IMODE(os.stat(sys.argv[1]).st_mode)
assert mode == 0o600, f"expected mode 600 for {sys.argv[1]}, got {mode:o}"
PY
}

run_install() {
  local os="$1" home="$2" backend_port="$3" frontend_port="$4" postgres_port="$5" password="$6"
  local python_version="${7:-}"
  local alembic_exit="${8:-0}"
  mkdir -p "$home"
  env \
    HOME="$home" \
    PATH="$FAKE_BIN:$PATH" \
    FAKE_UNAME_S="$os" \
    FAKE_PYTHON_VERSION="$python_version" \
    FAKE_ALEMBIC_EXIT="$alembic_exit" \
    MUSTER_HOME="$home/.muster" \
    MUSTER_SOURCE_DIR="$REPO_ROOT" \
    MUSTER_BIN_DIR="$home/bin" \
    MUSTER_BACKEND_PORT="$backend_port" \
    MUSTER_FRONTEND_PORT="$frontend_port" \
    MUSTER_POSTGRES_PORT="$postgres_port" \
    MUSTER_POSTGRES_USER="test_user" \
    MUSTER_POSTGRES_PASSWORD="$password" \
    MUSTER_POSTGRES_DB="test_db" \
    bash "$REPO_ROOT/scripts/install.sh" >/dev/null
}

MAC_HOME="$TEST_ROOT/mac home"
run_install Darwin "$MAC_HOME" 8181 3100 55432 "p&<>\$x"
assert_file "$MAC_HOME/.muster/app/docker-compose.yml"
assert_file "$MAC_HOME/.muster/muster.env"
assert_file "$MAC_HOME/Library/LaunchAgents/com.muster.backend.plist"
assert_file "$MAC_HOME/bin/musterctl"
assert_mode_600 "$MAC_HOME/.muster/muster.env"
assert_mode_600 "$MAC_HOME/Library/LaunchAgents/com.muster.backend.plist"
[ ! -e "$MAC_HOME/.muster/docker-compose.yml" ]
assert_contains "$MAC_HOME/.muster/muster.env" "MUSTER_BACKEND_PORT=8181"
assert_contains "$MAC_HOME/.muster/muster.env" "MUSTER_POSTGRES_PASSWORD=p&<>\$x"

"$REAL_PYTHON" - "$MAC_HOME/Library/LaunchAgents/com.muster.backend.plist" <<'PY'
import plistlib
import sys

with open(sys.argv[1], "rb") as stream:
    service = plistlib.load(stream)
assert service["ProgramArguments"][-1] == "8181"
assert service["EnvironmentVariables"]["MUSTER_POSTGRES_PASSWORD"] == "p&<>$x"
assert ".local/bin" in service["EnvironmentVariables"]["PATH"]
PY

MAC_CONFIG="$TEST_ROOT/mac-config.txt"
env HOME="$MAC_HOME" PATH="$FAKE_BIN:$MAC_HOME/bin:$PATH" FAKE_UNAME_S=Darwin \
  MUSTER_HOME="$MAC_HOME/.muster" "$MAC_HOME/bin/musterctl" config > "$MAC_CONFIG"
assert_contains "$MAC_CONFIG" "backend port:      8181"
assert_contains "$MAC_CONFIG" "$MAC_HOME/.muster/app/docker-compose.yml  (found)"

# Reinstalling from APP_DIR must fetch into a separate stage and must preserve
# the saved configuration when no overrides are supplied.
env HOME="$MAC_HOME" PATH="$FAKE_BIN:$MAC_HOME/bin:$PATH" FAKE_UNAME_S=Darwin \
  MUSTER_HOME="$MAC_HOME/.muster" MUSTER_SOURCE_DIR="$MAC_HOME/.muster/app" \
  MUSTER_BIN_DIR="$MAC_HOME/bin" \
  bash "$MAC_HOME/.muster/app/scripts/install.sh" >/dev/null
assert_contains "$CALL_LOG" "git|clone|"
assert_contains "$MAC_HOME/.muster/muster.env" "MUSTER_BACKEND_PORT=8181"
assert_contains "$MAC_HOME/.muster/muster.env" "MUSTER_POSTGRES_PASSWORD=p&<>\$x"

LINUX_HOME="$TEST_ROOT/linux home"
run_install Linux "$LINUX_HOME" 8282 3200 56432 'p"word%\tail'
UNIT="$LINUX_HOME/.config/systemd/user/muster.service"
assert_file "$UNIT"
assert_mode_600 "$UNIT"
assert_contains "$UNIT" "--port 8282"
assert_contains "$UNIT" 'Environment="MUSTER_POSTGRES_PASSWORD=p\"word%%\\tail"'
if grep -E '__[A-Z0-9_]+__' "$UNIT" >/dev/null; then
  printf 'Unresolved placeholder in %s\n' "$UNIT" >&2
  exit 1
fi
assert_contains "$CALL_LOG" "systemctl|--user enable --now muster.service"
assert_contains "$CALL_LOG" "docker|pg=56432|frontend=3200|api=http://localhost:8282|"

# The recovery CLI must be available even when a later installation step
# fails, so users can rerun install or inspect status without finding a shell
# script inside the application checkout.
FAILED_HOME="$TEST_ROOT/failed install home"
if run_install Darwin "$FAILED_HOME" 8484 3400 58432 "failed-password" "" 42; then
  printf 'Expected a simulated migration failure\n' >&2
  exit 1
fi
assert_file "$FAILED_HOME/bin/musterctl"
[ ! -e "$FAILED_HOME/Library/LaunchAgents/com.muster.backend.plist" ]

# A host with only Apple's Python 3.9 must get an isolated managed runtime
# instead of being told to replace or upgrade the system Python.
rm "$FAKE_BIN/python3.12"
LEGACY_PYTHON_HOME="$TEST_ROOT/legacy python home"
run_install Darwin "$LEGACY_PYTHON_HOME" 8383 3300 57432 "legacy-password" 3.9
assert_file "$LEGACY_PYTHON_HOME/.muster/tools/uv"
assert_file "$LEGACY_PYTHON_HOME/.muster/venv/bin/python"
assert_contains "$CALL_LOG" "curl|-LsSf https://astral.sh/uv/0.12.17/install.sh"
assert_contains "$CALL_LOG" "uv|python_dir=$LEGACY_PYTHON_HOME/.muster/python|venv --clear --seed --managed-python --python 3.12 $LEGACY_PYTHON_HOME/.muster/venv"

printf 'installer smoke tests passed\n'
