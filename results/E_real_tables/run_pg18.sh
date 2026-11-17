#!/bin/bash
# Experiment E's enforcement runs on the private PostgreSQL 18 cluster of results/run_pg18_reruns.sh
# (port 5488, open-file limit 10240), in their own database.
cd "$(dirname "$0")/../.."
L=results/E_real_tables/pg18_run.log
echo "started $(date)" > $L
export ONECOVER_DB_PORT=5488 ONECOVER_DB_NAME=onecover PGGSSENCMODE=disable
for s in exp_real_pg.py exp_voc.py; do
  caffeinate -i ~/.venvs/onecover-artifacts/bin/python -u experiments/E_real_tables/$s >> $L 2>&1 || echo "FAILED $s" >> $L
done
echo "finished $(date)" >> $L
