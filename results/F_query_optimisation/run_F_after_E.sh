#!/bin/bash
# Rerun of Experiment F on the private PostgreSQL 18 cluster (port 5488, open-file limit 10240), queued to start once
# the Experiment E rerun (run_E_after_mysql.sh) has finished and the laptop is on mains power. Records go to
# <name>_rerun.json and <name>_x100_rerun.json, so the files in the paper stay as they are.
# Log in F_rerun.log, load every minute in F_rerun_load.log. Stops if the laptop leaves mains power.
# Usage: run_F_after_E.sh <directory of the cluster> [<tag for the output files, default _rerun>]
cd "$(dirname "$0")/../.."
TAG=${2:-_rerun}; PG=${PGBIN:-/Library/PostgreSQL/18/bin}; C=$1; PORT=5488; F=results/F_query_optimisation; L=$F/F${TAG}.log; PY=~/.venvs/onecover-artifacts/bin/python
echo "waiting since $(date) for the E rerun to finish and mains power" >> $L
until pmset -g ps | grep -q "AC Power" && ! pgrep -f 'run_E_after_mysql.sh|run_mysql_keysets.sh|exp_db2_mysql.py' >/dev/null; do sleep 20; done
ulimit -n 10240
"$PG/pg_ctl" -D "$C" -o "-p $PORT -c max_files_per_process=9000 -c listen_addresses=localhost -c unix_socket_directories=''" -l "$C/server.log" -w start >/dev/null
( while :; do echo "$(date '+%d %H:%M') $(sysctl -n vm.loadavg)"; sleep 60; done ) >> $F/F${TAG}_load.log &
LOADER=$!
echo "started $(date), open-file limit $(ulimit -n), $("$PG/postgres" --version), load $(sysctl -n vm.loadavg)" >> $L
ps -axo %cpu,command | sort -nr | head -5 | cut -c1-110 >> $L
export ONECOVER_DB_PORT=$PORT ONECOVER_DB_NAME=postgres PGGSSENCMODE=disable ONECOVER_F_TAG=$TAG
WHY=
for a in "exp_queries.py" "exp_queries2.py" "exp_queries3.py" "exp_queries.py 100" "exp_queries2.py 100"; do
  echo "== $a $(date)" >> $L
  caffeinate -i $PY -u experiments/F_query_optimisation/$a >> $L 2>&1 &
  P=$!
  while kill -0 $P 2>/dev/null; do pmset -g ps | grep -q "AC Power" || { WHY="on leaving mains power"; kill -TERM $P; break; }; sleep 10; done
  wait $P || [ -n "$WHY" ] || echo "FAILED $a" >> $L
  [ -n "$WHY" ] && break
done
kill $LOADER
"$PG/pg_ctl" -D "$C" -m fast -w stop >/dev/null
if [ -n "$WHY" ]; then echo "STOPPED $WHY $(date)" >> $L; else echo "finished $(date), load $(sysctl -n vm.loadavg)" >> $L; fi
