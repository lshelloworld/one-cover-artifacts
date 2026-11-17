#!/bin/bash
# Saves a snapshot of the MySQL run's records, logs and progress at a given time, without touching the run.
# Usage: snapshot_mysql.sh "YYYY-MM-DD HH:MM"; writes results/D_enforcement/snapshot_<YYYYMMDD_HHMM>/.
cd "$(dirname "$0")/../.."
T=$(date -j -f "%Y-%m-%d %H:%M" "$1" +%s); while [ "$(date +%s)" -lt "$T" ]; do sleep 30; done
D=results/D_enforcement; S=$D/snapshot_$(date -j -f "%Y-%m-%d %H:%M" "$1" +%Y%m%d_%H%M); mkdir -p $S
cp -p $D/db2_mysql_ks2_repeat.jsonl $D/db2_mysql_ks2_repeat.jsonl.partial $D/mysql_repeat.log $D/mysql_repeat_load.log $D/mysql_pause.log $S/ 2>/dev/null
M=/usr/local/mysql/bin/mysql
{ echo "snapshot $(date)"; echo "load $(sysctl -n vm.loadavg); $(pmset -g ps | head -1)"
  pgrep -f exp_db2_mysql.py >/dev/null && echo "run going" || echo "no run going"
  echo "sides finished for m=40: $(grep -c '"m": 40' $D/db2_mysql_ks2_repeat.jsonl.partial 2>/dev/null)"
  echo "rows accepted so far on the current side: $($M -N -e 'SELECT COUNT(*) FROM onecover.T' 2>&1)"
  echo "current statement: $($M -N -e 'SHOW FULL PROCESSLIST' | awk -F'\t' '$5=="Query" && $8!~/PROCESSLIST/ {print substr($8,1,80)}')"
} > $S/progress.txt
