#!/usr/bin/env bash
#
# Sourced by backup.sh and backup-photos.sh: reports a run to healthchecks.io.
#
# A ping is sent when the run starts, when it succeeds and — through /fail —
# when it breaks. The alarm itself is the *missing* ping: a job that never
# starts, a node that is down or a CronJob that was deleted raises it too, which
# a failure notification from inside the job cannot do.
#
# HEALTHCHECK_URL is the check's ping URL. It is a secret (anyone holding it can
# mark the check green), so it comes from the lumios-values Secret. Unset, the
# job runs without alerting and says so in its log.
#
# A ping that cannot be delivered never fails the backup: the data is safe and
# the check goes red on its own when the ping stays away.

hc_ping() {
    local suffix="${1:-}"
    [ -n "${HEALTHCHECK_URL:-}" ] || return 0
    curl --silent --show-error --fail --max-time 10 --retry 3 --retry-delay 2 \
        --output /dev/null "${HEALTHCHECK_URL%/}${suffix}" \
        || echo "warning: could not reach healthchecks.io (${suffix:-success})" >&2
}

# Call once, after the required variables are checked.
hc_begin() {
    if [ -z "${HEALTHCHECK_URL:-}" ]; then
        echo "warning: HEALTHCHECK_URL is not set — a failed or missing backup raises no alarm" >&2
    fi
    hc_ping /start
    # The exit status is the script's own: set -e, a failed command or the
    # explicit exit at the end all pass through here.
    trap 'hc_finish $?' EXIT
}

hc_finish() {
    local status="$1"
    # The work directory of the caller is removed by its own trap, registered
    # before this one; trap replaces rather than stacks, so backup.sh calls
    # hc_cleanup from here.
    if declare -F hc_cleanup >/dev/null; then
        hc_cleanup
    fi
    if [ "$status" -eq 0 ]; then
        hc_ping
    else
        hc_ping /fail
    fi
}
