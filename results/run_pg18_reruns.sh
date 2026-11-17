#!/bin/bash
# Experiment F (x1 and x100) and Experiment D at scale (1M rows) on PostgreSQL 18 in a private cluster
# with a raised open-file limit (see results/D_enforcement/run_pg18.sh for why).
# Usage: run_pg18_reruns.sh <directory for the cluster>
set -u
cd "$(dirname "$0")/.."
PG=${PGBIN:-/Library/PostgreSQL/18/bin}; D=$1; PORT=5488
FL=results/F_query_optimisation/pg18_rerun.log; DL=results/D_enforcement/xl_run.log
[ -d "$D/base" ] || "$PG/initdb" -D "$D" -U postgres -A trust --no-locale -E UTF8 >/dev/null
ulimit -n 10240
"$PG/pg_ctl" -D "$D" -o "-p $PORT -c max_files_per_process=9000 -c listen_addresses=localhost -c unix_socket_directories=''" -l "$D/server.log" -w start >/dev/null
export ONECOVER_DB_PORT=$PORT ONECOVER_DB_NAME=postgres PGGSSENCMODE=disable
PY=~/.venvs/onecover-artifacts/bin/python
echo "started $(date), open-file limit $(ulimit -n), $("$PG/postgres" --version)" > $FL
for args in "exp_queries.py" "exp_queries2.py" "exp_queries3.py" "exp_queries.py 100" "exp_queries2.py 100"; do
  echo "== $args $(date)" >> $FL
  caffeinate -i $PY -u experiments/F_query_optimisation/$args >> $FL 2>&1 || echo "FAILED $args" >> $FL
done
echo "finished $(date)" >> $FL
echo "started $(date), open-file limit $(ulimit -n), $("$PG/postgres" --version)" > $DL
caffeinate -i $PY -u experiments/D_enforcement/exp_db2_pg_extra.py xl >> $DL 2>&1 || echo "FAILED" >> $DL
echo "finished $(date)" >> $DL
"$PG/pg_ctl" -D "$D" -m fast -w stop >/dev/null
