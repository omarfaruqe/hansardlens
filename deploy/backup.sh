#!/bin/sh
# Nightly PostgreSQL backups for HansardLens, run by the "backup" service.
#
# Every 10 minutes it checks whether today's backup exists; after BACKUP_AT (local time)
# it makes one, so a server that was off at that time catches up when it is back.
# Dumps are written to a temporary name first, then renamed, so a half-written file is
# never mistaken for a backup. Only the newest BACKUP_KEEP dumps are kept.
#
# Environment: PGHOST, PGUSER, PGPASSWORD, PGDATABASE (from the compose file),
# BACKUP_DIR (default /backups), BACKUP_AT (default 02:30), BACKUP_KEEP (default 3),
# BACKUP_HEALTHCHECK_URL (optional: pinged on success, URL/fail on failure).
set -u

DIR="${BACKUP_DIR:-/backups}"
AT="${BACKUP_AT:-02:30}"
KEEP="${BACKUP_KEEP:-3}"
PING="${BACKUP_HEALTHCHECK_URL:-}"

log() { echo "[backup $(date '+%Y-%m-%d %H:%M:%S')] $*"; }

ping() {  # ping "" | ping "/fail"; never fails the backup itself
    [ -n "$PING" ] && wget -q -T 10 -O /dev/null "${PING}$1" 2>/dev/null || true
}

LOCK="$DIR/.backup.lock"

take_lock() {  # only one backup at a time, even across containers
    waited=0
    while ! mkdir "$LOCK" 2>/dev/null; do
        # a lock older than 2 hours was left by a killed run: remove it
        if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +120 2>/dev/null)" ]; then
            log "removing stale lock"
            rmdir "$LOCK" 2>/dev/null
            continue
        fi
        if [ "$waited" -ge 3600 ]; then
            log "FAILED: another backup has been running for an hour"
            return 1
        fi
        [ "$waited" -eq 0 ] && log "another backup is running; waiting for it to finish"
        sleep 10
        waited=$((waited + 10))
    done
    HAVE_LOCK=1
}

release_lock() {
    [ "${HAVE_LOCK:-0}" = 1 ] && rmdir "$LOCK" 2>/dev/null
    HAVE_LOCK=0
}

backup_once() {
    take_lock || { ping "/fail"; return 1; }
    today="$(date +%F)"
    final="$DIR/hansardlens-$today.dump"
    tmp="$final.partial-$(hostname)"   # unique per container
    log "starting pg_dump of $PGDATABASE"
    if pg_dump -Fc -Z 6 -f "$tmp" && pg_restore --list "$tmp" > /dev/null; then
        mv "$tmp" "$final"
        size="$(du -h "$final" | cut -f1)"
        log "saved $final ($size)"
        # keep the newest $KEEP dumps
        ls -1t "$DIR"/hansardlens-*.dump 2>/dev/null | tail -n +"$((KEEP + 1))" | while read -r old; do
            rm -f "$old" && log "removed old backup $old"
        done
        ping ""
        release_lock
        return 0
    fi
    rm -f "$tmp"
    log "FAILED: pg_dump did not produce a readable backup"
    ping "/fail"
    release_lock
    return 1
}

trap 'log "stopping"; rm -f "$DIR"/*.partial-"$(hostname)"; release_lock; exit 0' TERM INT
mkdir -p "$DIR"
if [ "${1:-}" = "--now" ]; then
    backup_once
    exit $?
fi

log "daily backups at $AT ($(date +%Z)), keeping $KEEP, in $DIR"
last_attempt=""
while true; do
    today="$(date +%F)"
    # HHMM as numbers, e.g. 0230: works in every POSIX shell, including BusyBox
    if [ ! -f "$DIR/hansardlens-$today.dump" ] && [ "$(date +%H%M)" -ge "$(echo "$AT" | tr -d :)" ]; then
        # after a failure, retry at most once an hour
        if [ -z "$last_attempt" ] || [ $(( $(date +%s) - last_attempt )) -ge 3600 ]; then
            last_attempt="$(date +%s)"
            backup_once || true
        fi
    fi
    sleep 600 &
    wait $!   # lets docker stop interrupt the sleep at once
done
