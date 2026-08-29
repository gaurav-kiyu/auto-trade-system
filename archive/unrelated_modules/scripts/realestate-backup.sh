#!/usr/bin/env bash
# Version: 2.58.0
# ═══════════════════════════════════════════════════════════════════════════════
# Real Estate Platform — Backup & Disaster Recovery Script
# ═══════════════════════════════════════════════════════════════════════════════
# Provides:
#   1. PostgreSQL database backup (pg_dump with compression)
#   2. Upload directory backup (tar.gz)
#   3. Redis snapshot backup (RDB file)
#   4. Configuration backup (K8s secrets, configmaps)
#   5. Rotation policy (keep 7 daily, 4 weekly, 3 monthly)
#   6. Restoration procedure (documented)
# ═══════════════════════════════════════════════════════════════════════════════
#
# Usage:
#   ./scripts/realestate-backup.sh              # Full backup
#   ./scripts/realestate-backup.sh --db-only     # Database only
#   ./scripts/realestate-backup.sh --restore     # Interactive restore
#   ./scripts/realestate-backup.sh --cron        # Silent cron mode
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

# ── Configuration ───────────────────────────────────────────────────────────
BACKUP_DIR="${BACKUP_DIR:-/backups/realestate}"
DB_NAME="${DB_NAME:-realestate}"
DB_USER="${DB_USER:-realestate_user}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
UPLOAD_DIR="${UPLOAD_DIR:-./uploads}"
REDIS_RDB_DIR="${REDIS_RDB_DIR:-/var/lib/redis}"
K8S_NAMESPACE="${K8S_NAMESPACE:-realestate}"
RETENTION_DAILY="${RETENTION_DAILY:-7}"
RETENTION_WEEKLY="${RETENTION_WEEKLY:-4}"
RETENTION_MONTHLY="${RETENTION_MONTHLY:-3}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DATE=$(date +%Y%m%d)
LOG_FILE="${BACKUP_DIR}/backup.log"

# ── Ensure backup directory exists ──────────────────────────────────────────
mkdir -p "${BACKUP_DIR}/{daily,weekly,monthly,logs}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "${LOG_FILE}"
}

# ── 1. PostgreSQL Database Backup ──────────────────────────────────────────
backup_postgres() {
    log "[DB] Starting PostgreSQL backup..."
    local backup_file="${BACKUP_DIR}/daily/${DB_NAME}_${TIMESTAMP}.sql.gz"

    if command -v pg_dump &>/dev/null; then
        PGPASSWORD="${DB_PASSWORD:-}" pg_dump \
            -h "${DB_HOST}" \
            -p "${DB_PORT}" \
            -U "${DB_USER}" \
            -d "${DB_NAME}" \
            --no-owner \
            --no-acl \
            --verbose \
            2>>"${LOG_FILE}" \
            | gzip > "${backup_file}"

        local size=$(du -h "${backup_file}" | cut -f1)
        log "[DB] Backup complete: ${backup_file} (${size})"
    else
        log "[DB] WARNING: pg_dump not found. Install postgresql-client."
    fi
}

# ── 2. Upload Directory Backup ─────────────────────────────────────────────
backup_uploads() {
    log "[UPLOADS] Starting uploads backup..."
    local backup_file="${BACKUP_DIR}/daily/uploads_${TIMESTAMP}.tar.gz"

    if [ -d "${UPLOAD_DIR}" ] && [ "$(ls -A "${UPLOAD_DIR}" 2>/dev/null)" ]; then
        tar -czf "${backup_file}" -C "$(dirname "${UPLOAD_DIR}")" "$(basename "${UPLOAD_DIR}")" 2>>"${LOG_FILE}"
        local size=$(du -h "${backup_file}" | cut -f1)
        log "[UPLOADS] Backup complete: ${backup_file} (${size})"
    else
        log "[UPLOADS] No uploads to backup (${UPLOAD_DIR} empty or missing)"
    fi
}

# ── 3. Configuration Backup (K8s) ──────────────────────────────────────────
backup_config() {
    log "[CONFIG] Starting configuration backup..."
    local config_dir="${BACKUP_DIR}/daily/config_${TIMESTAMP}"
    mkdir -p "${config_dir}"

    # Backup K8s resources if kubectl is available
    if command -v kubectl &>/dev/null; then
        kubectl get configmap realestate-config -n "${K8S_NAMESPACE}" \
            -o yaml > "${config_dir}/configmap.yaml" 2>/dev/null || \
            log "[CONFIG] WARNING: ConfigMap not found in K8s"
        kubectl get secrets -n "${K8S_NAMESPACE}" \
            -o yaml > "${config_dir}/secrets.yaml" 2>/dev/null || \
            log "[CONFIG] WARNING: Secrets not found in K8s"
    fi

    # Backup local config files
    if [ -f "realestate/production.yml" ]; then
        cp "realestate/production.yml" "${config_dir}/"
    fi
    if [ -f "realestate/nginx.conf" ]; then
        cp "realestate/nginx.conf" "${config_dir}/"
    fi

    log "[CONFIG] Config backup complete: ${config_dir}"
}

# ── 4. Redis Snapshot Backup ───────────────────────────────────────────────
backup_redis() {
    log "[REDIS] Starting Redis RDB backup..."
    local backup_file="${BACKUP_DIR}/daily/redis_${TIMESTAMP}.rdb"

    if command -v redis-cli &>/dev/null; then
        # Trigger SAVE and copy RDB
        redis-cli -a "${REDIS_PASSWORD:-}" SAVE 2>/dev/null || true
        if [ -f "${REDIS_RDB_DIR}/dump.rdb" ]; then
            cp "${REDIS_RDB_DIR}/dump.rdb" "${backup_file}"
            local size=$(du -h "${backup_file}" | cut -f1)
            log "[REDIS] Backup complete: ${backup_file} (${size})"
        fi
    else
        log "[REDIS] WARNING: redis-cli not found"
    fi
}

# ── 5. Rotation — Clean up old backups ─────────────────────────────────────
rotate_backups() {
    log "[ROTATE] Starting backup rotation..."

    # Daily: keep last N days
    find "${BACKUP_DIR}/daily" -type f -mtime +${RETENTION_DAILY} -delete 2>/dev/null || true
    log "[ROTATE] Cleaned daily backups older than ${RETENTION_DAILY} days"

    # Weekly: every Monday, keep last N weeks
    if [ "$(date +%u)" = "1" ]; then
        for f in "${BACKUP_DIR}/daily/"*"${DATE}"*; do
            if [ -f "$f" ]; then
                cp "$f" "${BACKUP_DIR}/weekly/"
                log "[ROTATE] Promoted to weekly: $(basename "$f")"
            fi
        done
        find "${BACKUP_DIR}/weekly" -type f -mtime +$((RETENTION_WEEKLY * 7)) -delete
    fi

    # Monthly: every 1st, keep last N months
    if [ "$(date +%d)" = "01" ]; then
        for f in "${BACKUP_DIR}/daily/"*"${DATE}"*; do
            if [ -f "$f" ]; then
                cp "$f" "${BACKUP_DIR}/monthly/"
                log "[ROTATE] Promoted to monthly: $(basename "$f")"
            fi
        done
        find "${BACKUP_DIR}/monthly" -type f -mtime +$((RETENTION_MONTHLY * 30)) -delete
    fi

    log "[ROTATE] Rotation complete"
}

# ── 6. Backup Size Summary ─────────────────────────────────────────────────
summary() {
    log "═══════════════════════════════════════════════════════"
    log "BACKUP SUMMARY — ${TIMESTAMP}"
    log "═══════════════════════════════════════════════════════"
    log "Directory: ${BACKUP_DIR}"
    log "Total size: $(du -sh "${BACKUP_DIR}" | cut -f1)"
    log "Daily count: $(find "${BACKUP_DIR}/daily" -type f | wc -l)"
    log "Weekly count: $(find "${BACKUP_DIR}/weekly" -type f | wc -l)"
    log "Monthly count: $(find "${BACKUP_DIR}/monthly" -type f | wc -l)"
    log "Disk free: $(df -h "${BACKUP_DIR}" | tail -1 | awk '{print $4}')"
    log "═══════════════════════════════════════════════════════"
}

# ── 7. Restoration Guide ───────────────────────────────────────────────────
show_restore_guide() {
    cat << 'GUIDE'

═══════════════════════════════════════════════════════════════════════════════
DISASTER RECOVERY — Restoration Procedure
═══════════════════════════════════════════════════════════════════════════════

1. RESTORE DATABASE:
   $ gunzip -c /backups/realestate/daily/realestate_20260401_000000.sql.gz | \
     psql -h localhost -U realestate_user -d realestate

2. RESTORE UPLOADS:
   $ tar -xzf /backups/realestate/daily/uploads_20260401_000000.tar.gz -C /

3. RESTORE REDIS:
   $ systemctl stop redis
   $ cp /backups/realestate/daily/redis_20260401_000000.rdb /var/lib/redis/dump.rdb
   $ systemctl start redis

4. RESTORE K8S CONFIG:
   $ kubectl apply -f /backups/realestate/daily/config_20260401_000000/

5. RESTORE APPLICATION:
   $ kubectl rollout restart deployment/realestate-api -n realestate
   $ kubectl rollout restart deployment/realestate-worker -n realestate

═══════════════════════════════════════════════════════════════════════════════
GUIDE
}

# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

main() {
    local mode="${1:-full}"

    case "${mode}" in
        --db-only|-d)
            backup_postgres
            ;;
        --uploads|-u)
            backup_uploads
            ;;
        --config|-c)
            backup_config
            ;;
        --redis|-r)
            backup_redis
            ;;
        --restore|--guide|-g)
            show_restore_guide
            exit 0
            ;;
        --cron|--silent|-s)
            # Silent mode for cron — no stdout summary
            backup_postgres
            backup_uploads
            backup_config
            backup_redis
            rotate_backups
            ;;
        --rotate)
            rotate_backups
            ;;
        full|--full|-a)
            log "═══════════════════════════════════════════════════════"
            log "REAL ESTATE BACKUP STARTED — ${TIMESTAMP}"
            log "═══════════════════════════════════════════════════════"
            backup_postgres
            backup_uploads
            backup_config
            backup_redis
            rotate_backups
            summary
            ;;
        *)
            echo "Usage: $0 [--full|--db-only|--uploads|--config|--redis|--restore|--cron|--rotate]"
            echo ""
            echo "Options:"
            echo "  --full       Full backup (database + uploads + config + redis + rotation)"
            echo "  --db-only    PostgreSQL database backup only"
            echo "  --uploads    Upload directory backup only"
            echo "  --config     Configuration backup (K8s + local configs)"
            echo "  --redis      Redis snapshot backup"
            echo "  --restore    Show restoration procedure guide"
            echo "  --cron       Silent mode for cron jobs"
            echo "  --rotate     Backup rotation only"
            exit 1
            ;;
    esac
}

main "$@"
