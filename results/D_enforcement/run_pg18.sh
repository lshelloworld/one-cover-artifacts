#!/bin/bash
# Experiment D (75 runs) on PostgreSQL 18 in a private cluster with a raised open-file limit.
# The macOS default of 256 open files makes PostgreSQL close and reopen the files of a table's
# 400-odd filtered indexes on every insert, which slowed the input's inserts some 70-fold.
# Usage: run_pg18.sh <empty directory for the cluster>
set -eu
cd "$(dirname "$0")/../.."
PG=${PGBIN:-/Library/PostgreSQL/18/bin}; D=$1; PORT=5488; L=results/D_enforcement/pg18_run.log
[ -d "$D/base" ] || "$PG/initdb" -D "$D" -U postgres -A trust --no-locale -E UTF8 >/dev/null
ulimit -n 10240
"$PG/pg_ctl" -D "$D" -o "-p $PORT -c max_files_per_process=9000 -c listen_addresses=localhost -c unix_socket_directories=''" -l "$D/server.log" -w start >/dev/null
echo "started $(date), open-file limit $(ulimit -n), $("$PG/postgres" --version)" > $L
ONECOVER_DB_PORT=$PORT ONECOVER_DB_NAME=postgres PGGSSENCMODE=disable \
  caffeinate -i ~/.venvs/onecover-artifacts/bin/python -u experiments/D_enforcement/exp_db2_pg.py 1 >> $L 2>&1 || echo "FAILED $?" >> $L
"$PG/pg_ctl" -D "$D" -m fast -w stop >/dev/null
echo "finished $(date)" >> $L
