#!/usr/bin/env bash
#
# Muster one-shot installer.
#
#   curl -fsSL https://muster.dev/install.sh | bash
#
# Installs:
#   - ~/.muster/app        the Muster source checkout (backend/ + frontend/ etc.)
#   - ~/.muster/venv        a dedicated Python venv with backend/requirements.txt
#   - ~/.muster/docker-compose.yml   copy of the repo's compose file (postgres+frontend)
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
APP_DIR="$MUSTER_HOME/app"
VENV_DIR="$MUSTER_HOME/venv"
BACKEND_DIR="$APP_DIR/backend"
COMPOSE_FILE="$MUSTER_HOME/docker-compose.yml"
REPO_URL="${MUSTER_REPO_URL:-https://github.com/muster-dev/muster.git}"
REPO_REF="${MUSTER_REPO_REF:-main}"
POSTGRES_HOST="${MUSTER_POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${MUSTER_POSTGRES_PORT:-5432}"
POSTGRES_USER="${MUSTER_POSTGRES_USER:-muster}"
POSTGRES_PASSWORD="${MUSTER_POSTGRES_PASSWORD:-muster}"
POSTGRES_DB="${MUSTER_POSTGRES_DB:-muster}"
ENV_FILE="$MUSTER_HOME/muster.env"

# Directory this script lives in — used when running from a local checkout
# (`bash scripts/install.sh`) rather than piped from curl, so we can copy
# repo files directly instead of re-cloning over the network.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
LOCAL_REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

info()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m==> WARNING:\033[0m %s\n' "$*" >&2; }
error() { printf '\033[1;31m==> ERROR:\033[0m %s\n' "$*" >&2; }
die()   { error "$*"; exit 1; }

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
      error "python3 >= 3.11 is required (found $ver)."
      case "$OS" in
        darwin) echo "    Install: brew install python@3.12" ;;
        linux)  echo "    Install: sudo apt-get install python3.12 python3.12-venv   (or your distro equivalent)" ;;
      esac
      missing=1
    fi
  else
    error "python3 is required but not found."
    case "$OS" in
      darwin) echo "    Install: brew install python@3.12" ;;
      linux)  echo "    Install: sudo apt-get install python3.12 python3.12-venv" ;;
    esac
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
info "Prerequisites OK (python: $PYTHON_BIN)"

mkdir -p "$MUSTER_HOME"

# ---------------------------------------------------------------------------
# 2b. Write the env file the backend, alembic, launchd (via sed) and systemd
#     (via EnvironmentFile=) all read Postgres connection info from. This is
#     the single source of truth — nothing here is guessed from
#     docker-compose.yml's own defaults, since a user overriding
#     MUSTER_POSTGRES_* must have both docker-compose and the native backend
#     agree.
# ---------------------------------------------------------------------------
info "Writing $ENV_FILE"
cat > "$ENV_FILE" <<EOF
MUSTER_POSTGRES_HOST=${POSTGRES_HOST}
MUSTER_POSTGRES_PORT=${POSTGRES_PORT}
MUSTER_POSTGRES_USER=${POSTGRES_USER}
MUSTER_POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
MUSTER_POSTGRES_DB=${POSTGRES_DB}
EOF
chmod 600 "$ENV_FILE"

# ---------------------------------------------------------------------------
# 3. Fetch source into ~/.muster/app
# ---------------------------------------------------------------------------
fetch_source() {
  # --- FOR NOW: git-clone based flow -----------------------------------
  # There is no tagged GitHub Release yet, so we clone (or, if this script
  # is itself running from a local checkout, rsync that checkout) into
  # ~/.muster/app. This is the path actually exercised today.
  if [ -f "$LOCAL_REPO_ROOT/backend/app/main.py" ] && [ -f "$LOCAL_REPO_ROOT/docker-compose.yml" ]; then
    info "Installing from local checkout at $LOCAL_REPO_ROOT"
    mkdir -p "$APP_DIR"
    # Mirror the local repo in, excluding VCS/venv/node cruft.
    if have rsync; then
      rsync -a --delete \
        --exclude '.git' \
        --exclude '.venv' \
        --exclude 'venv' \
        --exclude 'node_modules' \
        --exclude '__pycache__' \
        "$LOCAL_REPO_ROOT"/ "$APP_DIR"/
    else
      rm -rf "$APP_DIR"
      mkdir -p "$APP_DIR"
      cp -R "$LOCAL_REPO_ROOT"/. "$APP_DIR"/
    fi
  elif [ -d "$APP_DIR/.git" ]; then
    info "Updating existing checkout at $APP_DIR"
    git -C "$APP_DIR" fetch --depth 1 origin "$REPO_REF"
    git -C "$APP_DIR" checkout "$REPO_REF"
    git -C "$APP_DIR" reset --hard "origin/$REPO_REF"
  else
    info "Cloning $REPO_URL ($REPO_REF) into $APP_DIR"
    rm -rf "$APP_DIR"
    git clone --depth 1 --branch "$REPO_REF" "$REPO_URL" "$APP_DIR"
  fi

  # --- FUTURE: tarball-download flow (once GitHub Releases exist) ------
  # When a real release pipeline exists, replace the block above with
  # something like:
  #
  #   RELEASE_URL="https://github.com/muster-dev/muster/releases/download/${MUSTER_VERSION}/muster-${MUSTER_VERSION}.tar.gz"
  #   curl -fsSL "$RELEASE_URL" -o "$MUSTER_HOME/muster.tar.gz"
  #   mkdir -p "$APP_DIR"
  #   tar -xzf "$MUSTER_HOME/muster.tar.gz" -C "$APP_DIR" --strip-components=1
  #   rm -f "$MUSTER_HOME/muster.tar.gz"
  #
  # Left commented out (not implemented) until a release artifact exists.
  :
}

fetch_source
[ -f "$BACKEND_DIR/requirements.txt" ] || die "backend/requirements.txt not found under $APP_DIR — install source looks incomplete."

# ---------------------------------------------------------------------------
# 4. Create venv + install backend deps
# ---------------------------------------------------------------------------
info "Creating venv at $VENV_DIR"
"$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip >/dev/null
info "Installing backend/requirements.txt into venv"
"$VENV_DIR/bin/pip" install -r "$BACKEND_DIR/requirements.txt"

# ---------------------------------------------------------------------------
# 5. Copy docker-compose.yml and bring up postgres + frontend
# ---------------------------------------------------------------------------
info "Copying docker-compose.yml to $COMPOSE_FILE"
cp "$APP_DIR/docker-compose.yml" "$COMPOSE_FILE"

info "Starting postgres + frontend via docker compose"
# docker-compose.yml reads POSTGRES_PASSWORD (unprefixed) from the shell
# environment it's invoked in; export it here so it matches the
# MUSTER_POSTGRES_PASSWORD the native backend uses (see $ENV_FILE above).
( cd "$MUSTER_HOME" && POSTGRES_PASSWORD="$POSTGRES_PASSWORD" MUSTER_API_URL="http://localhost:8080" docker compose -f "$COMPOSE_FILE" up -d postgres frontend )

# ---------------------------------------------------------------------------
# 6. Wait for Postgres to be ready (poll, don't sleep a fixed time)
# ---------------------------------------------------------------------------
wait_for_postgres() {
  local timeout="${MUSTER_PG_WAIT_TIMEOUT:-90}"
  local waited=0
  info "Waiting for Postgres to become ready (timeout ${timeout}s)..."
  while [ "$waited" -lt "$timeout" ]; do
    if ( cd "$MUSTER_HOME" && docker compose -f "$COMPOSE_FILE" exec -T postgres pg_isready -U "$POSTGRES_USER" >/dev/null 2>&1 ); then
      info "Postgres is ready."
      return 0
    fi
    sleep 2
    waited=$((waited + 2))
  done
  die "Postgres did not become ready within ${timeout}s. Check: docker compose -f $COMPOSE_FILE logs postgres"
}

wait_for_postgres

# ---------------------------------------------------------------------------
# 7. Run migrations
# ---------------------------------------------------------------------------
info "Running alembic upgrade head"
# Settings (backend/app/config.py) is a pydantic-settings model with
# env_prefix="MUSTER_" and individual postgres_host/port/user/password/db
# fields — it does not read a DATABASE_URL. Export the same MUSTER_POSTGRES_*
# vars written to $ENV_FILE so alembic's env.py builds the same DSN the
# running backend will.
( cd "$BACKEND_DIR" && set -a && . "$ENV_FILE" && set +a && "$VENV_DIR/bin/python" -m alembic upgrade head )

# ---------------------------------------------------------------------------
# 8. Install + start the backend service (launchd / systemd)
# ---------------------------------------------------------------------------
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

    sed \
      -e "s#__HOME__#${home_dir}#g" \
      -e "s#__VENV__#${VENV_DIR}#g" \
      -e "s#__BACKEND_DIR__#${BACKEND_DIR}#g" \
      -e "s#__PG_HOST__#${POSTGRES_HOST}#g" \
      -e "s#__PG_PORT__#${POSTGRES_PORT}#g" \
      -e "s#__PG_USER__#${POSTGRES_USER}#g" \
      -e "s#__PG_PASSWORD__#${POSTGRES_PASSWORD}#g" \
      -e "s#__PG_DB__#${POSTGRES_DB}#g" \
      "$template" > "$dest"
    chmod 600 "$dest"  # contains the Postgres password

    info "Loading launchd agent com.muster.backend"
    launchctl unload "$dest" >/dev/null 2>&1 || true
    launchctl load -w "$dest"
  else
    mkdir -p "$home_dir/.config/systemd/user"
    local template="$APP_DIR/scripts/systemd/muster.service.template"
    local dest="$home_dir/.config/systemd/user/muster.service"
    [ -f "$template" ] || die "systemd template not found at $template"

    sed \
      -e "s#__HOME__#${home_dir}#g" \
      -e "s#__VENV__#${VENV_DIR}#g" \
      -e "s#__BACKEND_DIR__#${BACKEND_DIR}#g" \
      -e "s#__ENV_FILE__#${ENV_FILE}#g" \
      "$template" > "$dest"

    info "Enabling+starting systemd --user muster.service"
    systemctl --user daemon-reload
    systemctl --user enable --now muster.service
  fi

  info "Service installed for user: $whoami_user"
}

install_service

# ---------------------------------------------------------------------------
# 9. Install musterctl on PATH
# ---------------------------------------------------------------------------
install_cli() {
  local src="$APP_DIR/cli/musterctl"
  [ -f "$src" ] || die "cli/musterctl not found at $src"
  chmod +x "$src"

  if [ -w /usr/local/bin ] 2>/dev/null || { [ ! -e /usr/local/bin ] && mkdir -p /usr/local/bin 2>/dev/null; }; then
    cp "$src" /usr/local/bin/musterctl
    chmod +x /usr/local/bin/musterctl
    info "Installed musterctl to /usr/local/bin/musterctl"
  else
    mkdir -p "$HOME/.local/bin"
    cp "$src" "$HOME/.local/bin/musterctl"
    chmod +x "$HOME/.local/bin/musterctl"
    info "Installed musterctl to $HOME/.local/bin/musterctl"
    case ":$PATH:" in
      *":$HOME/.local/bin:"*) : ;;
      *) warn "$HOME/.local/bin is not on your PATH. Add this to your shell rc file:
       export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
    esac
  fi
}

install_cli

# ---------------------------------------------------------------------------
# 10. Summary
# ---------------------------------------------------------------------------
cat <<EOF

Muster is installed.

  Frontend:  http://localhost:3000
  Backend:   http://localhost:8080
  Postgres:  localhost:${POSTGRES_PORT} (user: ${POSTGRES_USER}, db: ${POSTGRES_DB})

  musterctl status        # check backend + frontend + postgres
  musterctl logs -f backend
  musterctl doctor        # verify ports, venv, CLIs on PATH

Data/config root: $MUSTER_HOME
Docs: $APP_DIR/docs/OPERATIONS.md

EOF
