#!/bin/bash
# After the 1M-row run stops the private cluster: restart it with max_files_per_process=9000
# (TeamSplits at level 1 has 3708 indexes) and resume exp_real_pg.py, which redoes only that table.
cd "$(dirname "$0")/../.."
PG=/Library/PostgreSQL/18/bin; D=$1; L=results/E_real_tables/pg18_run.log
until grep -q finished results/D_enforcement/xl_run.log && ! "$PG/pg_ctl" -D "$D" status >/dev/null 2>&1; do sleep 60; done
ulimit -n 10240
"$PG/pg_ctl" -D "$D" -o "-p 5488 -c max_files_per_process=9000 -c listen_addresses=localhost -c unix_socket_directories=''" -l "$D/server.log" -w start >/dev/null
echo "TeamSplits rerun started $(date), max_files_per_process $("$PG/psql" -h localhost -p 5488 -U postgres -Atc 'show max_files_per_process')" >> $L
ONECOVER_DB_PORT=5488 ONECOVER_DB_NAME=onecover PGGSSENCMODE=disable caffeinate -i ~/.venvs/onecover-artifacts/bin/python -u experiments/E_real_tables/exp_real_pg.py >> $L 2>&1 || echo "FAILED" >> $L
"$PG/pg_ctl" -D "$D" -m fast -w stop >/dev/null
echo "TeamSplits rerun finished $(date)" >> $L
