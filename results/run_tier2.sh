#!/bin/bash
# Robustness experiments (tier 2), one after another, on the laptop:
#   1. Algorithm 2 stress test                                  (minutes)
#   2. Experiment D, 75 configurations x 5 repetitions, SQLite  (about an hour)
#   3. the same on PostgreSQL                                   (about two hours)
#   4. Experiment D on wider schemas (16/24/32 columns), SQLite and PostgreSQL
#   5. million-row PostgreSQL runs: key set 3, and a second run of key sets 1 and 2 (about 18 hours)
# Waits for mains power and for no MySQL run; PostgreSQL is the private cluster (port 5488, open-file limit
# 10240). Stops on leaving mains power; rerunning skips finished steps and configurations.
# Log results/tier2.log, load every minute in results/tier2_load.log.
# Usage: run_tier2.sh <directory of the cluster>
cd "$(dirname "$0")/.."
PG=${PGBIN:-/Library/PostgreSQL/18/bin}; C=$1; PORT=5488; L=results/tier2.log; PY=~/.venvs/onecover-artifacts/bin/python
echo "waiting since $(date) for mains power and no MySQL run" >> $L
until pmset -g ps | grep -q "AC Power" && ! pgrep -f 'exp_db2_mysql.py|run_mysql' >/dev/null; do sleep 60; done
ulimit -n 10240
"$PG/pg_ctl" -D "$C" -o "-p $PORT -c max_files_per_process=9000 -c listen_addresses=localhost -c unix_socket_directories=''" -l "$C/server.log" -w start >/dev/null
( while :; do echo "$(date '+%d %H:%M') $(sysctl -n vm.loadavg)"; sleep 60; done ) >> results/tier2_load.log &
LOADER=$!
echo "started $(date), load $(sysctl -n vm.loadavg), $("$PG/postgres" --version)" >> $L
ps -axo %cpu,command | sort -nr | head -5 | cut -c1-110 >> $L
export ONECOVER_DB_PORT=$PORT ONECOVER_DB_NAME=postgres PGGSSENCMODE=disable
WHY=
step() {   # step <name> <command...>: skipped if done before
  [ -n "$WHY" ] && return
  grep -qx "done $1" $L && { echo "skip $1 (done before)" >> $L; return; }
  echo "== $1 $(date)" >> $L
  caffeinate -i "${@:2}" >> $L 2>&1 &
  P=$!
  while kill -0 $P 2>/dev/null; do pmset -g ps | grep -q "AC Power" || { WHY="on leaving mains power"; pkill -TERM -P $P; kill -TERM $P; break; }; sleep 20; done
  wait $P; rc=$?
  if [ -n "$WHY" ]; then echo "stopped $1" >> $L; elif [ $rc -eq 0 ]; then echo "done $1" >> $L; else echo "FAILED $1 (exit $rc)" >> $L; fi
}
D=results/D_enforcement
step alg2        $PY -u experiments/A-C_random_covers/exp_alg2_stress.py
step reps_sqlite $PY -u experiments/D_enforcement/exp_db2_tier2.py reps sqlite 5
step reps_pg     $PY -u experiments/D_enforcement/exp_db2_tier2.py reps pg 5
step wide_sqlite $PY -u experiments/D_enforcement/exp_db2_tier2.py wide sqlite 3
step wide_pg     $PY -u experiments/D_enforcement/exp_db2_tier2.py wide pg 3
step xl_ks3      env ONECOVER_KEYSET=3 ONECOVER_XL_OUT=$D/db2_pg_extra_ks3.jsonl $PY -u experiments/D_enforcement/exp_db2_pg_extra.py xl 30,40,50
step xl_ks1_rep2 env ONECOVER_KEYSET=1 ONECOVER_XL_OUT=$D/db2_pg_extra_ks1_rep2.jsonl $PY -u experiments/D_enforcement/exp_db2_pg_extra.py xl 30,40,50
step xl_ks2_rep2 env ONECOVER_KEYSET=2 ONECOVER_XL_OUT=$D/db2_pg_extra_ks2_rep2.jsonl $PY -u experiments/D_enforcement/exp_db2_pg_extra.py xl 30,40,50
kill $LOADER
"$PG/pg_ctl" -D "$C" -m fast -w stop >/dev/null
if [ -n "$WHY" ]; then echo "STOPPED $WHY $(date); rerun to continue" >> $L; else echo "finished $(date), load $(sysctl -n vm.loadavg)" >> $L; fi
