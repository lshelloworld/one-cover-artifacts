#!/bin/bash
# MySQL diagnostic (exp_mysql_diag.py, key set 2, |Sigma|=40, 100,000 inserts), queued after the buffer-pool test.
# The tier 2 queue waits while this script exists. Log mysql_diag.log, load every minute in mysql_diag_load.log.
cd "$(dirname "$0")/../.."
D=results/D_enforcement; L=$D/mysql_diag.log; PY=~/.venvs/onecover-artifacts/bin/python
echo "waiting since $(date) for the buffer-pool test and mains power" >> $L
until pmset -g ps | grep -q "AC Power" && ! pgrep -f 'run_mysql_bp.sh|exp_db2_mysql.py' >/dev/null; do sleep 30; done
( while :; do echo "$(date '+%d %H:%M') $(sysctl -n vm.loadavg)"; sleep 60; done ) >> $D/mysql_diag_load.log &
LOADER=$!
echo "started $(date), load $(sysctl -n vm.loadavg)" >> $L
caffeinate -i $PY -u experiments/D_enforcement/exp_mysql_diag.py 2 40 100000 >> $L 2>&1 &
P=$!; WHY=
while kill -0 $P 2>/dev/null; do pmset -g ps | grep -q "AC Power" || { WHY="on leaving mains power"; kill -TERM $P; break; }; sleep 20; done
wait $P; kill $LOADER
/usr/local/mysql/bin/mysql -N -e "SELECT @@GLOBAL.innodb_flush_log_at_trx_commit" | sed 's/^/flush setting now /' >> $L
if [ -n "$WHY" ]; then echo "STOPPED $WHY $(date)" >> $L; else echo "finished $(date), load $(sysctl -n vm.loadavg)" >> $L; fi
