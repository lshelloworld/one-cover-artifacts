#!/bin/bash
# Experiment D extras on PostgreSQL 18 in the private cluster (open-file limit 10240,
# max_files_per_process 9000): planning cost of the integrity check, naive triggers, 100k rows.
# Usage: run_pg18_extras.sh <directory of the cluster>
cd "$(dirname "$0")/../.."
PG=${PGBIN:-/Library/PostgreSQL/18/bin}; D=$1; L=results/D_enforcement/pg18_extras.log
[ -d "$D/base" ] || "$PG/initdb" -D "$D" -U postgres -A trust --no-locale -E UTF8 >/dev/null
ulimit -n 10240
"$PG/pg_ctl" -D "$D" -o "-p 5488 -c max_files_per_process=9000 -c listen_addresses=localhost -c unix_socket_directories=''" -l "$D/server.log" -w start >/dev/null
echo "started $(date), open-file limit $(ulimit -n), $("$PG/postgres" --version)" > $L
export ONECOVER_DB_PORT=5488 ONECOVER_DB_NAME=postgres PGGSSENCMODE=disable
for args in "exp_check_plan.py" "exp_db2_pg_extra.py naive" "exp_db2_pg_extra.py large"; do
  echo "== $args $(date)" >> $L
  caffeinate -i ~/.venvs/onecover-artifacts/bin/python -u experiments/D_enforcement/$args >> $L 2>&1 || echo "FAILED $args" >> $L
done
"$PG/pg_ctl" -D "$D" -m fast -w stop >/dev/null
echo "finished $(date)" >> $L
