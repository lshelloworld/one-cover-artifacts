#!/bin/bash
# Repeat of one MySQL size with both sides measured in one sitting, to check results whose input and cover
# sides were measured on different nights. Records go to their own files, so the earlier ones stay as they are.
# Usage: run_mysql_repeat.sh <keyset> <m> [<stop "YYYY-MM-DD HH:MM">]
# Waits for mains power; terminates at the stop time or when the laptop leaves mains power (times on battery
# are not comparable). A finished side is checkpointed; rerunning redoes only an unfinished side.
# Records in db2_mysql_ks<k>_repeat.jsonl, log in mysql_repeat.log, load every 10 minutes in mysql_repeat_load.log.
cd "$(dirname "$0")/../.."
KS=$1; M=$2; STOP=${3:-}; D=results/D_enforcement; L=$D/mysql_repeat.log; PY=~/.venvs/onecover-artifacts/bin/python
T1=0; [ -z "$STOP" ] || T1=$(date -j -f "%Y-%m-%d %H:%M" "$STOP" +%s)
flush() { $PY -c "import sys; sys.path.insert(0,'.'); from config import MYSQL; import mysql.connector as m; c=m.connect(**MYSQL); k=c.cursor(); k.execute(sys.argv[1]); r=k.fetchall() if k.with_rows else None; print(r[0][0] if r else '')" "$1"; }
echo "waiting since $(date) for mains power and no other MySQL run, key set $KS, m=$M, stop at ${STOP:-none}" >> $L
until pmset -g ps | grep -q "AC Power" && ! pgrep -f exp_db2_mysql.py > /dev/null; do sleep 60; done
F0=$(flush 'SELECT @@GLOBAL.innodb_flush_log_at_trx_commit')
( while :; do echo "$(date '+%d %H:%M') $(sysctl -n vm.loadavg)"; sleep 600; done ) >> $D/mysql_repeat_load.log &
LOADER=$!
echo "started $(date), load $(sysctl -n vm.loadavg), flush setting $F0" >> $L
ps -axo %cpu,command | sort -nr | head -5 | cut -c1-110 >> $L
ONECOVER_KEYSET=$KS ONECOVER_XL_OUT=$D/db2_pg_extra_ks$KS.jsonl ONECOVER_MYSQL_OUT=$D/db2_mysql_ks${KS}_repeat.jsonl \
  $PY -u experiments/D_enforcement/exp_db2_mysql.py xl perkey $M >> $L 2>&1 &
PID=$!
caffeinate -i -w $PID &
WHY=
while kill -0 $PID 2>/dev/null; do
  if [ "$T1" -gt 0 ] && [ "$(date +%s)" -ge "$T1" ]; then WHY="at the stop time"; break; fi
  pmset -g ps | grep -q "AC Power" || { WHY="on leaving mains power"; break; }
  sleep 30
done
[ -n "$WHY" ] && kill -TERM $PID
wait $PID
kill $LOADER
flush "SET GLOBAL innodb_flush_log_at_trx_commit = $F0"
echo "flush setting now $(flush 'SELECT @@GLOBAL.innodb_flush_log_at_trx_commit')" >> $L
if [ -n "$WHY" ]; then echo "STOPPED $WHY $(date); rerun to continue" >> $L; else echo "finished $(date), load $(sysctl -n vm.loadavg)" >> $L; fi
