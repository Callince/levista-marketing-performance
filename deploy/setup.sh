#!/usr/bin/env bash
# One-shot deploy for a fresh Ubuntu droplet. Idempotent — safe to re-run to update.
#   curl -fsSL https://raw.githubusercontent.com/Callince/levista-marketing-performance/main/deploy/setup.sh | bash
# or, after cloning: sudo bash /opt/levista/deploy/setup.sh
set -euo pipefail

REPO="https://github.com/Callince/levista-marketing-performance.git"
APP=/opt/levista
PUBLIC_URL="${PUBLIC_URL:-https://levista.fourdm.services}"   # for the final message only

echo ">> packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip nginx git curl ca-certificates >/dev/null
if ! command -v node >/dev/null 2>&1; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash - >/dev/null
  apt-get install -y -qq nodejs >/dev/null
fi

echo ">> swap (next build needs more than 1GB RAM)"
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo ">> code"
if [ -d "$APP/.git" ]; then git -C "$APP" pull --ff-only; else git clone --depth 1 "$REPO" "$APP"; fi

echo ">> backend (venv + deps)"
python3 -m venv "$APP/.venv"
"$APP/.venv/bin/pip" install -q -U pip
"$APP/.venv/bin/pip" install -q -r "$APP/platform/requirements.txt"
mkdir -p "$APP/data/input" "$APP/data/output"
if [ ! -f "$APP/platform/.env" ]; then
  cat > "$APP/platform/.env" <<ENV
DATABASE_URL=sqlite:///$APP/platform/levista.db
INPUT_DIR=$APP/data/input
OUTPUT_DIR=$APP/data/output
ENV
fi

echo ">> frontend (build)"
cd "$APP/dashboard"
npm ci --no-audit --no-fund
# Relative API base ("" -> same-origin /api). Host- and protocol-agnostic, so the
# same build serves the raw IP over HTTP and the domain over HTTPS with no
# mixed-content errors. nginx proxies /api to the backend either way.
NEXT_PUBLIC_API="" npm run build

echo ">> services"
cp "$APP/deploy/levista-api.service" /etc/systemd/system/
cp "$APP/deploy/levista-web.service" /etc/systemd/system/
chown -R www-data:www-data "$APP"
systemctl daemon-reload
systemctl enable --now levista-api levista-web
systemctl restart levista-api levista-web

echo ">> nginx"
cp "$APP/deploy/nginx.conf" /etc/nginx/sites-available/levista
ln -sf /etc/nginx/sites-available/levista /etc/nginx/sites-enabled/levista
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

echo ">> done -> $PUBLIC_URL"
echo "   Load data: put exports in $APP/data/input then run:"
echo "     sudo -u www-data $APP/.venv/bin/python -m etl.run   # (from $APP/platform)"
echo "   Or copy a prebuilt DB to $APP/platform/levista.db and: systemctl restart levista-api"
