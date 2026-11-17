#!/bin/bash
# Experiment D at scale with the native index: key sets 1-3 at |Sigma| = 30, 40, 50 (no load checks).
# Usage: run_dxl_native.sh [HH:MM]  -- start no new size after this time of day (default 07:30)
cd "$(dirname "$0")/../.."; PY=~/.venvs/onecover-artifacts/bin/python; L=results/D_native/dxl_native.log
STOP=${1:-07:30}; export ONECOVER_DB_PORT=${ONECOVER_DB_PORT:-5488} ONECOVER_DB_NAME=${ONECOVER_DB_NAME:-e_native} PGGSSENCMODE=disable
late() { now=$(date +%H:%M); [[ "$now" > "$STOP" && "$now" < "12:00" ]]; }
echo "start $(date), stop starting new sizes after $STOP" >> $L
for k in 1 2 3; do for m in 30 40 50; do
  if late; then echo "STOPPED before ks$k m=$m at $(date)" >> $L; exit 0; fi
  echo "== ks$k m=$m $(date) load $(sysctl -n vm.loadavg)" >> $L
  ONECOVER_KEYSET=$k caffeinate -i $PY -u experiments/D_native/exp_dxl_native.py $m >> $L 2>&1 || echo "FAILED ks$k m=$m" >> $L
done; done
echo "finished $(date)" >> $L
