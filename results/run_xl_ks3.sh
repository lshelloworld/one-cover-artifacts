#!/bin/bash
# Million-row PostgreSQL runs: key set 3 at |Sigma| = 30, 40, 50, started once the machine is quiet (5-minute
# load below 6 for 10 minutes running) and on mains power; then, only if key set 3 is done before 01:30 on
# 16 November, the second run of key set 1. Stops on leaving mains power; a finished size is kept, and a rerun
# skips it. Private cluster on port 5488 (open-file limit 10240). Log results/xl.log, load every minute in
# results/xl_load.log. Usage: run_xl_ks3.sh <directory of the cluster>
cd "$(dirname "$0")/.."
PG=${PGBIN:-/Library/PostgreSQL/18/bin}; C=$1; PORT=5488; L=results/xl.log; D=results/D_enforcement; PY=~/.venvs/onecover-artifacts/bin/python
echo "waiting since $(date) for mains power and the 5-minute load below 6 for 10 minutes" >> $L
q=0; while [ $q -lt 10 ]; do l=$(sysctl -n vm.loadavg | awk '{print $3}')
  if pmset -g ps | grep -q "AC Power" && awk "BEGIN{exit !($l<6)}"; then q=$((q+1)); else q=0; fi; sleep 60; done
ulimit -n 10240
"$PG/pg_ctl" -D "$C" -o "-p $PORT -c max_files_per_process=9000 -c listen_addresses=localhost -c unix_socket_directories=''" -l "$C/server.log" -w start >/dev/null
( while :; do echo "$(date '+%d %H:%M') $(sysctl -n vm.loadavg)"; sleep 60; done ) >> results/xl_load.log &
LOADER=$!
echo "started $(date), load $(sysctl -n vm.loadavg)" >> $L
ps -axo %cpu,command | sort -nr | head -5 | cut -c1-110 >> $L
export ONECOVER_DB_PORT=$PORT ONECOVER_DB_NAME=postgres PGGSSENCMODE=disable
WHY=
xl() {   # xl <key set> <output file>
  echo "== key set $1 -> $2 $(date)" >> $L
  ONECOVER_KEYSET=$1 ONECOVER_XL_OUT=$2 caffeinate -i $PY -u experiments/D_enforcement/exp_db2_pg_extra.py xl 30,40,50 >> $L 2>&1 &
  P=$!
  while kill -0 $P 2>/dev/null; do pmset -g ps | grep -q "AC Power" || { WHY="on leaving mains power"; kill -TERM $P; break; }; sleep 20; done
  wait $P; rc=$?; [ -z "$WHY" ] && echo "done key set $1 (exit $rc) $(date)" >> $L; }
xl 3 $D/db2_pg_extra_ks3.jsonl
if [ -z "$WHY" ] && [ "$(date +%s)" -lt "$(date -j -f "%Y-%m-%d %H:%M" "2026-11-16 01:30" +%s)" ]; then
  xl 1 $D/db2_pg_extra_ks1_rep2.jsonl
elif [ -z "$WHY" ]; then echo "key set 3 finished after 01:30: second run of key set 1 not started" >> $L; fi
kill $LOADER
"$PG/pg_ctl" -D "$C" -m fast -w stop >/dev/null
if [ -n "$WHY" ]; then echo "STOPPED $WHY $(date); rerun to continue" >> $L; else echo "finished $(date), load $(sysctl -n vm.loadavg)" >> $L; fi
