#!/bin/bash
# Rerun the 1M-row runs at |Sigma| = 30 and 50 on the private PostgreSQL 18 cluster at night,
# after the extras have finished. The earlier records for these sizes, made while other jobs
# loaded the machine, are kept in xl_shared_machine.jsonl.
# Usage: run_pg18_xl_night.sh <directory of the cluster>
cd "$(dirname "$0")/../.."
PG=${PGBIN:-/Library/PostgreSQL/18/bin}; D=$1; L=results/D_enforcement/xl_night.log; F=results/D_enforcement/db2_pg_extra.jsonl
echo "waiting since $(date)" > $L
until grep -q finished results/D_enforcement/pg18_extras.log && pmset -g ps | grep -q "AC Power" \
      && ! "$PG/pg_ctl" -D "$D" status >/dev/null 2>&1; do sleep 300; done
python3 - "$F" <<'PY'
import json, sys
f = sys.argv[1]; L = open(f).read().splitlines()
moved = [l for l in L if json.loads(l)['exp'] == 'xl' and json.loads(l)['m'] in (30, 50)]
open('results/D_enforcement/xl_shared_machine.jsonl', 'a').write('\n'.join(moved) + '\n')
open(f, 'w').write('\n'.join(l for l in L if l not in moved) + '\n')
PY
ulimit -n 10240
"$PG/pg_ctl" -D "$D" -o "-p 5488 -c max_files_per_process=9000 -c listen_addresses=localhost -c unix_socket_directories=''" -l "$D/server.log" -w start >/dev/null
echo "started $(date), load $(sysctl -n vm.loadavg)" >> $L
ps -axo %cpu,command | sort -nr | head -5 | cut -c1-120 >> $L
ONECOVER_DB_PORT=5488 ONECOVER_DB_NAME=postgres PGGSSENCMODE=disable \
  caffeinate -i ~/.venvs/onecover-artifacts/bin/python -u experiments/D_enforcement/exp_db2_pg_extra.py xl >> $L 2>&1 || echo FAILED >> $L
"$PG/pg_ctl" -D "$D" -m fast -w stop >/dev/null
echo "finished $(date), load $(sysctl -n vm.loadavg)" >> $L
