#!/usr/bin/env bash
#
# Muster one-shot installer.
#
#   curl -fsSL https://raw.githubusercontent.com/aayushostwal/muster/main/scripts/install.sh | bash
#
# Installs:
#   - ~/.muster/app        the Muster source checkout (backend/ + frontend/ etc.)
#   - ~/.muster/venv        a dedicated Python venv with backend/requirements.txt
#   - ~/.muster/app/docker-compose.yml   Compose definition (postgres+frontend)
#   - launchd agent (macOS) / systemd --user unit (Linux) running uvicorn
#   - musterctl on PATH (/usr/local/bin or ~/.local/bin)
#
# See docs/OPERATIONS.md for the full command reference and
# docs/SPEC.md's "CLI / install contract" for the design rationale.
set -euo pipefail

# ---------------------------------------------------------------------------
# Config / constants
# ---------------------------------------------------------------------------
MUSTER_HOME="${MUSTER_HOME:-$HOME/.muster}"
ENV_FILE="$MUSTER_HOME/muster.env"

installed_value() {
  local key="$1"
  [ -f "$ENV_FILE" ] || return 0
  sed -n "s/^${key}=//p" "$ENV_FILE" | tail -n 1
}

APP_DIR="$MUSTER_HOME/app"
VENV_DIR="$MUSTER_HOME/venv"
BACKEND_DIR="$APP_DIR/backend"
COMPOSE_FILE="$APP_DIR/docker-compose.yml"
REPO_URL="${MUSTER_REPO_URL:-https://github.com/aayushostwal/muster.git}"
REPO_REF="${MUSTER_REPO_REF:-main}"
POSTGRES_HOST="${MUSTER_POSTGRES_HOST:-$(installed_value MUSTER_POSTGRES_HOST)}"
POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${MUSTER_POSTGRES_PORT:-$(installed_value MUSTER_POSTGRES_PORT)}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_USER="${MUSTER_POSTGRES_USER:-$(installed_value MUSTER_POSTGRES_USER)}"
POSTGRES_USER="${POSTGRES_USER:-muster}"
POSTGRES_PASSWORD="${MUSTER_POSTGRES_PASSWORD:-$(installed_value MUSTER_POSTGRES_PASSWORD)}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-muster}"
POSTGRES_DB="${MUSTER_POSTGRES_DB:-$(installed_value MUSTER_POSTGRES_DB)}"
POSTGRES_DB="${POSTGRES_DB:-muster}"
BACKEND_PORT="${MUSTER_BACKEND_PORT:-$(installed_value MUSTER_BACKEND_PORT)}"
BACKEND_PORT="${BACKEND_PORT:-8080}"
FRONTEND_PORT="${MUSTER_FRONTEND_PORT:-$(installed_value MUSTER_FRONTEND_PORT)}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
BIN_DIR="${MUSTER_BIN_DIR:-}"
PYTHON_VERSION="${MUSTER_PYTHON_VERSION:-3.12}"
UV_VERSION="${MUSTER_UV_VERSION:-0.12.17}"
UV_BIN="$MUSTER_HOME/tools/uv"
UV_PYTHON_DIR="$MUSTER_HOME/python"
UV_CACHE_DIR="$MUSTER_HOME/cache/uv"
PYTHON_BIN=""
USE_MANAGED_PYTHON="0"
SOURCE_STAGE=""
ENV_STAGE=""

# Directory this script lives in — used when running from a local checkout
# (`bash scripts/install.sh`) rather than piped from curl, so we can copy
# repo files directly instead of re-cloning over the network.
SCRIPT_SOURCE="${BASH_SOURCE[0]:-}"
LOCAL_REPO_ROOT=""
if [ -n "$SCRIPT_SOURCE" ] && [ -f "$SCRIPT_SOURCE" ]; then
  SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_SOURCE")" && pwd -P)"
  LOCAL_REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"
fi

info()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m==> WARNING:\033[0m %s\n' "$*" >&2; }
error() { printf '\033[1;31m==> ERROR:\033[0m %s\n' "$*" >&2; }
die()   { error "$*"; exit 1; }

cleanup() {
  if [ -n "$SOURCE_STAGE" ] && [ -d "$SOURCE_STAGE" ]; then
    rm -rf "$SOURCE_STAGE"
  fi
  if [ -n "$ENV_STAGE" ] && [ -f "$ENV_STAGE" ]; then
    rm -f "$ENV_STAGE"
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

validate_port() {
  local name="$1" value="$2"
  case "$value" in
    ''|*[!0-9]*) die "$name must be an integer between 1 and 65535 (got: $value)" ;;
  esac
  [ "$value" -ge 1 ] && [ "$value" -le 65535 ] || die "$name must be between 1 and 65535 (got: $value)"
}

validate_settings() {
  case "$MUSTER_HOME" in
    ''|/|"$HOME") die "MUSTER_HOME must point to a dedicated installation directory" ;;
    /*) : ;;
    *) die "MUSTER_HOME must be an absolute path (got: $MUSTER_HOME)" ;;
  esac
  case "$BIN_DIR" in
    ''|/*) : ;;
    *) die "MUSTER_BIN_DIR must be an absolute path (got: $BIN_DIR)" ;;
  esac
  validate_port "MUSTER_POSTGRES_PORT" "$POSTGRES_PORT"
  validate_port "MUSTER_BACKEND_PORT" "$BACKEND_PORT"
  validate_port "MUSTER_FRONTEND_PORT" "$FRONTEND_PORT"
  [ -n "$POSTGRES_USER" ] || die "MUSTER_POSTGRES_USER must not be empty"
  [ -n "$POSTGRES_DB" ] || die "MUSTER_POSTGRES_DB must not be empty"
  [ -n "$REPO_URL" ] || die "MUSTER_REPO_URL must not be empty"
  [ -n "$REPO_REF" ] || die "MUSTER_REPO_REF must not be empty"
  case "$PYTHON_VERSION" in
    ''|*[!0-9.]*) die "MUSTER_PYTHON_VERSION must be a numeric Python version (got: $PYTHON_VERSION)" ;;
  esac
  case "$UV_VERSION" in
    ''|*[!0-9.]*) die "MUSTER_UV_VERSION must be a numeric uv version (got: $UV_VERSION)" ;;
  esac
  local value
  for value in "$MUSTER_HOME" "$BIN_DIR" "$POSTGRES_HOST" "$POSTGRES_USER" "$POSTGRES_PASSWORD" "$POSTGRES_DB"; do
    case "$value" in
      *$'\n'*|*$'\r'*) die "Postgres settings must not contain newlines" ;;
    esac
  done
}

# ---------------------------------------------------------------------------
# 1. Detect OS / arch
# ---------------------------------------------------------------------------
# The backend is Python, not a cross-compiled binary, so OS/arch detection
# doesn't pick a download artifact the way it would for a Go/Rust release.
# It's still needed to: (a) branch launchd vs systemd service install,
# (b) pick correct Docker Desktop / Docker Engine install hints, and
# (c) validate the platform is supported before we do any work. See the
# "Pragmatic simplification" note in docs/SPEC.md's CLI/install contract.
detect_os() {
  case "$(uname -s)" in
    Darwin) echo "darwin" ;;
    Linux)  echo "linux" ;;
    *) die "Unsupported OS: $(uname -s). Muster supports macOS and Linux." ;;
  esac
}

detect_arch() {
  case "$(uname -m)" in
    arm64|aarch64) echo "arm64" ;;
    x86_64|amd64)  echo "amd64" ;;
    *) die "Unsupported architecture: $(uname -m)." ;;
  esac
}

OS="$(detect_os)"
ARCH="$(detect_arch)"
info "Detected platform: ${OS}/${ARCH}"
validate_settings

# ---------------------------------------------------------------------------
# 2. Prerequisite checks
# ---------------------------------------------------------------------------
have() { command -v "$1" >/dev/null 2>&1; }

check_prereqs() {
  local missing=0

  if ! have docker; then
    error "docker is required but not found."
    case "$OS" in
      darwin) echo "    Install: brew install --cask docker   (or https://docker.com/products/docker-desktop)" ;;
      linux)  echo "    Install: curl -fsSL https://get.docker.com | sh   (or your distro's docker-ce package)" ;;
    esac
    missing=1
  fi

  if have docker && ! docker compose version >/dev/null 2>&1; then
    error "'docker compose' (v2 plugin) is required but not found."
    echo "    Install: https://docs.docker.com/compose/install/"
    missing=1
  fi

  if have python3.12; then
    PYTHON_BIN="python3.12"
  elif have python3; then
    local ver
    ver="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
    local major minor
    major="${ver%%.*}"
    minor="${ver##*.}"
    if [ "$major" -eq 3 ] && [ "$minor" -ge 11 ]; then
      PYTHON_BIN="python3"
      warn "python3.12 not found; falling back to python3 ($ver). Muster is developed against 3.12 — things should work on 3.11+ but this is a fallback, not the primary target."
    else
      warn "System python3 is $ver; Muster will provision an isolated Python $PYTHON_VERSION runtime."
      USE_MANAGED_PYTHON="1"
    fi
  else
    warn "No system Python found; Muster will provision an isolated Python $PYTHON_VERSION runtime."
    USE_MANAGED_PYTHON="1"
  fi

  if [ "$USE_MANAGED_PYTHON" = "1" ] && ! have curl; then
    error "curl is required to provision Muster's isolated Python runtime."
    missing=1
  fi

  if ! have git; then
    error "git is required but not found."
    case "$OS" in
      darwin) echo "    Install: brew install git   (or: xcode-select --install)" ;;
      linux)  echo "    Install: sudo apt-get install git" ;;
    esac
    missing=1
  fi

  [ "$missing" -eq 0 ] || die "Missing prerequisites — install the above and re-run."
}

check_prereqs
if [ "$USE_MANAGED_PYTHON" = "1" ]; then
  info "Prerequisites OK (Python $PYTHON_VERSION will be managed under $MUSTER_HOME)"
else
  info "Prerequisites OK (python: $PYTHON_BIN)"
fi

mkdir -p "$MUSTER_HOME"

# ---------------------------------------------------------------------------
# 3. Fetch source into ~/.muster/app
# ---------------------------------------------------------------------------
canonical_target() {
  local path="$1" parent name
  parent="$(dirname "$path")"
  name="$(basename "$path")"
  mkdir -p "$parent"
  printf '%s/%s\n' "$(cd "$parent" && pwd -P)" "$name"
}

stage_local_source() {
  local source="$1"
  info "Installing from local checkout at $source"
  mkdir -p "$SOURCE_STAGE"
  if have rsync; then
    rsync -a --delete \
      --exclude '.git' \
      --exclude '.venv' \
      --exclude 'venv' \
      --exclude 'node_modules' \
      --exclude '.next' \
      --exclude '.nexus' \
      --exclude '__pycache__' \
      --exclude '.pytest_cache' \
      --exclude '.DS_Store' \
      "$source"/ "$SOURCE_STAGE"/
  else
    cp -R "$source"/. "$SOURCE_STAGE"/
    rm -rf \
      "$SOURCE_STAGE/.git" \
      "$SOURCE_STAGE/.venv" \
      "$SOURCE_STAGE/venv" \
      "$SOURCE_STAGE/backend/.venv" \
      "$SOURCE_STAGE/backend/.pytest_cache" \
      "$SOURCE_STAGE/frontend/node_modules" \
      "$SOURCE_STAGE/frontend/.next" \
      "$SOURCE_STAGE/.nexus"
  fi
}

activate_staged_source() {
  local previous=""
  [ -f "$SOURCE_STAGE/backend/app/main.py" ] || die "Staged source is missing backend/app/main.py"
  [ -f "$SOURCE_STAGE/docker-compose.yml" ] || die "Staged source is missing docker-compose.yml"

  if [ -e "$APP_DIR" ]; then
    previous="$MUSTER_HOME/.app.previous.$$"
    rm -rf "$previous"
    mv "$APP_DIR" "$previous"
  fi

  if mv "$SOURCE_STAGE" "$APP_DIR"; then
    SOURCE_STAGE=""
    [ -z "$previous" ] || rm -rf "$previous"
  else
    [ -z "$previous" ] || mv "$previous" "$APP_DIR"
    die "Could not activate the staged source tree"
  fi
}

fetch_source() {
  local requested_source="${MUSTER_SOURCE_DIR:-$LOCAL_REPO_ROOT}"
  local source_path="" app_path
  app_path="$(canonical_target "$APP_DIR")"

  if [ -n "${MUSTER_SOURCE_DIR:-}" ] && { [ ! -f "$MUSTER_SOURCE_DIR/backend/app/main.py" ] || [ ! -f "$MUSTER_SOURCE_DIR/docker-compose.yml" ]; }; then
    die "MUSTER_SOURCE_DIR is not a Muster checkout: $MUSTER_SOURCE_DIR"
  fi

  if [ -n "$requested_source" ] && [ -f "$requested_source/backend/app/main.py" ] && [ -f "$requested_source/docker-compose.yml" ]; then
    source_path="$(cd "$requested_source" && pwd -P)"
  fi

  # `musterctl install` executes the copy already under APP_DIR. Treating that
  # as a local source would make rsync/cp mirror the directory onto itself.
  # Fetch a fresh remote tree instead. Also reject an install root nested in a
  # separate local source checkout, which would recurse while copying.
  if [ -n "$source_path" ] && [ "$source_path" = "$app_path" ]; then
    source_path=""
  elif [ -n "$source_path" ]; then
    case "$app_path/" in
      "$source_path"/*) die "MUSTER_HOME must not be inside the source checkout ($source_path)" ;;
    esac
  fi

  SOURCE_STAGE="$MUSTER_HOME/.app.stage.$$"
  rm -rf "$SOURCE_STAGE"

  if [ -n "$source_path" ]; then
    stage_local_source "$source_path"
  else
    info "Fetching $REPO_URL ($REPO_REF)"
    git clone --depth 1 --branch "$REPO_REF" -- "$REPO_URL" "$SOURCE_STAGE"
  fi
  activate_staged_source
}

fetch_source
[ -f "$BACKEND_DIR/requirements.txt" ] || die "backend/requirements.txt not found under $APP_DIR — install source looks incomplete."

# Persist the settings shared by musterctl, Docker Compose, Alembic, and the
# rendered native backend service only after the new source is active. The
# file is deliberately parsed as data and is never shell-sourced.
info "Writing $ENV_FILE"
ENV_STAGE="$MUSTER_HOME/.muster.env.$$"
( umask 077 && cat > "$ENV_STAGE" <<EOF
MUSTER_POSTGRES_HOST=${POSTGRES_HOST}
MUSTER_POSTGRES_PORT=${POSTGRES_PORT}
MUSTER_POSTGRES_USER=${POSTGRES_USER}
MUSTER_POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
MUSTER_POSTGRES_DB=${POSTGRES_DB}
MUSTER_BACKEND_PORT=${BACKEND_PORT}
MUSTER_FRONTEND_PORT=${FRONTEND_PORT}
EOF
)
mv "$ENV_STAGE" "$ENV_FILE"
ENV_STAGE=""
chmod 600 "$ENV_FILE"

# ---------------------------------------------------------------------------
# 4. Install musterctl before long-running setup
# ---------------------------------------------------------------------------
install_cli() {
  local src="$APP_DIR/cli/musterctl" target_dir
  [ -f "$src" ] || die "cli/musterctl not found at $src"
  chmod +x "$src"

  if [ -n "$BIN_DIR" ]; then
    target_dir="$BIN_DIR"
  elif [ -d /usr/local/bin ] && [ -w /usr/local/bin ]; then
    target_dir="/usr/local/bin"
  elif [ ! -e /usr/local/bin ] && [ -d /usr/local ] && [ -w /usr/local ]; then
    target_dir="/usr/local/bin"
  else
    target_dir="$HOME/.local/bin"
  fi

  mkdir -p "$target_dir"
  cp "$src" "$target_dir/musterctl"
  chmod +x "$target_dir/musterctl"
  info "Installed musterctl to $target_dir/musterctl"

  if [ "$target_dir" != "/usr/local/bin" ]; then
    case ":$PATH:" in
      *":$target_dir:"*) : ;;
      *) warn "$target_dir is not on your PATH. Add this to your shell rc file:
       export PATH=\"$target_dir:\$PATH\"" ;;
    esac
  fi
}

install_cli

# ---------------------------------------------------------------------------
# 5. Create venv + install backend deps
# ---------------------------------------------------------------------------
bootstrap_uv() {
  if [ -x "$UV_BIN" ]; then
    info "Using managed uv at $UV_BIN"
    return 0
  fi

  info "Installing uv $UV_VERSION into $MUSTER_HOME/tools"
  mkdir -p "$MUSTER_HOME/tools"
  curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" \
    | env UV_UNMANAGED_INSTALL="$MUSTER_HOME/tools" sh
  [ -x "$UV_BIN" ] || die "uv installation did not create $UV_BIN"
}

create_managed_venv() {
  bootstrap_uv
  info "Creating venv with managed Python $PYTHON_VERSION at $VENV_DIR"
  env \
    UV_CACHE_DIR="$UV_CACHE_DIR" \
    UV_NO_CONFIG=1 \
    UV_MANAGED_PYTHON=1 \
    UV_PYTHON_INSTALL_DIR="$UV_PYTHON_DIR" \
    "$UV_BIN" venv --clear --seed --managed-python \
      --python "$PYTHON_VERSION" "$VENV_DIR"
}

if [ "$USE_MANAGED_PYTHON" = "1" ]; then
  create_managed_venv
else
  info "Creating venv at $VENV_DIR"
  if ! "$PYTHON_BIN" -m venv --clear "$VENV_DIR"; then
    warn "$PYTHON_BIN could not create a venv; falling back to managed Python $PYTHON_VERSION."
    rm -rf "$VENV_DIR"
    create_managed_venv
  fi
fi

"$VENV_DIR/bin/python" -c \
  'import sys; assert sys.version_info >= (3, 11), f"Python 3.11+ required, got {sys.version}"'
"$VENV_DIR/bin/pip" install --upgrade pip >/dev/null
info "Installing backend/requirements.txt into venv"
"$VENV_DIR/bin/pip" install -r "$BACKEND_DIR/requirements.txt"

# ---------------------------------------------------------------------------
# 6. Bring up postgres + frontend
# ---------------------------------------------------------------------------
[ -f "$COMPOSE_FILE" ] || die "docker-compose.yml not found at $COMPOSE_FILE"

compose() {
  (
    cd "$APP_DIR"
    env \
      "MUSTER_POSTGRES_PORT=$POSTGRES_PORT" \
      "MUSTER_POSTGRES_USER=$POSTGRES_USER" \
      "MUSTER_POSTGRES_PASSWORD=$POSTGRES_PASSWORD" \
      "MUSTER_POSTGRES_DB=$POSTGRES_DB" \
      "MUSTER_FRONTEND_PORT=$FRONTEND_PORT" \
      "MUSTER_API_URL=http://localhost:$BACKEND_PORT" \
      docker compose --project-name muster -f "$COMPOSE_FILE" "$@"
  )
}

info "Starting postgres + frontend via docker compose"
compose up -d --build postgres frontend

# ---------------------------------------------------------------------------
# 7. Wait for Postgres to be ready (poll, don't sleep a fixed time)
# ---------------------------------------------------------------------------
wait_for_postgres() {
  local timeout="${MUSTER_PG_WAIT_TIMEOUT:-90}"
  local waited=0
  case "$timeout" in
    ''|*[!0-9]*) die "MUSTER_PG_WAIT_TIMEOUT must be a positive integer (got: $timeout)" ;;
  esac
  [ "$timeout" -gt 0 ] || die "MUSTER_PG_WAIT_TIMEOUT must be greater than zero"
  info "Waiting for Postgres to become ready (timeout ${timeout}s)..."
  while [ "$waited" -lt "$timeout" ]; do
    if compose exec -T postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then
      info "Postgres is ready."
      return 0
    fi
    sleep 2
    waited=$((waited + 2))
  done
  die "Postgres did not become ready within ${timeout}s. Check: musterctl logs postgres"
}

wait_for_postgres

# ---------------------------------------------------------------------------
# 8. Run migrations
# ---------------------------------------------------------------------------
info "Running alembic upgrade head"
# Settings (backend/app/config.py) is a pydantic-settings model with
# env_prefix="MUSTER_" and individual postgres_host/port/user/password/db
# fields — it does not read a DATABASE_URL. Export the same MUSTER_POSTGRES_*
# vars written to $ENV_FILE so alembic's env.py builds the same DSN the
# running backend will. Values are passed directly instead of shell-sourcing
# the EnvironmentFile, so passwords containing shell metacharacters are safe.
(
  cd "$BACKEND_DIR"
  env \
    "MUSTER_POSTGRES_HOST=$POSTGRES_HOST" \
    "MUSTER_POSTGRES_PORT=$POSTGRES_PORT" \
    "MUSTER_POSTGRES_USER=$POSTGRES_USER" \
    "MUSTER_POSTGRES_PASSWORD=$POSTGRES_PASSWORD" \
    "MUSTER_POSTGRES_DB=$POSTGRES_DB" \
    "$VENV_DIR/bin/python" -m alembic upgrade head
)

# ---------------------------------------------------------------------------
# 9. Install + start the backend service (launchd / systemd)
# ---------------------------------------------------------------------------
render_service_template() {
  local kind="$1" template="$2" destination="$3"
  local service_path="$VENV_DIR/bin:$HOME/.local/bin:$HOME/.npm-global/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

  RENDER_KIND="$kind" \
  RENDER_HOME="$HOME" \
  RENDER_VENV="$VENV_DIR" \
  RENDER_BACKEND_DIR="$BACKEND_DIR" \
  RENDER_BACKEND_PORT="$BACKEND_PORT" \
  RENDER_PATH="$service_path" \
  RENDER_ENV_FILE="$ENV_FILE" \
  RENDER_PG_HOST="$POSTGRES_HOST" \
  RENDER_PG_PORT="$POSTGRES_PORT" \
  RENDER_PG_USER="$POSTGRES_USER" \
  RENDER_PG_PASSWORD="$POSTGRES_PASSWORD" \
  RENDER_PG_DB="$POSTGRES_DB" \
    "$VENV_DIR/bin/python" - "$template" "$destination" <<'PY'
import html
import os
from pathlib import Path
import re
import sys

kind, source, destination = os.environ["RENDER_KIND"], Path(sys.argv[1]), Path(sys.argv[2])
values = {
    "HOME": os.environ["RENDER_HOME"],
    "VENV": os.environ["RENDER_VENV"],
    "BACKEND_DIR": os.environ["RENDER_BACKEND_DIR"],
    "BACKEND_PORT": os.environ["RENDER_BACKEND_PORT"],
    "PATH": os.environ["RENDER_PATH"],
    "ENV_FILE": os.environ["RENDER_ENV_FILE"],
    "PG_HOST": os.environ["RENDER_PG_HOST"],
    "PG_PORT": os.environ["RENDER_PG_PORT"],
    "PG_USER": os.environ["RENDER_PG_USER"],
    "PG_PASSWORD": os.environ["RENDER_PG_PASSWORD"],
    "PG_DB": os.environ["RENDER_PG_DB"],
}

def escape(value: str) -> str:
    if kind == "plist":
        return html.escape(value, quote=True)
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")

rendered = source.read_text()
for key, value in values.items():
    rendered = rendered.replace(f"__{key}__", escape(value))

unresolved = sorted(set(re.findall(r"__[A-Z0-9_]+__", rendered)))
if unresolved:
    raise SystemExit(f"unresolved service template placeholders: {', '.join(unresolved)}")

destination.write_text(rendered)
PY
}

install_service() {
  local whoami_user home_dir
  whoami_user="$(whoami)"
  home_dir="$HOME"

  if [ "$OS" = "darwin" ]; then
    mkdir -p "$home_dir/Library/Logs/muster"
    mkdir -p "$home_dir/Library/LaunchAgents"
    local template="$APP_DIR/scripts/launchd/com.muster.backend.plist.template"
    local dest="$home_dir/Library/LaunchAgents/com.muster.backend.plist"
    [ -f "$template" ] || die "launchd template not found at $template"

    render_service_template "plist" "$template" "$dest"
    chmod 600 "$dest"  # contains the Postgres password

    info "Loading launchd agent com.muster.backend"
    launchctl unload "$dest" >/dev/null 2>&1 || true
    launchctl load -w "$dest"
  else
    mkdir -p "$home_dir/.config/systemd/user"
    local template="$APP_DIR/scripts/systemd/muster.service.template"
    local dest="$home_dir/.config/systemd/user/muster.service"
    [ -f "$template" ] || die "systemd template not found at $template"

    render_service_template "systemd" "$template" "$dest"
    chmod 600 "$dest"  # contains the Postgres password

    info "Enabling+starting systemd --user muster.service"
    systemctl --user daemon-reload
    systemctl --user enable --now muster.service
  fi

  info "Service installed for user: $whoami_user"
}

install_service

# ---------------------------------------------------------------------------
# 10. Summary
# ---------------------------------------------------------------------------
cat <<EOF

Muster is installed.

  Frontend:  http://localhost:${FRONTEND_PORT}
  Backend:   http://localhost:${BACKEND_PORT}
  Postgres:  localhost:${POSTGRES_PORT} (user: ${POSTGRES_USER}, db: ${POSTGRES_DB})

  musterctl status        # check backend + frontend + postgres
  musterctl logs backend -f
  musterctl doctor        # verify ports, venv, CLIs on PATH

Data/config root: $MUSTER_HOME
Docs: $APP_DIR/docs/CLI.md

EOF
