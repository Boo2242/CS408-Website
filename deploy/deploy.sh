#!/usr/bin/env bash
#
# Push this project to an EC2 instance that has already been prepared with
# deploy/setup-ec2.sh.
#
# Run it from the project root on your own machine (macOS or Linux):
#
#    ./deploy/deploy.sh -h 54.12.34.56 -i ~/keys/webdev.pem
#
# What it does:
#    1. rsync source to /opt/pikmin-helper on the server (venv, .git, and data left behind).
#    2. Install/update python dependencies there.
#    3. Restart the systemd service.
#
# Options:
#    -h HOST    public IP or DNS name of the instance    (required)
#    -i KEY     path to your .pem private key            (optional if ssh-agent has it)
#    -u USER    SSH login user (default: ubuntu; use 'ec2-user' for Amazon Linux)
#    -d DIR     remote directory (default: /opt/pikmin-helper)

set -euo pipefail

REMOTE_HOST=""
SSH_KEY=""
REMOTE_USER="ubuntu"
REMOTE_DIR="/opt/pikmin-helper"
SERVICE="pikmin-helper"

usage() {
    awk 'NR>1 { if (/^#/) { sub(/^# ?/, ""); print } else { exit } }' "$0"
    exit 1
}

while getopts ":h:i:u:d:" option; do
    case "$option" in
        h) REMOTE_HOST="$OPTARG" ;;
        i) SSH_KEY="$OPTARG" ;;
        u) REMOTE_USER="$OPTARG" ;;
        d) REMOTE_DIR="$OPTARG" ;;
        :) echo "ERROR: -$OPTARG needs a value" >&2; usage ;;
        \?) echo "ERROR: unknown option -$OPTARG" >&2; usage ;;
    esac
done

[ -n "$REMOTE_HOST" ] || { echo "ERROR: -h HOST is required" >&2; usage; }

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

[ -f requirements.txt ] || { echo "ERROR: no requirements.txt in $PROJECT_DIR" >&2; exit 1; }

SSH_OPTS=(-o StrictHostKeyChecking=accept-new)
if [ -n "$SSH_KEY" ]; then
    [ -f "$SSH_KEY" ] || { echo "ERROR: key file not found: $SSH_KEY" >&2; exit 1; }
    SSH_OPTS+=(-i "$SSH_KEY")
fi

TARGET="${REMOTE_USER}@${REMOTE_HOST}"

echo "==> Running local tests before deploying"
if command -v pytest &> /dev/null; then
    pytest
else
    echo "No pytest found locally, skipping local test run."
fi

echo "==> Copying files to ${TARGET}:${REMOTE_DIR}"
rsync -az --delete \
    --exclude '.git' \
    --exclude 'venv' \
    --exclude 'instance' \
    --exclude 'data' \
    --exclude '.DS_Store' \
    --exclude '*.log' \
    --exclude '*.db' \
    -e "ssh ${SSH_OPTS[*]}" \
    ./ "${TARGET}:${REMOTE_DIR}/"

echo "==> Installing dependencies and restarting the service on remote server"
ssh "${SSH_OPTS[@]}" "$TARGET" "
    set -e
    cd '${REMOTE_DIR}'
    if [ ! -d 'venv' ]; then
        python3 -m venv venv
    fi
    source venv/bin/activate
    pip install --upgrade pip >/dev/null
    pip install -r requirements.txt
    
    # Initialize DB tables if missing
    python3 -c 'from app import app, db; app.app_context().push(); db.create_all()' 2>/dev/null || true
    
    sudo systemctl restart ${SERVICE}
    sleep 2
    sudo systemctl is-active --quiet ${SERVICE} && echo 'service is running'
"

echo "==> Checking the health endpoint"
if curl -fsS --max-time 10 "http://${REMOTE_HOST}/" >/dev/null; then
    printf '\n\n==> Deployed. Open http://%s in your browser.\n' "$REMOTE_HOST"
else
    printf '\n'
    echo "WARNING: the health check did not answer." >&2
    echo "Check the EC2 security group (port 80 inbound) and the logs:" >&2
    echo "  ssh ${SSH_OPTS[*]} $TARGET 'journalctl -u ${SERVICE} -n 50'" >&2
    exit 1
fi