#!/bin/bash
# Rerun of Experiment E on the private PostgreSQL 18 cluster (port 5488, open-file limit 10240), queued to start
# once no MySQL run (run_mysql_keysets.sh or exp_db2_mysql.py) is going and the laptop is on mains power.
# Records go to real_pg_rerun.jsonl and voc_pg_rerun.jsonl, so the records in the paper stay as they are.
# Log in E_rerun.log, load every minute in E_rerun_load.log. Stops if the laptop leaves mains power.
# Usage: run_E_after_mysql.sh <directory of the cluster> [<tag for the output files, default _rerun>]
cd "$(dirname "$0")/../.."
TAG=${2:-_rerun}; PG=${PGBIN:-/Library/PostgreSQL/18/bin}; C=$1; PORT=5488; E=results/E_real_tables; L=$E/E${TAG}.log; PY=~/.venvs/onecover-artifacts/bin/python
echo "waiting since $(date) for MySQL to finish and mains power" >> $L
until pmset -g ps | grep -q "AC Power" && ! pgrep -f 'run_mysql_keysets.sh|exp_db2_mysql.py' >/dev/null; do sleep 60; done
sleep 120   # let MySQL settle after its run
ulimit -n 10240
"$PG/pg_ctl" -D "$C" -o "-p $PORT -c max_files_per_process=9000 -c listen_addresses=localhost -c unix_socket_directories=''" -l "$C/server.log" -w start >/dev/null
( while :; do echo "$(date '+%d %H:%M') $(sysctl -n vm.loadavg)"; sleep 60; done ) >> $E/E${TAG}_load.log &
LOADER=$!
echo "started $(date), open-file limit $(ulimit -n), $("$PG/postgres" --version), load $(sysctl -n vm.loadavg)" >> $L
ps -axo %cpu,command | sort -nr | head -5 | cut -c1-110 >> $L
export ONECOVER_DB_PORT=$PORT ONECOVER_DB_NAME=onecover PGGSSENCMODE=disable ONECOVER_E_OUT=$E/real_pg${TAG}.jsonl ONECOVER_VOC_OUT=$E/voc_pg${TAG}.jsonl
"$PG/psql" -h localhost -p $PORT -U postgres -Atc "SELECT 1 FROM pg_database WHERE datname='onecover'" | grep -q 1 || "$PG/createdb" -h localhost -p $PORT -U postgres onecover
WHY=
for s in exp_real_pg.py exp_voc.py; do
  echo "== $s $(date)" >> $L
  caffeinate -i $PY -u experiments/E_real_tables/$s >> $L 2>&1 &
  P=$!
  while kill -0 $P 2>/dev/null; do pmset -g ps | grep -q "AC Power" || { WHY="on leaving mains power"; kill -TERM $P; break; }; sleep 15; done
  wait $P || [ -n "$WHY" ] || echo "FAILED $s" >> $L
  [ -n "$WHY" ] && break
done
kill $LOADER
"$PG/pg_ctl" -D "$C" -m fast -w stop >/dev/null
if [ -n "$WHY" ]; then echo "STOPPED $WHY $(date); rerun to continue" >> $L; else echo "finished $(date), load $(sysctl -n vm.loadavg)" >> $L; fi
