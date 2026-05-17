#!/usr/bin/env bash
# Install (or remove) anacron entries for the memory flywheel jobs.
#
# Anacron is the right scheduler for a laptop: if the machine is off when a
# job is due, anacron runs it on next boot. The job logic is already
# catch-up-safe (sentinel files + sentinel-anchored window), so the scheduler
# just needs to *eventually* fire it.
#
# This script writes two job files into /etc/cron.daily and /etc/cron.weekly
# style anacron entries via /etc/cron.d/, OR, simpler: it appends to
# /etc/anacrontab. We pick the /etc/cron.d approach since WSL's /etc/cron.d
# is processed by the cron daemon and works without anacron when needed.
#
# Default action: install. Pass --uninstall to remove.
#
# Requires sudo. Idempotent — re-running install is a no-op.

set -u

ACTION="install"
if [ "${1:-}" = "--uninstall" ]; then
  ACTION="uninstall"
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
USER_NAME="$(id -un)"
CRON_FILE=/etc/cron.d/ob-memory-flywheel
ANACRONTAB=/etc/anacrontab

# ── Preconditions ─────────────────────────────────────────────────────────────

if [ "$(id -u)" -ne 0 ] && ! sudo -v 2>/dev/null; then
  echo "error: sudo required to write to $CRON_FILE / $ANACRONTAB" >&2
  exit 1
fi

# ── Uninstall ─────────────────────────────────────────────────────────────────

if [ "$ACTION" = "uninstall" ]; then
  echo "Removing $CRON_FILE …"
  sudo rm -f "$CRON_FILE"
  if [ -f "$ANACRONTAB" ]; then
    echo "Stripping anacron entries from $ANACRONTAB …"
    sudo sed -i '/# >>> ob-memory-flywheel >>>/,/# <<< ob-memory-flywheel <<</d' "$ANACRONTAB" || true
  fi
  echo "Done. Reload cron with: sudo service cron reload"
  exit 0
fi

# ── Install ───────────────────────────────────────────────────────────────────

echo "Installing memory-flywheel cron entries for user $USER_NAME"
echo "  repo:  $REPO_ROOT"
echo "  cron:  $CRON_FILE"
echo

# /etc/cron.d entry — runs at 23:00 daily and Sunday 09:00. cron.d format:
#   m h dom mon dow user command
# The daily/weekly logic mirrors the YAML frontmatter in cron/jobs/*.md.
# IO redirection in the cron entry routes any extra stderr to the log too.
TMP_CRON=$(mktemp)
cat > "$TMP_CRON" <<EOF
# Open Brain memory flywheel — installed by scripts/memory/install-anacron.sh
# Daily: distill yesterday's session log(s) into context/STATE.md.
0 23 * * *   $USER_NAME  bash $REPO_ROOT/scripts/memory/run-distill.sh >> /tmp/ob-memory-distill.log 2>&1
# Weekly: curate the personal markdown memory layer. Sunday 09:00.
0  9 * * 0   $USER_NAME  bash $REPO_ROOT/scripts/memory/run-curate.sh  >> /tmp/ob-memory-curate.log  2>&1
EOF
sudo install -m 0644 "$TMP_CRON" "$CRON_FILE"
rm -f "$TMP_CRON"

# /etc/anacrontab entry — fires on boot if the daily/weekly run was missed.
# Format: period-in-days delay-in-min job-id command
if [ -f "$ANACRONTAB" ]; then
  if ! sudo grep -q "ob-memory-flywheel" "$ANACRONTAB"; then
    echo "Appending anacron catch-up entries to $ANACRONTAB …"
    sudo tee -a "$ANACRONTAB" >/dev/null <<EOF

# >>> ob-memory-flywheel >>>
# Catch-up runs if cron missed them (laptop off at 23:00 / Sun 09:00).
1   10  ob-memory-distill   su -l $USER_NAME -c 'bash $REPO_ROOT/scripts/memory/run-distill.sh'
7   20  ob-memory-curate    su -l $USER_NAME -c 'bash $REPO_ROOT/scripts/memory/run-curate.sh'
# <<< ob-memory-flywheel <<<
EOF
  else
    echo "anacron entries already present in $ANACRONTAB — skipping"
  fi
else
  echo "note: /etc/anacrontab not found. Install anacron with: sudo apt install anacron"
fi

# Reload cron so the new /etc/cron.d entry is picked up.
if command -v service >/dev/null; then
  sudo service cron reload 2>/dev/null || sudo service cron restart 2>/dev/null || true
fi

cat <<EOF

Done. Verify with:
  ls -l $CRON_FILE
  sudo service cron status   # should show "active (running)"

WSL2 note: cron does NOT start automatically. Make sure /etc/wsl.conf has:
  [boot]
  command = "service cron start"

That guarantees the schedule keeps firing across WSL restarts. anacron will
also fire missed jobs the next time cron runs (i.e. after the next WSL boot).

Trigger a one-off run any time with:
  make memory-distill
  make memory-curate
EOF
