#!/usr/bin/env bash
# KJV MCP Server — Debian 11/12 installer
# Run as root: bash install.sh <your-domain> [api-key]
#
# Designed for servers where ports 80 and 443 are already in use.
# The MCP server is exposed on port 8443 (HTTPS) via nginx.
# SSL certificate is obtained using the DNS-01 challenge — no port 80 needed.
#
# What this script does:
#   1. Installs system packages (Python 3.11+, nginx, certbot, git)
#   2. Creates a dedicated 'kjvmcp' system user
#   3. Clones/updates the repo to /opt/kjv-mcp
#   4. Creates a Python virtualenv and installs requirements
#   5. Downloads the KJV Bible data
#   6. Writes /etc/kjv-mcp/env (environment variables)
#   7. Installs and starts the systemd service
#   8. Installs the nginx config on port 8443
#   9. Walks you through DNS-01 certificate issuance

set -euo pipefail

DOMAIN="${1:-}"
API_KEY="${2:-}"

if [[ -z "$DOMAIN" ]]; then
    echo "Usage: bash install.sh <your-domain> [api-key]"
    echo "  e.g. bash install.sh kjv.buitendyk.ca my-secret-key"
    exit 1
fi

if [[ $EUID -ne 0 ]]; then
    echo "Please run as root (sudo bash install.sh ...)"
    exit 1
fi

REPO_URL="https://github.com/tbuitendyk/Claude-1.git"
BRANCH="claude/kjv-verse-lookup-tool-uqHWx"
INSTALL_DIR="/opt/kjv-mcp"
SERVICE_USER="kjvmcp"
ENV_FILE="/etc/kjv-mcp/env"

echo "=== KJV MCP Server Installer ==="
echo "Domain  : $DOMAIN"
echo "Port    : 8443 (nginx SSL, won't touch 80/443)"
echo "API key : ${API_KEY:-<none — server will be open>}"
echo ""

# ── 1. System packages ──────────────────────────────────────────────────────
echo "--- Installing system packages ---"

CODENAME=$(. /etc/os-release && echo "$VERSION_CODENAME")
echo "    Detected Debian: $CODENAME"

# Remove any leftover broken repo files from previous install attempts
rm -f /etc/apt/sources.list.d/sury-python.list
rm -f /etc/apt/trusted.gpg.d/sury-python.gpg

apt-get update -qq
apt-get install -y --no-install-recommends nginx certbot git curl gnupg

# Install Python 3.11 — required by the mcp package (needs Python >= 3.10).
# On Debian 12 (bookworm) python3.11 is in the main repo.
# On Debian 11 (bullseye) backports and third-party repos are unreliable;
# compile from source if not already present.
if ! command -v python3.11 &>/dev/null; then
    if [[ "$CODENAME" == "bookworm" ]]; then
        echo "    Installing Python 3.11 from Debian 12 repo..."
        apt-get install -y python3.11 python3.11-venv
    else
        echo "    Python 3.11 not found."
        echo "    On Debian 11, compile it first then re-run this installer:"
        echo ""
        echo "      apt-get install -y build-essential libssl-dev zlib1g-dev libbz2-dev \\"
        echo "          libreadline-dev libsqlite3-dev wget libncurses5-dev xz-utils \\"
        echo "          libffi-dev liblzma-dev"
        echo "      cd /tmp && wget https://www.python.org/ftp/python/3.11.9/Python-3.11.9.tgz"
        echo "      tar xzf Python-3.11.9.tgz && cd Python-3.11.9"
        echo "      ./configure --enable-optimizations && make -j\$(nproc) && make altinstall"
        echo ""
        exit 1
    fi
else
    echo "    Python 3.11 already installed: $(python3.11 --version)"
    apt-get install -y python3.11-venv 2>/dev/null || true
fi

# Allow git to operate on the install directory regardless of who owns it
git config --global --add safe.directory "$INSTALL_DIR" 2>/dev/null || true

# ── 2. Dedicated system user ────────────────────────────────────────────────
echo "--- Creating system user '$SERVICE_USER' ---"
id "$SERVICE_USER" &>/dev/null || \
    useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"

# ── 3. Clone / update repo ──────────────────────────────────────────────────
echo "--- Deploying code to $INSTALL_DIR ---"
if [[ -d "$INSTALL_DIR/.git" ]]; then
    echo "    Updating existing clone..."
    git -C "$INSTALL_DIR" fetch origin "$BRANCH"
    git -C "$INSTALL_DIR" checkout "$BRANCH"
    git -C "$INSTALL_DIR" reset --hard "origin/$BRANCH"
else
    echo "    Cloning fresh..."
    git clone --branch "$BRANCH" --depth 1 "$REPO_URL" "$INSTALL_DIR"
fi
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

# ── 4. Python virtualenv ────────────────────────────────────────────────────
echo "--- Setting up Python virtualenv (python3.11) ---"
if [[ ! -d "$INSTALL_DIR/venv" ]]; then
    python3.11 -m venv "$INSTALL_DIR/venv"
fi
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/venv"

# ── 5. Download KJV data ────────────────────────────────────────────────────
echo "--- Downloading KJV Bible data ---"
if [[ ! -f "$INSTALL_DIR/kjv.json" ]]; then
    sudo -u "$SERVICE_USER" "$INSTALL_DIR/venv/bin/python" \
        "$INSTALL_DIR/download_kjv.py"
else
    echo "    kjv.json already present, skipping download."
fi

# ── 6. Environment file ─────────────────────────────────────────────────────
echo "--- Writing environment file $ENV_FILE ---"
mkdir -p /etc/kjv-mcp
chmod 750 /etc/kjv-mcp
chown root:"$SERVICE_USER" /etc/kjv-mcp

cat > "$ENV_FILE" <<EOF
TRANSPORT=http
PORT=8000
BASE_URL=https://${DOMAIN}:8443
API_KEY=${API_KEY}
EOF

chmod 640 "$ENV_FILE"
chown root:"$SERVICE_USER" "$ENV_FILE"

# ── 7. Systemd service ──────────────────────────────────────────────────────
echo "--- Installing systemd service ---"
cp "$INSTALL_DIR/deploy/kjv-mcp.service" /etc/systemd/system/kjv-mcp.service
systemctl daemon-reload
systemctl enable kjv-mcp
systemctl restart kjv-mcp
echo "    Service status:"
systemctl status kjv-mcp --no-pager -l | head -20

# ── 8. Firewall — open port 8443 ───────────────────────────────────────────
echo "--- Opening port 8443 in firewall ---"
if command -v ufw &>/dev/null && ufw status | grep -q "Status: active"; then
    ufw allow 8443/tcp comment "KJV MCP Server"
    echo "    ufw: port 8443 allowed."
else
    echo "    ufw not active — ensure port 8443 is open in your firewall/iptables."
fi

# ── 9. nginx config (port 8443, no cert yet) ────────────────────────────────
echo "--- Installing nginx config for port 8443 ---"

# Install config with the domain substituted in — but without ssl lines for now
sed "s/YOUR_DOMAIN/${DOMAIN}/g" \
    "$INSTALL_DIR/deploy/nginx-kjv-mcp.conf" \
    > /etc/nginx/sites-available/kjv-mcp

rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true
ln -sf /etc/nginx/sites-available/kjv-mcp /etc/nginx/sites-enabled/kjv-mcp

# Make sure nginx itself is running (on no default ports — just ours)
systemctl enable nginx
systemctl start nginx || true   # may fail until cert exists — that's OK

# ── 9. SSL certificate via DNS-01 ───────────────────────────────────────────
echo ""
echo "==================================================================="
echo " SSL Certificate — DNS-01 Challenge"
echo "==================================================================="
echo ""
echo " Because ports 80 and 443 are in use, we use the DNS challenge."
echo " certbot will ask you to add a TXT record to your DNS."
echo ""
echo " Have your DNS management console open and ready."
echo " Press ENTER to start, or Ctrl-C to do it manually later."
echo "==================================================================="
read -r

certbot certonly \
    --manual \
    --preferred-challenges dns \
    -d "$DOMAIN" \
    --agree-tos \
    --register-unsafely-without-email

# Now reload nginx with the cert in place
nginx -t && systemctl reload nginx

# ── Done ────────────────────────────────────────────────────────────────────
echo ""
echo "=== Installation complete ==="
echo ""
echo "MCP server URL : https://${DOMAIN}:8443/mcp"
echo "Health check   : https://${DOMAIN}:8443/health"
if [[ -n "$API_KEY" ]]; then
echo "API key        : $API_KEY"
fi
echo ""
echo "Useful commands:"
echo "  sudo systemctl status kjv-mcp        # service status"
echo "  sudo journalctl -u kjv-mcp -f        # live logs"
echo "  sudo systemctl restart kjv-mcp       # restart"
echo "  sudo nano /etc/kjv-mcp/env           # edit env vars"
echo ""
echo "Test it:"
echo "  curl https://${DOMAIN}:8443/health"
echo ""
echo "Update to latest code:"
echo "  sudo bash ${INSTALL_DIR}/deploy/update.sh"
echo ""
echo "Certificate renewal (add to cron or run manually every ~60 days):"
echo "  sudo certbot renew --manual --preferred-challenges dns"
