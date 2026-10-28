#!/usr/bin/env bash
#
# Mirrors the object storage (photos and videos) into a second bucket at another
# provider. Nothing is staged on disk: rclone streams between the two buckets.
#
# Deletion is the hard part. The backup must not grow without bound, and photos
# of deleted accounts must leave it after a bounded time, but a leaked key must
# not be able to wipe the backup either. BACKUP_MODE picks the trade-off; what
# each mode needs from the bucket's permissions is in deploy/README.md.
#
#   backup-dir  rclone sync into <bucket>/current. Whatever a sync would delete
#               or overwrite is moved to <bucket>/deleted/<date>/ instead, and a
#               lifecycle rule on that prefix empties it after the retention
#               period. Needs delete rights on the bucket (the move is a copy
#               plus a delete), so a leaked key can remove current/.
#   mirror      rclone sync into <bucket>/current with nothing kept aside. For a
#               bucket that versions its objects and expires non-current
#               versions itself. Needs delete rights as well.
#   copy        rclone copy: new and changed objects are added, nothing is ever
#               deleted. Needs no delete right, but deleted photos stay in the
#               backup forever.
set -euo pipefail

: "${S3_ENDPOINT_URL:?}"
: "${S3_ACCESS_KEY:?}"
: "${S3_SECRET_KEY:?}"
: "${S3_BUCKET:?}"
: "${GCS_ENDPOINT:?}"
: "${GCS_ACCESS_KEY:?}"
: "${GCS_SECRET_KEY:?}"
: "${BACKUP_BUCKET:?}"

BACKUP_MODE="${BACKUP_MODE:-backup-dir}"
RCLONE_TRANSFERS="${RCLONE_TRANSFERS:-4}"

case "$BACKUP_MODE" in
    backup-dir | mirror | copy) ;;
    *)
        echo "error: BACKUP_MODE must be backup-dir, mirror or copy, got '${BACKUP_MODE}'" >&2
        exit 2
        ;;
esac

# shellcheck source=healthcheck.sh
. "$(dirname "$0")/healthcheck.sh"

hc_begin

# The scratch directory holds only rclone's config file.
RCLONE_CONFIG="$(mktemp "${TMPDIR:-/tmp}/rclone.XXXXXX")"
export RCLONE_CONFIG
hc_cleanup() { rm -f "$RCLONE_CONFIG"; }

# `src` is the live bucket, read with the backend's own key (Hetzner in
# production). `gcs` is the backup bucket; no_check_bucket because the HMAC key
# may not create buckets, and rclone would otherwise try.
export RCLONE_CONFIG_SRC_TYPE=s3 RCLONE_CONFIG_SRC_PROVIDER=Other \
    RCLONE_CONFIG_SRC_ENDPOINT="$S3_ENDPOINT_URL" \
    RCLONE_CONFIG_SRC_ACCESS_KEY_ID="$S3_ACCESS_KEY" \
    RCLONE_CONFIG_SRC_SECRET_ACCESS_KEY="$S3_SECRET_KEY"
export RCLONE_CONFIG_GCS_TYPE=s3 RCLONE_CONFIG_GCS_PROVIDER=GCS \
    RCLONE_CONFIG_GCS_ENDPOINT="$GCS_ENDPOINT" \
    RCLONE_CONFIG_GCS_ACCESS_KEY_ID="$GCS_ACCESS_KEY" \
    RCLONE_CONFIG_GCS_SECRET_ACCESS_KEY="$GCS_SECRET_KEY" \
    RCLONE_CONFIG_GCS_NO_CHECK_BUCKET=true

src="src:${S3_BUCKET}"
dest="gcs:${BACKUP_BUCKET}/current"
common=(--transfers "$RCLONE_TRANSFERS" --stats-one-line --stats 1m -v)

echo "==> ${BACKUP_MODE}: ${S3_BUCKET} -> ${BACKUP_BUCKET}/current"
case "$BACKUP_MODE" in
    backup-dir)
        rclone sync "${common[@]}" \
            --backup-dir "gcs:${BACKUP_BUCKET}/deleted/$(date -u +%F)" \
            "$src" "$dest"
        ;;
    mirror)
        rclone sync "${common[@]}" "$src" "$dest"
        ;;
    copy)
        rclone copy "${common[@]}" "$src" "$dest"
        ;;
esac

echo "==> verifying"
# Same objects with the same sizes on both sides. In copy mode the backup may
# hold more than the source, so only the missing-in-backup side is an error.
if [ "$BACKUP_MODE" = copy ]; then
    rclone check --size-only --one-way "$src" "$dest"
else
    rclone check --size-only "$src" "$dest"
fi

echo "photo backup complete"
