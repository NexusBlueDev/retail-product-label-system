#!/usr/bin/env bash
# Waits for ls_upc_fix.py to complete, then sends the error log email.
# Run from project root: bash docs/await_upc_fix_and_email.sh &
set -e
cd "$(dirname "$0")/.."

LOG="docs/await_upc_fix.log"
echo "[$(date -u)] Waiting for UPC fix process to complete..." | tee -a "$LOG"

while pgrep -f "ls_upc_fix.py" > /dev/null 2>&1; do
    sleep 30
done

echo "[$(date -u)] UPC fix process complete. Sending email..." | tee -a "$LOG"
python3 docs/send_upc_fix_results_email.py 2>&1 | tee -a "$LOG"
echo "[$(date -u)] Done." | tee -a "$LOG"
