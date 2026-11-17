#!/bin/bash
# Experiment F, batch 2 at x100, on the private PostgreSQL 18 cluster (open-file limit raised, see
# results/D_enforcement/run_pg18.sh). Usage: run_pg18_batch2_x100.sh <directory for the cluster>
set -u
cd "$(dirname "$0")/../.."
PG=${PGBIN:-/Library/PostgreSQL/18/bin}; D=$1; PORT=5488; L=results/F_query_optimisation/batch2_x100_rerun.log
ulimit -n 10240
"$PG/pg_ctl" -D "$D" -o "-p $PORT -c max_files_per_process=9000 -c listen_addresses=localhost -c unix_socket_directories=''" -l "$D/server.log" -w start >/dev/null
export ONECOVER_DB_PORT=$PORT ONECOVER_DB_NAME=postgres PGGSSENCMODE=disable
echo "started $(date), load $(sysctl -n vm.loadavg)" > $L
ps -Ao pcpu,command -r | sed -n 2,6p | cut -c1-110 >> $L
caffeinate -i ~/.venvs/onecover-artifacts/bin/python -u experiments/F_query_optimisation/exp_queries2.py 100 >> $L 2>&1 || echo FAILED >> $L
echo "finished $(date), load $(sysctl -n vm.loadavg)" >> $L
"$PG/pg_ctl" -D "$D" -m fast -w stop >/dev/null
