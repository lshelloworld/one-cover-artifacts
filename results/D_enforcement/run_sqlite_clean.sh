#!/bin/bash
# Experiment D on SQLite on the laptop with load logged. Do not run during the MySQL runs.
# Writes to results/D_enforcement/sqlite_laptop_clean/, leaving the paper's results alone.
cd "$(dirname "$0")/../.."
OUT=results/D_enforcement/sqlite_laptop_clean; M=results/D_enforcement/mysql_keysets.log; PY=~/.venvs/onecover-artifacts/bin/python
mkdir -p $OUT; L=$OUT/run.log
( while :; do echo "$(date +%H:%M:%S) $(sysctl -n vm.loadavg)"; sleep 15; done ) > $OUT/load.log &
LOADER=$!
echo "started $(date), load $(sysctl -n vm.loadavg)" > $L
ps -axo %cpu,command | sort -nr | head -5 | cut -c1-110 >> $L
ONECOVER_D_OUT=$OUT caffeinate -i $PY -u experiments/D_enforcement/exp_db2.py >> $L 2>&1 || echo FAILED >> $L
kill $LOADER
echo "finished $(date), load $(sysctl -n vm.loadavg)" >> $L
