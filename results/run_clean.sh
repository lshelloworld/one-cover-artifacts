#!/bin/bash
# Experiments D, E and F on the private PostgreSQL 18 cluster (open-file limit 10240,
# max_files_per_process 9000), one after another, with machine load logged every minute in
# clean_run_load.log. The naive baseline goes to D_enforcement/naive_clean.jsonl.
# Usage: run_clean.sh <directory of the cluster>
cd "$(dirname "$0")/.."
PG=${PGBIN:-/Library/PostgreSQL/18/bin}; D=$1; PORT=5488; L=results/clean_run.log; PY=~/.venvs/onecover-artifacts/bin/python
[ -d "$D/base" ] || "$PG/initdb" -D "$D" -U postgres -A trust --no-locale -E UTF8 >/dev/null
ulimit -n 10240
"$PG/pg_ctl" -D "$D" -o "-p $PORT -c max_files_per_process=9000 -c listen_addresses=localhost -c unix_socket_directories=''" -l "$D/server.log" -w start >/dev/null
( while :; do echo "$(date +%H:%M) $(sysctl -n vm.loadavg)"; sleep 60; done ) > results/clean_run_load.log &
LOADER=$!
echo "started $(date), open-file limit $(ulimit -n), $("$PG/postgres" --version)" > $L
ps -axo %cpu,command | sort -nr | head -5 | cut -c1-110 >> $L
export ONECOVER_DB_PORT=$PORT PGGSSENCMODE=disable
run() { echo "== $* $(date)" >> $L; caffeinate -i $PY -u experiments/"$@" >> $L 2>&1 || echo "FAILED $*" >> $L; }
export ONECOVER_DB_NAME=postgres
run D_enforcement/exp_db2_pg.py 1
run D_enforcement/exp_check_plan.py
ONECOVER_XL_OUT=results/D_enforcement/naive_clean.jsonl run D_enforcement/exp_db2_pg_extra.py naive
export ONECOVER_DB_NAME=onecover
"$PG/psql" -h localhost -p $PORT -U postgres -Atc "SELECT 1 FROM pg_database WHERE datname='onecover'" | grep -q 1 || "$PG/createdb" -h localhost -p $PORT -U postgres onecover
run E_real_tables/exp_real_pg.py
run E_real_tables/exp_voc.py
export ONECOVER_DB_NAME=postgres
for a in "exp_queries.py" "exp_queries2.py" "exp_queries3.py" "exp_queries.py 100" "exp_queries2.py 100"; do run F_query_optimisation/$a; done
kill $LOADER
"$PG/pg_ctl" -D "$D" -m fast -w stop >/dev/null
echo "finished $(date), load $(sysctl -n vm.loadavg)" >> $L
