#!/bin/bash
# UNIQUE index against EXCLUDE constraint against trigger (exp_unique_vs_exclude.py, about 20 minutes), started
# once no million-row or tier-2 run is active, on mains power, with the 5-minute load below 6 for 5 minutes.
# Starts the private cluster (port 5488) if it is not running, and stops it again only if it started it.
# Log results/uvx.log. Usage: run_unique_vs_exclude.sh <directory of the cluster>
cd "$(dirname "$0")/../.."
PG=${PGBIN:-/Library/PostgreSQL/18/bin}; C=$1; PORT=5488; L=results/uvx.log; PY=~/.venvs/onecover-artifacts/bin/python
echo "waiting since $(date) for the million-row run to end, mains power and the 5-minute load below 6" >> $L
q=0; while [ $q -lt 5 ]; do l=$(sysctl -n vm.loadavg | awk '{print $3}')
  if ! pgrep -f 'run_xl_ks3|run_tier2|exp_db2_pg_extra|exp_db2_tier2' >/dev/null && pmset -g ps | grep -q "AC Power" && awk "BEGIN{exit !($l<6)}"; then q=$((q+1)); else q=0; fi; sleep 60; done
MINE=
if ! "$PG/pg_ctl" -D "$C" status >/dev/null 2>&1; then
  "$PG/pg_ctl" -D "$C" -o "-p $PORT -c listen_addresses=localhost -c unix_socket_directories=''" -l "$C/server.log" -w start >/dev/null && MINE=1; fi
echo "started $(date), load $(sysctl -n vm.loadavg)" >> $L
ps -axo %cpu,command | sort -nr | head -4 | cut -c1-110 >> $L
ONECOVER_DB_PORT=$PORT ONECOVER_DB_NAME=postgres PGGSSENCMODE=disable caffeinate -i $PY -u experiments/D_enforcement/exp_unique_vs_exclude.py >> $L 2>&1
echo "exit $? $(date), load $(sysctl -n vm.loadavg)" >> $L
[ -n "$MINE" ] && "$PG/pg_ctl" -D "$C" -m fast -w stop >/dev/null
echo "finished $(date)" >> $L
