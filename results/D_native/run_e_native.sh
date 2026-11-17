#!/bin/bash
# Experiment E with the native index: waits for a 5-minute load below 6 and mains power before each data set.
cd "$(dirname "$0")/../.."; PY=~/.venvs/onecover-artifacts/bin/python; L=results/D_native/e_native.log
ready() { while :; do l=$(sysctl -n vm.loadavg | awk '{print $3}')
  if awk -v l=$l 'BEGIN{exit !(l<6)}' && pmset -g batt | grep -q "AC Power"; then break; fi; sleep 60; done; }
export ONECOVER_DB_PORT=${ONECOVER_DB_PORT:-5488} ONECOVER_DB_NAME=${ONECOVER_DB_NAME:-e_native} ONECOVER_MAXLOAD=${ONECOVER_MAXLOAD:-6}
for d in "$@"; do
  ready; echo "== $d $(date) load $(sysctl -n vm.loadavg)" >> $L
  caffeinate -i $PY -u experiments/D_native/exp_e_native.py $d >> $L 2>&1 || echo "FAILED $d" >> $L
done
echo "finished $(date) load $(sysctl -n vm.loadavg)" >> $L
