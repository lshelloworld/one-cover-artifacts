#!/bin/bash
# Defers the wide-schema PostgreSQL step (many hours) so that key set 3's million-row runs finish tonight.
# When the step starts it is stopped; the queue then goes on to key set 3, and a later rerun of run_tier2.sh
# repeats wide_pg, which is not marked done.
cd "$(dirname "$0")/.."
L=results/tier2.log
until grep -qE '^== wide_pg|^STOPPED|^finished' $L; do sleep 5; done
grep -q '^== wide_pg' $L || exit 0
sleep 5; pkill -TERM -f 'exp_db2_tier2.py wide pg'
echo "deferred wide_pg to a later run, so that key set 3 finishes tonight ($(date))" >> $L
