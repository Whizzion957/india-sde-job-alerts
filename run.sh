#!/usr/bin/env bash
# Job alerts: scan official job boards and push NEW India entry-level SDE postings to Telegram.
# Scheduled daily by cron (see `crontab -l`). History: ALERTS.md; run logs kept 60 days in logs/.
set -u
cd "$(dirname "$(readlink -f "$0")")" || exit 1
mkdir -p logs
LOG="logs/run_$(date -u +%Y-%m-%d_%H%M).log"
/usr/bin/python3 -I notify.py >> "$LOG" 2>&1
echo "exit code: $?" >> "$LOG"
find logs -type f -mtime +60 -delete
