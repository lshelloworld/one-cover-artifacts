#!/bin/bash
# Experiment D (75 runs) on the local PostgreSQL: start on AC power, with no other experiment running.
cd "$(dirname "$0")/../.."
L=results/D_enforcement/pg18_run.log
echo "waiting since $(date)" > $L
ready() { pmset -g ps | grep -q "AC Power" && ! pgrep -f '[e]xp_db2_mysql|[e]xp_queries|[e]xp_covers|[m]ine_tpcds' >/dev/null; }
until ready; do sleep 300; done
echo "started $(date), load $(sysctl -n vm.loadavg)" >> $L
mv results/D_enforcement/db2_pg_log.jsonl results/D_enforcement/pg16/db2_pg_log.jsonl
caffeinate -i ~/.venvs/onecover-artifacts/bin/python -u experiments/D_enforcement/exp_db2_pg.py 1 >> $L 2>&1
echo "finished $(date)" >> $L
