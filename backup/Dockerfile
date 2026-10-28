# Backup runner: pg_dump, rclone, brotli and curl in one place.
#
# Based on the Postgres image the chart runs (charts/lumios/values.yaml,
# postgres.image) rather than a plain Alpine, because pg_dump refuses to dump a
# server newer than itself — the major version here has to track the one the
# StatefulSet runs.
FROM docker.io/library/postgres:18.6-alpine@sha256:10a5c69a83035ab5239f5620d708520e8b28f5aa1f2b20143e6024532edadfb5

# rclone from the official image, the same way the backend Dockerfile takes uv
# from the astral image. Pinned by digest. The binary is statically linked and
# comes from an Alpine image as well, so it runs here as it is.
COPY --from=docker.io/rclone/rclone:1.75.2@sha256:2687085f718d3c628f7fdfb77c52a1d344332aed543110bb88088f2c70d43eb5 /usr/local/bin/rclone /usr/local/bin/rclone

# bash for pipefail, curl for the healthchecks.io pings, brotli for the dump.
# The upgrade takes Alpine security updates that landed after the Postgres image
# was last rebuilt.
USER root
RUN apk upgrade --no-cache \
    && apk add --no-cache bash brotli curl

COPY backup.sh backup-photos.sh healthcheck.sh /usr/local/bin/
RUN chmod 0755 /usr/local/bin/backup.sh /usr/local/bin/backup-photos.sh \
        /usr/local/bin/healthcheck.sh /usr/local/bin/rclone

# Back to the image's unprivileged postgres user (uid 70).
USER 70

ARG GIT_SHA=unknown
ENV GIT_HASH=${GIT_SHA}

# The photo CronJob overrides this with backup-photos.sh.
ENTRYPOINT ["/usr/local/bin/backup.sh"]
