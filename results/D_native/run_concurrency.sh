#!/bin/bash
# Concurrency experiment, queued after the million-row native runs (no load checks; nothing new after STOP).
# Usage: run_concurrency.sh [HH:MM]
cd "$(dirname "$0")/../.."; PY=~/.venvs/onecover-artifacts/bin/python; L=results/D_native/concurrency.log
STOP=${1:-07:30}; export ONECOVER_DB_PORT=${ONECOVER_DB_PORT:-5488} ONECOVER_DB_NAME=${ONECOVER_DB_NAME:-e_native} PGGSSENCMODE=disable
echo "queued $(date), waiting for the million-row runs" >> $L
until grep -qE '^(finished|STOPPED)' results/D_native/dxl_native.log; do sleep 30; done
echo "== smoke $(date)" >> $L
caffeinate -i $PY -u experiments/D_native/exp_concurrency.py --keyset 1 --m 40 --rows 3000 --clients 1,4 --cap 120 \
  --out results/D_native/concurrency_smoke.jsonl >> $L 2>&1 || { echo "FAILED smoke; full runs not started" >> $L; exit 1; }
for km in 1:40 2:50; do
  IFS=: read k m <<< "$km"; echo "== ks$k m=$m $(date) load $(sysctl -n vm.loadavg)" >> $L
  caffeinate -i $PY -u experiments/D_native/exp_concurrency.py --keyset $k --m $m --rows 100000 --clients 1,4,8 --cap 900 \
    --stop $STOP >> $L 2>&1 || echo "FAILED ks$k m=$m" >> $L
done
echo "finished $(date)" >> $L
