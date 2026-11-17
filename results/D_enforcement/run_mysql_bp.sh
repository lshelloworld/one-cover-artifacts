#!/bin/bash
# One MySQL size, both sides in one sitting, with the InnoDB buffer pool set to <MB> for the run (it is
# resized online and set back afterwards). Tests whether the 128 MB default pool limits the cover's gains.
# Usage: run_mysql_bp.sh <keyset> <m> <MB>. Records in db2_mysql_ks<k>_bp<MB>.jsonl, log mysql_bp.log,
# load every 10 minutes in mysql_bp_load.log. Stops if the laptop leaves mains power.
cd "$(dirname "$0")/../.."
KS=$1; M=$2; MB=$3; D=results/D_enforcement; L=$D/mysql_bp.log; PY=~/.venvs/onecover-artifacts/bin/python
q() { $PY -c "import sys; sys.path.insert(0,'.'); from config import MYSQL; import mysql.connector as m; c=m.connect(**MYSQL); k=c.cursor(); k.execute(sys.argv[1]); r=k.fetchall() if k.with_rows else None; print(r[0][0] if r else '')" "$1"; }
echo "waiting since $(date) for mains power and no other MySQL run, key set $KS, m=$M, buffer pool $MB MB" >> $L
until pmset -g ps | grep -q "AC Power" && ! pgrep -f exp_db2_mysql.py > /dev/null; do sleep 60; done
F0=$(q 'SELECT @@GLOBAL.innodb_flush_log_at_trx_commit'); B0=$(q 'SELECT @@GLOBAL.innodb_buffer_pool_size')
q "SET GLOBAL innodb_buffer_pool_size = $((MB*1048576))"
until q "SHOW STATUS LIKE 'Innodb_buffer_pool_resize_status_code'" | grep -q . ; do sleep 2; done; sleep 20
echo "buffer pool now $(q 'SELECT @@GLOBAL.innodb_buffer_pool_size') bytes (was $B0)" >> $L
( while :; do echo "$(date '+%d %H:%M') $(sysctl -n vm.loadavg)"; sleep 600; done ) >> $D/mysql_bp_load.log &
LOADER=$!
echo "started $(date), load $(sysctl -n vm.loadavg), flush setting $F0" >> $L
ONECOVER_KEYSET=$KS ONECOVER_XL_OUT=$D/db2_pg_extra_ks$KS.jsonl ONECOVER_MYSQL_OUT=$D/db2_mysql_ks${KS}_bp$MB.jsonl \
  $PY -u experiments/D_enforcement/exp_db2_mysql.py xl perkey $M >> $L 2>&1 &
PID=$!; caffeinate -i -w $PID &
WHY=
while kill -0 $PID 2>/dev/null; do pmset -g ps | grep -q "AC Power" || { WHY="on leaving mains power"; break; }; sleep 30; done
[ -n "$WHY" ] && kill -TERM $PID
wait $PID; kill $LOADER
q "SET GLOBAL innodb_flush_log_at_trx_commit = $F0"; q "SET GLOBAL innodb_buffer_pool_size = $B0"; sleep 20
echo "flush setting now $(q 'SELECT @@GLOBAL.innodb_flush_log_at_trx_commit'), buffer pool now $(q 'SELECT @@GLOBAL.innodb_buffer_pool_size') bytes" >> $L
if [ -n "$WHY" ]; then echo "STOPPED $WHY $(date); rerun to continue" >> $L; else echo "finished $(date), load $(sysctl -n vm.loadavg)" >> $L; fi
