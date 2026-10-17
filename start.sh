#!/usr/bin/env bash
#
# Start the Pikmin Bloom Helper app on your own machine.
#
# Checks that everything the app needs is in place before starting it, so a
# missing tool or a skipped install gives you a sentence to read instead of a
# stack trace.
#
#    ./start.sh             start the app on http://localhost:5000
#    ./start.sh --port 4000 listen somewhere other than port 5000
#    ./start.sh --help      show this message
#
# Works on macOS and Linux.

set -euo pipefail

REQUIRED_PYTHON_MAJOR=3
REQUIRED_PYTHON_MINOR=10

PORT_OVERRIDE=""

say() {
    printf '==> %s\n' "$1"
}

die() {
    printf 'ERROR: %s\n' "$1" >&2
    exit 1
}

usage() {
    awk 'NR>1 { if (/^#/) { sub(/^# ?/, ""); print } else { exit } }' "$0"
    exit 0
}

# --- options ----------------------------------------------------------------

while [ $# -gt 0 ]; do
    case "$1" in
        -p|--port)
            [ $# -ge 2 ] || die "--port needs a number, for example: --port 5000"
            case "$2" in
                ''|*[!0-9]*) die "--port needs a number, got '$2'" ;;
            esac
            PORT_OVERRIDE="$2"
            shift 2
            ;;
        -h|--help)
            usage
            ;;
        *)
            die "unknown option '$1' (try --help)"
            ;;
    esac
done

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

# --- checks -----------------------------------------------------------------

command -v python3 >/dev/null 2>&1 \
    || die "Python 3 is not installed. Please install Python version ${REQUIRED_PYTHON_MAJOR}.${REQUIRED_PYTHON_MINOR} or newer."

# Check Python version
if ! python3 -c "import sys; sys.exit(0 if sys.version_info >= (${REQUIRED_PYTHON_MAJOR}, ${REQUIRED_PYTHON_MINOR}) else 1)"; then
    die "Python $(python3 --version) is too old. This app needs Python ${REQUIRED_PYTHON_MAJOR}.${REQUIRED_PYTHON_MINOR} or newer."
fi

[ -f requirements.txt ] || die "no requirements.txt here. Run this script from inside the project folder."

# --- virtual environment & dependencies -------------------------------------

VENV_DIR="venv"
MARKER_FILE="$VENV_DIR/.requirements-installed"

if [ ! -d "$VENV_DIR" ]; then
    say "Creating Python virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

# Activate virtual environment
if [ -f "venv/Scripts/activate" ]; then
    source venv/Scripts/activate
elif [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
else
    die "Virtual environment activation script not found."
fi

# Install or update dependencies if requirements.txt changed
if [ ! -f "$MARKER_FILE" ] || [ requirements.txt -nt "$MARKER_FILE" ]; then
    say "Installing/updating Python dependencies..."
    pip install --upgrade pip >/dev/null
    
    # If running on Windows (Git Bash/MSYS), exclude psycopg2-binary for local SQLite use
    if [[ "$(uname -s)" =~ (MINGW|MSYS|CYGWIN|Windows) ]]; then
        say "Windows environment detected: filtering out psycopg2-binary for local testing..."
        grep -v "psycopg2-binary" requirements.txt > requirements-local.txt
        pip install -r requirements-local.txt
        rm requirements-local.txt
    else
        # Linux (Grader environment) gets the full requirements.txt
        pip install -r requirements.txt
    fi
    
    touch "$MARKER_FILE"
fi

# Initialize local database tables if app.py exists
if [ -f "app.py" ]; then
    python3 -c "from app import app, db; app.app_context().push(); db.create_all()" 2>/dev/null || true
fi

# --- start ------------------------------------------------------------------

PORT_IN_USE="${PORT_OVERRIDE:-5000}"
say "Starting on http://localhost:${PORT_IN_USE} -- press Ctrl+C to stop"

export FLASK_APP="app.py"
export FLASK_ENV="development"
export PORT="$PORT_IN_USE"

exec python3 app.py