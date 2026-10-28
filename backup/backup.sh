#!/usr/bin/env bash
#
# One archive per run, written straight to the off-site bucket:
#
#   lumios-postgres-<TS>.tar
#   └── dump.sql.br     brotli — SQL is text and compresses about 10:1
#
# The tar wrapper holds one file today; it keeps the archive layout stable should
# something else be added next to the dump.
#
# The GCS bucket is addressed through its S3-compatible endpoint using an HMAC
# key that may add and read archives but not delete or overwrite them, so no GCP
# service account key is needed anywhere in this path and a leaked key cannot
# destroy existing backups. Archive names carry a timestamp and never collide;
# the bucket's lifecycle rule removes archives after 14 days.
set -euo pipefail

: "${DATABASE_HOST:?}"
: "${DATABASE_USER:?}"
: "${DATABASE_NAME:?}"
: "${PGPASSWORD:?}"
: "${GCS_ENDPOINT:?}"
: "${GCS_ACCESS_KEY:?}"
: "${GCS_SECRET_KEY:?}"
: "${BACKUP_BUCKET:?}"

WORK_DIR="${WORK_DIR:-/backup}"
# 5 rather than brotli's default of 11: on two shared vCPUs the top levels cost
# minutes for a few percent, and this runs while the app is serving.
BROTLI_QUALITY="${BROTLI_QUALITY:-5}"

# shellcheck source=healthcheck.sh
. "$(dirname "$0")/healthcheck.sh"

TS="$(date -u +%Y%m%dT%H%M%SZ)"
ARCHIVE="lumios-postgres-${TS}.tar"

work="$(mktemp -d "${WORK_DIR}/run.XXXXXX")"
hc_cleanup() { rm -rf "$work"; }
hc_begin

# The remote is defined in the environment; the config file stays empty and only
# exists so rclone does not complain that it is missing. no_check_bucket because
# the HMAC key may not create buckets, and rclone would otherwise try.
export RCLONE_CONFIG="${work}/rclone.conf"
: > "$RCLONE_CONFIG"
export RCLONE_CONFIG_GCS_TYPE=s3 RCLONE_CONFIG_GCS_PROVIDER=GCS \
    RCLONE_CONFIG_GCS_ENDPOINT="$GCS_ENDPOINT" \
    RCLONE_CONFIG_GCS_ACCESS_KEY_ID="$GCS_ACCESS_KEY" \
    RCLONE_CONFIG_GCS_SECRET_ACCESS_KEY="$GCS_SECRET_KEY" \
    RCLONE_CONFIG_GCS_NO_CHECK_BUCKET=true

echo "==> dumping ${DATABASE_NAME} from ${DATABASE_HOST}"
# A plain SQL script that restores as whoever runs psql: no owner, no grants.
pg_dump \
    --host="$DATABASE_HOST" \
    --username="$DATABASE_USER" \
    --dbname="$DATABASE_NAME" \
    --format=plain --no-owner --no-privileges \
    | brotli -q "$BROTLI_QUALITY" > "${work}/dump.sql.br"

echo "==> uploading ${ARCHIVE}"
# rclone rcat consumes stdin, so the tar never lands on disk.
tar -cf - -C "$work" dump.sql.br \
    | rclone rcat "gcs:${BACKUP_BUCKET}/${ARCHIVE}"

echo "==> verifying"
rclone lsl "gcs:${BACKUP_BUCKET}/${ARCHIVE}"

echo "backup ${ARCHIVE} complete"
