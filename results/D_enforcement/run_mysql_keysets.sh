#!/bin/bash
# 1M-row MySQL runs on key sets 1 and 2 at |Sigma| = 30, 40, 50 (the key sets of run_keysets.sh).
# Usage: run_mysql_keysets.sh <start "YYYY-MM-DD HH:MM" or now> [<stop "YYYY-MM-DD HH:MM">]
# Waits for the start time, the end of results/run_clean.sh and mains power. At the stop time the run
# is terminated, not paused: times are wall clock, so a paused size would be wrong. The run is also
# terminated when the laptop leaves mains power, since times on battery are not comparable. A size is recorded
# only when finished; rerunning this script skips finished sizes and redoes the interrupted one.
# Records in db2_mysql_ks<k>.jsonl, load every 10 minutes in mysql_keysets_load.log.
cd "$(dirname "$0")/../.."
L=${MYSQL_KS_LOG:-results/D_enforcement/mysql_keysets.log}; PY=~/.venvs/onecover-artifacts/bin/python
START=$1; STOP=${2:-}; POLL=${MYSQL_KS_POLL:-30}
T0=0; [ "$START" = now ] || T0=$(date -j -f "%Y-%m-%d %H:%M" "$START" +%s)
T1=0; [ -z "$STOP" ] || T1=$(date -j -f "%Y-%m-%d %H:%M" "$STOP" +%s)
flush() { $PY -c "import sys; sys.path.insert(0,'.'); from config import MYSQL; import mysql.connector as m; c=m.connect(**MYSQL); k=c.cursor(); k.execute(sys.argv[1]); r=k.fetchall() if k.with_rows else None; print(r[0][0] if r else '')" "$1"; }
echo "waiting since $(date) for $START, stop at ${STOP:-none}" >> $L
until [ "$(date +%s)" -ge "$T0" ] && grep -q "^finished" results/clean_run.log && pmset -g ps | grep -q "AC Power"; do sleep 60; done
F0=$(flush 'SELECT @@GLOBAL.innodb_flush_log_at_trx_commit')
( while :; do echo "$(date '+%d %H:%M') $(sysctl -n vm.loadavg)"; sleep 600; done ) >> results/D_enforcement/mysql_keysets_load.log &
LOADER=$!
echo "started $(date), load $(sysctl -n vm.loadavg), flush setting $F0" >> $L
ps -axo %cpu,command | sort -nr | head -5 | cut -c1-110 >> $L
STOPPED=0
for k in 1 2; do
  [ $STOPPED = 1 ] && break
  echo "== key set $k $(date)" >> $L
  ONECOVER_KEYSET=$k ONECOVER_XL_OUT=results/D_enforcement/db2_pg_extra_ks$k.jsonl ONECOVER_MYSQL_OUT=results/D_enforcement/db2_mysql_ks$k.jsonl \
    $PY -u experiments/D_enforcement/exp_db2_mysql.py xl perkey 30,40,50 >> $L 2>&1 &
  PID=$!
  caffeinate -i -w $PID &
  while kill -0 $PID 2>/dev/null; do
    if [ "$T1" -gt 0 ] && [ "$(date +%s)" -ge "$T1" ]; then kill -TERM $PID; STOPPED=1; break; fi
    pmset -g ps | grep -q "AC Power" || { kill -TERM $PID; STOPPED=1; WHY="on leaving mains power"; break; }
    sleep $POLL
  done
  wait $PID; RC=$?
  [ $STOPPED = 1 ] || [ $RC = 0 ] || echo "FAILED key set $k" >> $L
done
kill $LOADER
flush "SET GLOBAL innodb_flush_log_at_trx_commit = $F0"
echo "flush setting now $(flush 'SELECT @@GLOBAL.innodb_flush_log_at_trx_commit')" >> $L
if [ $STOPPED = 1 ]; then echo "STOPPED ${WHY:-at the stop time} $(date); rerun to continue" >> $L; else echo "finished $(date), load $(sysctl -n vm.loadavg)" >> $L; fi
