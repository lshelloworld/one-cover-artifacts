#!/bin/bash
# Concurrency experiment, three repetitions on a quiet machine: key set 1 at 40 keys and key set 2 at 50 keys,
# 30,000 rows, 1/4/8 clients, all four schemes. Repetitions interleave: repetition 1 runs the configurations
# (and the key sets) in reverse order. Each process starts only at a 5-minute load below 6; nothing new starts
# after STOP. Records: concurrency_reps.jsonl (resumable); console: concurrency_reps.log; load every 10 minutes:
# concurrency_reps_load.log. Usage: run_concurrency_reps.sh [HH:MM]
cd "$(dirname "$0")/../.."; PY=${PY:-~/.venvs/onecover-artifacts/bin/python}
L=results/D_native/concurrency_reps.log; OUT=results/D_native/concurrency_reps.jsonl
STOP=${1:-07:30}; export ONECOVER_DB_PORT=${ONECOVER_DB_PORT:-5488} ONECOVER_DB_NAME=${ONECOVER_DB_NAME:-e_native} PGGSSENCMODE=disable
( while :; do echo "$(date +%H:%M) $(sysctl -n vm.loadavg)"; sleep 600; done ) > results/D_native/concurrency_reps_load.log &
LOADER=$!; trap 'kill $LOADER 2>/dev/null' EXIT
echo "started $(date), load $(sysctl -n vm.loadavg), stop at $STOP" >> $L
late() { now=$(date +%H:%M); [[ "$now" > "$STOP" && "$now" < "12:00" ]]; }
for r in 0 1 2; do
  if [ $((r % 2)) -eq 1 ]; then SETS="2:50 1:40"; REV=--reverse; else SETS="1:40 2:50"; REV=; fi
  for km in $SETS; do
    IFS=: read k m <<< "$km"
    while sysctl -n vm.loadavg | awk '{exit !($3 >= 6)}'; do      # field 3 is the 5-minute load
      late && { echo "stopped waiting for a quiet machine: past $STOP $(date)" >> $L; exit 0; }; sleep 60; done
    late && { echo "stopped: past $STOP $(date)" >> $L; exit 0; }
    echo "== rep $r ks$k m=$m $(date) load $(sysctl -n vm.loadavg)" >> $L
    caffeinate -i $PY -u experiments/D_native/exp_concurrency.py --keyset $k --m $m --rows 30000 --clients 1,4,8 --cap 600 \
      --stop $STOP --rep $r $REV --out $OUT >> $L 2>&1 || echo "FAILED rep $r ks$k m=$m" >> $L
  done
done
echo "finished $(date)" >> $L
