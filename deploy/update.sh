#!/usr/bin/env bash
# KJV MCP Server — update to latest code
# Run as root: sudo bash /opt/kjv-mcp/deploy/update.sh
set -euo pipefail

INSTALL_DIR="/opt/kjv-mcp"
SERVICE_USER="kjvmcp"
BRANCH="claude/kjv-verse-lookup-tool-uqHWx"

if [[ $EUID -ne 0 ]]; then
    echo "Please run as root (sudo bash update.sh)"
    exit 1
fi

echo "--- Pulling latest code ---"
git -C "$INSTALL_DIR" fetch origin "$BRANCH"
git -C "$INSTALL_DIR" checkout "$BRANCH"
git -C "$INSTALL_DIR" reset --hard "origin/$BRANCH"
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

echo "--- Updating Python dependencies ---"
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"

echo "--- Restarting service ---"
systemctl restart kjv-mcp
systemctl status kjv-mcp --no-pager -l | head -15

echo "Done."
