#!/bin/bash
# Concurrency experiment, full runs at 30,000 rows (100,000 would take ~9 hours under the emulation).
# Waits for the smoke test to end; nothing new starts after STOP.  Usage: run_concurrency2.sh [HH:MM]
cd "$(dirname "$0")/../.."; PY=~/.venvs/onecover-artifacts/bin/python; L=results/D_native/concurrency.log
STOP=${1:-07:30}; export ONECOVER_DB_PORT=${ONECOVER_DB_PORT:-5488} ONECOVER_DB_NAME=${ONECOVER_DB_NAME:-e_native} PGGSSENCMODE=disable
while pgrep -f "concurrency_smoke" >/dev/null; do sleep 15; done
grep -q "^done" results/D_native/concurrency.log || { echo "smoke did not finish cleanly; full runs not started $(date)" >> $L; exit 1; }
for km in 1:40 2:50; do
  IFS=: read k m <<< "$km"; echo "== ks$k m=$m rows 30000 $(date) load $(sysctl -n vm.loadavg)" >> $L
  caffeinate -i $PY -u experiments/D_native/exp_concurrency.py --keyset $k --m $m --rows 30000 --clients 1,4,8 --cap 600 \
    --stop $STOP >> $L 2>&1 || echo "FAILED ks$k m=$m" >> $L
done
echo "finished $(date)" >> $L
