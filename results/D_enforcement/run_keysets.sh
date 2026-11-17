#!/bin/bash
# 1M-row PostgreSQL runs on freshly drawn key sets, to see how much the gains depend on the key set.
# Key sets 1 and 2 at |Sigma| = 30, 40, 50; records in db2_pg_extra_ks<k>.jsonl, machine load every
# 10 minutes in keysets_load.log. Usage: run_keysets.sh <directory of the cluster>
cd "$(dirname "$0")/../.."
PG=${PGBIN:-/Library/PostgreSQL/18/bin}; D=$1; L=results/D_enforcement/keysets.log; PY=~/.venvs/onecover-artifacts/bin/python
[ -d "$D/base" ] || "$PG/initdb" -D "$D" -U postgres -A trust --no-locale -E UTF8 >/dev/null
ulimit -n 10240
"$PG/pg_ctl" -D "$D" -o "-p 5488 -c max_files_per_process=9000 -c listen_addresses=localhost -c unix_socket_directories=''" -l "$D/server.log" -w start >/dev/null
( while :; do echo "$(date +%H:%M) $(sysctl -n vm.loadavg)"; sleep 600; done ) > results/D_enforcement/keysets_load.log &
LOADER=$!
echo "started $(date), load $(sysctl -n vm.loadavg)" > $L
for k in 1 2; do
  echo "== key set $k $(date)" >> $L
  ONECOVER_KEYSET=$k ONECOVER_XL_OUT=results/D_enforcement/db2_pg_extra_ks$k.jsonl ONECOVER_DB_PORT=5488 ONECOVER_DB_NAME=postgres PGGSSENCMODE=disable \
    caffeinate -i $PY -u experiments/D_enforcement/exp_db2_pg_extra.py xl 30,40,50 >> $L 2>&1 || echo "FAILED key set $k" >> $L
done
kill $LOADER
"$PG/pg_ctl" -D "$D" -m fast -w stop >/dev/null
echo "finished $(date), load $(sysctl -n vm.loadavg)" >> $L
