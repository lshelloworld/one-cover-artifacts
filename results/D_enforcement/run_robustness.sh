#!/bin/bash
# Two robustness runs that leave the paper's results untouched: Experiment D on SQLite on the laptop
# (results/D_enforcement/sqlite_laptop/), then a second 1M-row PostgreSQL run at |Sigma| = 30, 40, 50
# with the same key sets and workload (results/D_enforcement/db2_pg_extra_run2.jsonl).
# Usage: run_robustness.sh <directory of the cluster>
cd "$(dirname "$0")/../.."
PG=${PGBIN:-/Library/PostgreSQL/18/bin}; D=$1; L=results/D_enforcement/robustness.log; PY=~/.venvs/onecover-artifacts/bin/python
echo "== SQLite started $(date), load $(sysctl -n vm.loadavg)" > $L
ONECOVER_D_OUT=results/D_enforcement/sqlite_laptop caffeinate -i $PY -u experiments/D_enforcement/exp_db2.py >> $L 2>&1 || echo FAILED SQLite >> $L
ulimit -n 10240
"$PG/pg_ctl" -D "$D" -o "-p 5488 -c max_files_per_process=9000 -c listen_addresses=localhost -c unix_socket_directories=''" -l "$D/server.log" -w start >/dev/null
echo "== 1M rows started $(date), load $(sysctl -n vm.loadavg)" >> $L
ps -axo %cpu,command | sort -nr | head -5 | cut -c1-120 >> $L
ONECOVER_XL_OUT=results/D_enforcement/db2_pg_extra_run2.jsonl ONECOVER_DB_PORT=5488 ONECOVER_DB_NAME=postgres PGGSSENCMODE=disable \
  caffeinate -i $PY -u experiments/D_enforcement/exp_db2_pg_extra.py xl 30,40,50 >> $L 2>&1 || echo FAILED 1M >> $L
"$PG/pg_ctl" -D "$D" -m fast -w stop >/dev/null
echo "finished $(date), load $(sysctl -n vm.loadavg)" >> $L
