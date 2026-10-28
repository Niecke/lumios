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
#
# The sync modes stop with an error when one run would delete more than
# BACKUP_MAX_DELETE objects (0 turns the guard off). A wrong or unlistable source
# bucket looks empty to rclone and would otherwise empty current/ and report
# success.
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
BACKUP_MAX_DELETE="${BACKUP_MAX_DELETE:-500}"

case "$BACKUP_MODE" in
    backup-dir | mirror | copy) ;;
    *)
        echo "error: BACKUP_MODE must be backup-dir, mirror or copy, got '${BACKUP_MODE}'" >&2
        exit 2
        ;;
esac

case "$BACKUP_MAX_DELETE" in
    '' | *[!0-9]*)
        echo "error: BACKUP_MAX_DELETE must be a number, got '${BACKUP_MAX_DELETE}'" >&2
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
sync_guard=()
if [ "$BACKUP_MAX_DELETE" -gt 0 ]; then
    sync_guard=(--max-delete "$BACKUP_MAX_DELETE")
fi
started=$(date +%s)

echo "==> ${BACKUP_MODE}: ${S3_BUCKET} -> ${BACKUP_BUCKET}/current"
case "$BACKUP_MODE" in
    backup-dir)
        rclone sync "${common[@]}" "${sync_guard[@]}" \
            --backup-dir "gcs:${BACKUP_BUCKET}/deleted/$(date -u +%F)" \
            "$src" "$dest"
        ;;
    mirror)
        rclone sync "${common[@]}" "${sync_guard[@]}" "$src" "$dest"
        ;;
    copy)
        rclone copy "${common[@]}" "$src" "$dest"
        ;;
esac

echo "==> verifying"
# Every object of the source is in the backup with the same size. The sync can
# run for hours against a live bucket, so objects written or changed since it
# started are left out (--min-age is relative to now), and objects that vanished
# from the source meanwhile are no error (--one-way): neither is a failed backup.
elapsed=$(($(date +%s) - started + 60))
rclone check --size-only --one-way --min-age "${elapsed}s" "$src" "$dest"

echo "photo backup complete"
