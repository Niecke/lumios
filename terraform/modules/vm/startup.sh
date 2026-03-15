#!/bin/bash
set -euo pipefail

# Mount persistent data disk if not already mounted
if ! mountpoint -q /data; then
  DISK="/dev/disk/by-id/google-lumios-data"
  if ! blkid "$DISK" | grep -q ext4; then
    mkfs.ext4 -F "$DISK"
  fi
  mkdir -p /data
  mount "$DISK" /data
  echo "$DISK /data ext4 defaults,nofail 0 2" >> /etc/fstab
fi

mkdir -p /data/postgres /data/redis /run/secrets

# Install Docker
if ! command -v docker &>/dev/null; then
  apt-get update
  apt-get install -y ca-certificates curl
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
    https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
  systemctl enable --now docker
fi

# Fetch Postgres password from Secret Manager
gcloud secrets versions access latest --secret=lumios-postgres-password \
  > /run/secrets/postgres_password
chmod 600 /run/secrets/postgres_password

# Write docker-compose
cat > /opt/docker-compose.yml <<'EOF'
services:
  postgres:
    image: postgres:18
    restart: always
    environment:
      POSTGRES_USER: lumios
      POSTGRES_DB: lumios
      POSTGRES_PASSWORD_FILE: /run/secrets/postgres_password
    secrets:
      - postgres_password
    volumes:
      - /data/postgres:/var/lib/postgresql
    ports:
      - "5432:5432"

  redis:
    image: redis:8
    restart: always
    command: redis-server --save 60 1 --loglevel warning
    volumes:
      - /data/redis:/data
    ports:
      - "6379:6379"

secrets:
  postgres_password:
    file: /run/secrets/postgres_password
EOF

# Systemd service
cat > /etc/systemd/system/lumios-data.service <<'EOF'
[Unit]
Description=Lumios Postgres + Redis
After=docker.service
Requires=docker.service

[Service]
WorkingDirectory=/opt
ExecStart=/usr/bin/docker compose -f /opt/docker-compose.yml up
ExecStop=/usr/bin/docker compose -f /opt/docker-compose.yml down
Restart=always

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now lumios-data
