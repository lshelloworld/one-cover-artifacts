#!/bin/bash
# Stops the tier 2 queue after the million-row runs of key set 3, or, if key set 3 is done before 01:30 on
# 16 November, after the second run of key set 1; the second run of key set 2 is left for Monday evening.
cd "$(dirname "$0")/.."
L=results/tier2.log
stopnow() {   # $1: the step being stopped, $2: what remains
  pkill -TERM -f 'run_tier2.sh'; sleep 1; pkill -TERM -f 'exp_db2_pg_extra.py xl'; sleep 3
  /Library/PostgreSQL/18/bin/pg_ctl -D ~/onecover-pg18/data -m fast -w stop >/dev/null 2>&1
  echo "stopped $1" >> $L
  echo "STOPPED as asked $(date); $2 remain; rerun results/run_tier2.sh ~/onecover-pg18/data" >> $L; exit 0; }
until grep -qE '^== xl_ks1_rep2|^STOPPED|^finished' $L; do sleep 5; done
grep -q '^== xl_ks1_rep2' $L || exit 0
if [ "$(date +%s)" -ge "$(date -j -f "%Y-%m-%d %H:%M" "2026-11-16 01:30" +%s)" ]; then stopnow xl_ks1_rep2 "the second runs of key sets 1 and 2"; fi
echo "key set 3 done before 01:30: running the second run of key set 1, then stopping ($(date))" >> $L
until grep -qE '^== xl_ks2_rep2|^STOPPED|^finished' $L; do sleep 5; done
grep -q '^== xl_ks2_rep2' $L && stopnow xl_ks2_rep2 "the second run of key set 2"
